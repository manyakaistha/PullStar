"""CPU and portable OpenCL rendering with the same Lanczos-4 sampling grid."""

from dataclasses import dataclass

import cv2
import numpy as np

from core.cancellation import check_cancelled
from core.compute import gpu_devices, memory_bytes


class AccelerationError(RuntimeError):
    pass


class CPURenderer:
    backend = "cpu"
    device_name = "CPU"

    def __init__(self, shape, cancel_check=None):
        self.accumulator = np.zeros(shape, np.float32)
        self.cancel_check = cancel_check
        from modules.transform import WarpWorkspace
        self._warp_workspace = WarpWorkspace()

    def align(self, image, matrix, crop):
        check_cancelled(self.cancel_check)
        from modules.transform import warp_to_crop
        return warp_to_crop(image.astype(np.float32, copy=False), matrix, crop,
                            cancel_check=self.cancel_check, workspace=self._warp_workspace)

    def warp(self, frame, matrix):
        check_cancelled(self.cancel_check)
        return cv2.warpAffine(frame, matrix, (frame.shape[1], frame.shape[0]),
                              flags=cv2.INTER_LANCZOS4)

    def upload_mask(self, mask):
        return mask

    def masked(self, frame, mask):
        return frame * mask[:, :, None]

    def blend(self, frame, *, add=False, fade=1.0, mask=None):
        check_cancelled(self.cancel_check)
        value = frame if fade == 1 else frame * np.float32(fade)
        if mask is not None:
            value = value * mask[:, :, None]
        if add:
            self.accumulator += value
        else:
            np.maximum(self.accumulator, value, out=self.accumulator)

    def download(self, frame):
        return frame

    def snapshot(self):
        check_cancelled(self.cancel_check)
        return self.accumulator

    def restore(self, image):
        self.accumulator[:] = image

    def close(self):
        pass


_KERNEL = r"""
#pragma OPENCL FP_CONTRACT OFF
inline float sample(__global const uchar *source, int index, int kind) {
    if (kind == 0) return (float)source[index];
    if (kind == 1) return (float)((__global const ushort *)source)[index];
    return ((__global const float *)source)[index];
}
__kernel void warp_lanczos(
    __global const uchar *source, __global float *output,
    int sw, int sh, int dw, int dh, int kind,
    __global const int *dx, __global const int *dy,
    __global const int *rx, __global const int *ry,
    __constant const float *weights) {
    int x = get_global_id(0), y = get_global_id(1);
    if (x >= dw || y >= dh) return;
    int sx = (dx[x] + rx[y]) >> 5, sy = (dy[x] + ry[y]) >> 5;
    int bx = (sx >> 5) - 3, by = (sy >> 5) - 3;
    int ax = (sx & 31) * 8, ay = (sy & 31) * 8;
    float3 value = (float3)(0.0f);
    for (int i = 0; i < 8; i++) {
        int iy = by + i;
        float3 horizontal = (float3)(0.0f);
        if (iy >= 0 && iy < sh) {
            for (int j = 0; j < 8; j++) {
                int ix = bx + j;
                if (ix >= 0 && ix < sw) {
                    int at = (iy * sw + ix) * 3;
                    horizontal += (float3)(sample(source, at, kind), sample(source, at+1, kind),
                                            sample(source, at+2, kind)) * weights[ax+j];
                }
            }
        }
        value += horizontal * weights[ay+i];
    }
    int at = (y * dw + x) * 3;
    output[at] = value.x; output[at+1] = value.y; output[at+2] = value.z;
}
__kernel void mask_frame(__global const float *source, __global const float *mask,
                         __global float *output, int count) {
    int i = get_global_id(0);
    if (i < count) output[i] = source[i] * mask[i/3];
}
__kernel void blend(__global const float *frame, __global float *accumulator,
                     __global const float *mask, int count, int masked, float fade, int add) {
    int i = get_global_id(0);
    if (i >= count) return;
    float value = frame[i] * fade;
    if (masked) value *= mask[i/3];
    accumulator[i] = add ? accumulator[i] + value
        : ((isnan(value) || isnan(accumulator[i])) ? NAN : fmax(accumulator[i], value));
}
"""


@dataclass
class GPUFrame:
    buffer: object
    shape: tuple
    dtype: np.dtype


class OpenCLRenderer:
    backend = "opencl"

    def __init__(self, shape, device, cancel_check=None):
        import pyopencl as cl
        self.cl = cl
        self.cancel_check = cancel_check
        self.shape = shape
        self.device_name = device.name
        size = int(np.prod(shape)) * 4
        if size > 0.8 * device.max_mem_alloc_size or size * 4 > min(
            0.6 * device.global_mem_size, 0.35 * memory_bytes()
        ):
            raise AccelerationError("Image exceeds the GPU memory budget")
        check_cancelled(cancel_check)
        try:
            self.context = cl.Context([device])
            self.queue = cl.CommandQueue(self.context)
            program = cl.Program(self.context, _KERNEL).build(options=["-cl-std=CL1.2"])
            self.warp_kernel = cl.Kernel(program, "warp_lanczos")
            self.mask_kernel = cl.Kernel(program, "mask_frame")
            self.blend_kernel = cl.Kernel(program, "blend")
            self.accumulator = cl.Buffer(self.context, cl.mem_flags.READ_WRITE, size)
            cl.enqueue_fill_buffer(self.queue, self.accumulator, np.float32(0), 0, size).wait()
            self._map_buffers = {}
            # Frame buffers are reused after each operation waits on its
            # kernel. This avoids repeated OpenCL allocation/free churn for
            # long sequences (the same cache pattern used by Siril's stack
            # workers).
            self._source_buffers = {}
            self._scratch_buffers = {"warp": {}, "mask": {}}
            # The current aligned real frame remains live while one or more
            # synthetic frames are generated from it. Keep its output buffer
            # out of the short-lived synthetic warp pool.
            self._reserved_warp_buffer = None
            offsets = np.arange(-3, 5)[None, :] - np.arange(32)[:, None] / 32
            weights = np.sinc(offsets) * np.sinc(offsets / 4)
            weights /= weights.sum(axis=1, keepdims=True)
            weights[0] = 0
            weights[0, 3] = 1
            self.weights = self._buffer(weights.astype(np.float32))
        except cl.Error as error:
            raise AccelerationError(f"OpenCL initialization failed: {error}") from error
        check_cancelled(cancel_check)

    def _buffer(self, array):
        return self.cl.Buffer(self.context, self.cl.mem_flags.READ_ONLY | self.cl.mem_flags.COPY_HOST_PTR,
                               hostbuf=np.ascontiguousarray(array))

    def _reusable_empty(self, shape, purpose, avoid=None, reserved=None):
        key = tuple(shape)
        pool = self._scratch_buffers[purpose].setdefault(key, [])
        required = 2 if purpose == "warp" else 1
        while len(pool) < required:
            pool.append(GPUFrame(self.cl.Buffer(self.context, self.cl.mem_flags.READ_WRITE,
                                                int(np.prod(shape)) * 4),
                                 shape, np.dtype("float32")))
        for frame in pool:
            if frame.buffer is not avoid and frame.buffer is not reserved:
                return frame
        # The two-buffer warp pool should make this unreachable, but retaining
        # a safe fallback is preferable to aliasing source and destination.
        frame = GPUFrame(self.cl.Buffer(self.context, self.cl.mem_flags.READ_WRITE,
                                        int(np.prod(shape)) * 4),
                         shape, np.dtype("float32"))
        pool.append(frame)
        return frame

    def _upload_frame(self, image):
        key = (tuple(image.shape), np.dtype(image.dtype).str)
        frame = self._source_buffers.get(key)
        if frame is None:
            frame = self.cl.Buffer(self.context, self.cl.mem_flags.READ_ONLY,
                                   int(image.nbytes))
            self._source_buffers[key] = frame
        self.cl.enqueue_copy(self.queue, frame, np.ascontiguousarray(image),
                             is_blocking=False)
        return GPUFrame(frame, image.shape, image.dtype)

    def _map_buffer(self, slot, array):
        """Reuse coordinate buffers across Lanczos warps of the same length."""
        array = np.ascontiguousarray(array, dtype=np.int32)
        current = self._map_buffers.get(slot)
        if current is None or current.size < array.nbytes:
            current = self.cl.Buffer(self.context, self.cl.mem_flags.READ_ONLY, array.nbytes)
            self._map_buffers[slot] = current
        self.cl.enqueue_copy(self.queue, current, array, is_blocking=False)
        return current

    def _wait(self, event):
        try:
            event.wait()
        except self.cl.Error as error:
            raise AccelerationError(f"GPU rendering failed: {error}") from error
        check_cancelled(self.cancel_check)

    def _warp(self, frame, matrix, width, height, x_offset=0, y_offset=0,
              reserve_output=False):
        check_cancelled(self.cancel_check)
        inverse = cv2.invertAffineTransform(np.asarray(matrix, dtype=np.float64))
        x = np.arange(width, dtype=float) + x_offset
        y = np.arange(height, dtype=float) + y_offset
        # Match OpenCV's 10-bit affine coordinate rounding and 1/32-pixel
        # interpolation table, including the crop's original destination origin.
        maps = [np.rint(inverse[0, 0] * x * 1024).astype(np.int32),
                np.rint(inverse[1, 0] * x * 1024).astype(np.int32),
                np.rint((inverse[0, 1] * y + inverse[0, 2]) * 1024).astype(np.int32) + 16,
                np.rint((inverse[1, 1] * y + inverse[1, 2]) * 1024).astype(np.int32) + 16]
        try:
            output = self._reusable_empty(
                (height, width, 3), "warp", avoid=frame.buffer,
                reserved=None if reserve_output else self._reserved_warp_buffer)
            if reserve_output:
                self._reserved_warp_buffer = output.buffer
            kind = {np.dtype("uint8"): 0, np.dtype("uint16"): 1, np.dtype("float32"): 2}[frame.dtype]
            map_buffers = tuple(self._map_buffer(index, array) for index, array in enumerate(maps))
            event = self.warp_kernel(self.queue, (width, height), None, frame.buffer, output.buffer,
                                     *map(np.int32, (frame.shape[1], frame.shape[0], width, height, kind)),
                                     *map_buffers, self.weights)
            self._wait(event)
            return output
        except self.cl.Error as error:
            raise AccelerationError(f"GPU warp failed: {error}") from error

    def align(self, image, matrix, crop):
        if image.dtype not in (np.uint8, np.uint16, np.float32):
            image = image.astype(np.float32)
        try:
            frame = self._upload_frame(image)
            return self._warp(frame, matrix, crop.width, crop.height, crop.x_start, crop.y_start,
                              reserve_output=True)
        except self.cl.Error as error:
            raise AccelerationError(f"GPU upload failed: {error}") from error

    def warp(self, frame, matrix):
        return self._warp(frame, matrix, frame.shape[1], frame.shape[0])

    def upload_mask(self, mask):
        try:
            return GPUFrame(self._buffer(mask.astype(np.float32)), mask.shape, np.dtype("float32"))
        except self.cl.Error as error:
            raise AccelerationError(f"GPU mask upload failed: {error}") from error

    def masked(self, frame, mask):
        try:
            output = self._reusable_empty(frame.shape, "mask", avoid=frame.buffer)
            self._wait(self.mask_kernel(self.queue, (int(np.prod(frame.shape)),), None,
                                        frame.buffer, mask.buffer, output.buffer,
                                        np.int32(np.prod(frame.shape))))
            return output
        except self.cl.Error as error:
            raise AccelerationError(f"GPU mask failed: {error}") from error

    def blend(self, frame, *, add=False, fade=1.0, mask=None):
        try:
            self._wait(self.blend_kernel(self.queue, (int(np.prod(self.shape)),), None,
                                         frame.buffer, self.accumulator,
                                         mask.buffer if mask is not None else self.accumulator,
                                         np.int32(np.prod(self.shape)), np.int32(mask is not None),
                                         np.float32(fade), np.int32(add)))
        except self.cl.Error as error:
            raise AccelerationError(f"GPU blending failed: {error}") from error

    def download(self, frame):
        try:
            output = np.empty(frame.shape, frame.dtype)
            self._wait(self.cl.enqueue_copy(self.queue, output, frame.buffer))
            return output
        except self.cl.Error as error:
            raise AccelerationError(f"GPU readback failed: {error}") from error

    def snapshot(self):
        return self.download(GPUFrame(self.accumulator, self.shape, np.dtype("float32")))

    def restore(self, image):
        try:
            self._wait(self.cl.enqueue_copy(self.queue, self.accumulator,
                                            np.ascontiguousarray(image, dtype=np.float32)))
        except self.cl.Error as error:
            raise AccelerationError(f"GPU checkpoint restore failed: {error}") from error

    def close(self):
        try:
            self.queue.finish()
        except self.cl.Error:
            pass

    def validate(self):
        """Check this device/compiler before trusting it with a user's render."""
        from types import SimpleNamespace
        image = np.random.default_rng(281).integers(0, 65535, (32, 40, 3), dtype=np.uint16)
        matrix = cv2.getRotationMatrix2D((20, 16), 1.37, 1)
        matrix[:, 2] += (1.23, -0.87)
        crop = SimpleNamespace(width=36, height=28, x_start=2, y_start=2)
        expected = cv2.warpAffine(image.astype(np.float32), matrix, (40, 32),
                                  flags=cv2.INTER_LANCZOS4)[2:30, 2:38]
        actual = self.download(self.align(image, matrix, crop))
        if not np.isfinite(actual).all() or np.max(np.abs(actual - expected)) > 0.5:
            raise AccelerationError("GPU quality check did not match CPU Lanczos rendering")


def create_renderer(shape, preference="auto", cancel_check=None):
    reason = None
    if preference != "cpu":
        devices = gpu_devices()
        if devices and (preference == "opencl" or shape[0] * shape[1] >= 1024**2):
            failures = []
            for device in devices:
                try:
                    renderer = OpenCLRenderer(shape, device, cancel_check)
                    try:
                        renderer.validate()
                    except BaseException:
                        renderer.close()
                        raise
                    return renderer, None
                except AccelerationError as error:
                    failures.append(str(error))
            reason = "; ".join(failures)[:320]
        elif not devices:
            reason = "No usable OpenCL GPU/driver is available"
        else:
            reason = "Small images use the CPU to avoid GPU setup overhead"
    return CPURenderer(shape, cancel_check), reason
