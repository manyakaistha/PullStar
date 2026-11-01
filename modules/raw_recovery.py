"""Noise-aware RAW measurements and conservative linear-light denoising."""

from pathlib import Path
from dataclasses import dataclass
import warnings
from functools import lru_cache

import cv2
import numpy as np
import rawpy
from astropy.utils.exceptions import AstropyWarning
from photutils.detection import DAOStarFinder

from core.cancellation import check_cancelled
from modules.astronomy import _prepare_detection_image, MAX_STARS


def _orient(image, flip):
    if flip in (3, 5, 6):
        image = np.rot90(image, {3: 2, 5: 1, 6: -1}[flip])
    elif flip == 1:
        image = image[:, ::-1]
    elif flip == 2:
        image = image[::-1]
    elif flip == 4:
        image = image.T
    elif flip == 7:
        image = image.T[::-1, ::-1]
    return np.ascontiguousarray(image)


def sensor_plane(raw):
    """Bin Bayer cells before demosaicing/WB, retaining signed dark signal.

    A half-resolution sample is centred at native coordinate (2*x+.5, 2*y+.5).
    Other sensor layouts keep using LibRaw's established development path.
    """
    pattern = raw.raw_pattern
    if pattern is None or pattern.shape != (2, 2) or raw.sizes.pixel_aspect != 1:
        return None
    data = raw.raw_image_visible
    height, width = data.shape
    if height % 2 or width % 2 or (height, width) != (raw.sizes.height, raw.sizes.width):
        return None
    plane = np.zeros((height // 2, width // 2), np.float32)
    work = np.empty_like(plane)
    black = raw.black_level_per_channel
    for y in range(2):
        for x in range(2):
            # Retain the original subtract-then-add order with one reusable
            # float32 buffer (also handles non-integer black-level metadata).
            np.copyto(work, data[y::2, x::2], casting="unsafe")
            np.subtract(work, black[int(pattern[y, x])], out=work)
            np.add(plane, work, out=plane)
    plane *= 0.25
    return _orient(plane, raw.sizes.flip)


def detect_streak_sources(image, cancel_check=None):
    """Measure short exposure streaks without requiring a round stellar core."""
    check_cancelled(cancel_check)
    prepared = _prepare_detection_image(image)
    if prepared is None:
        return np.empty((0, 2))
    normalized, smoothed, foreground, scale = prepared
    height, width = normalized.shape
    candidates = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", AstropyWarning)
        # DAOFIND computes magnitudes for negative-flux noise candidates too;
        # only centroid/positive-flux measurements are used here.
        warnings.filterwarnings("ignore", message="invalid value encountered in log10",
                                category=RuntimeWarning, module="photutils.detection.core")
        for fwhm in (3.0, 6.0):
            check_cancelled(cancel_check)
            sources = DAOStarFinder(threshold=4, fwhm=fwhm, roundlo=-2, roundhi=2,
                                    exclude_border=True)(smoothed, mask=foreground)
            if sources is None:
                continue
            xcol = "x_centroid" if "x_centroid" in sources.colnames else "xcentroid"
            ycol = "y_centroid" if "y_centroid" in sources.colnames else "ycentroid"
            sources.sort("flux", reverse=True)
            rows = sources[:600]
            x_all = np.asarray(rows[xcol], dtype=float)
            y_all = np.asarray(rows[ycol], dtype=float)
            flux_all = np.asarray(rows["flux"], dtype=float)
            patch_y = np.arange(-4, 5)
            patch_x = np.arange(-4, 5)
            for start in range(0, len(rows), 256):
                check_cancelled(cancel_check)
                x = x_all[start:start + 256]
                y = y_all[start:start + 256]
                flux = flux_all[start:start + 256]
                finite = np.isfinite(x) & np.isfinite(y)
                xi = np.rint(np.where(finite, x, 0)).astype(np.intp)
                yi = np.rint(np.where(finite, y, 0)).astype(np.intp)
                finite &= (xi >= 5) & (yi >= 5) & (xi < width - 5) & (yi < height - 5)
                if not finite.any():
                    continue
                x, y, xi, yi, flux = (arr[finite] for arr in (x, y, xi, yi, flux))
                patch = normalized[yi[:, None, None] + patch_y[None, :, None],
                                   xi[:, None, None] + patch_x[None, None, :]]
                rim = np.concatenate((patch[:, 0, :], patch[:, -1, :],
                                      patch[:, :, 0], patch[:, :, -1]), axis=1)
                signal = patch - np.median(rim, axis=1)[:, None, None]
                positive = np.maximum(signal, 0)
                core = positive[:, 3:6, 3:6]
                core_sum = core.sum(axis=(1, 2))
                keep = ((signal.sum(axis=(1, 2)) >= 20) &
                        (core.max(axis=(1, 2)) <= 0.75 * np.maximum(core_sum, 1e-6)))
                candidates.extend((float(px), float(py), float(pv))
                                  for px, py, pv in zip(x[keep], y[keep], flux[keep]))
    points, occupied = [], {}
    for x, y, flux in sorted(candidates, key=lambda item: -item[2]):
        check_cancelled(cancel_check)
        cell = int(x * 8 / width), int(y * 6 / height)
        if occupied.get(cell, 0) >= 5:
            continue
        if any((x-a)**2 + (y-b)**2 < 16 for a, b in points):
            continue
        points.append((x, y))
        occupied[cell] = occupied.get(cell, 0) + 1
        if len(points) == MAX_STARS:
            break
    return (np.asarray(points).reshape(-1, 2) + 0.5) * scale - 0.5


@dataclass
class MeasuredField:
    shape: tuple
    points: np.ndarray
    registration: np.ndarray | None = None


def measure_field(path: Path, *, recovery=True, cancel_check=None):
    from modules.io_utils import is_raw_file, load_image
    from modules.astronomy import detect_sources

    check_cancelled(cancel_check)
    if recovery and is_raw_file(path):
        try:
            with rawpy.imread(str(path)) as raw:
                plane = sensor_plane(raw)
            check_cancelled(cancel_check)
            if plane is not None:
                points = detect_streak_sources(plane, cancel_check) * 2 + 0.5
                if len(points) < 30:
                    # Very sparse, undersampled round stars can be sharper than
                    # the streak kernels. Retain the established full-resolution
                    # detector's additional centroids in those fields.
                    developed = load_image(path)
                    extra = detect_sources(developed, cancel_check=cancel_check)
                    combined = list(points)
                    for point in extra:
                        if all(np.linalg.norm(point - other) >= 3 for other in combined):
                            combined.append(point)
                        if len(combined) == MAX_STARS:
                            break
                    points = np.asarray(combined).reshape(-1, 2)
                registration = np.maximum(plane - cv2.GaussianBlur(plane, (0, 0), 10), 0)
                return MeasuredField((plane.shape[0] * 2, plane.shape[1] * 2), points,
                                     registration)
        except rawpy.LibRawError:
            # The shared loader provides the filename and decoder diagnostic.
            pass
    image = load_image(path)
    check_cancelled(cancel_check)
    return MeasuredField(image.shape[:2], detect_sources(image, cancel_check=cancel_check))


def extract_field(path: Path, *, recovery=True, cancel_check=None):
    """Compatibility view for callers comparing source-coordinate arrays."""
    result = measure_field(path, recovery=recovery, cancel_check=cancel_check)
    return result.shape, result.points


def match_fields(source, target, cancel_check=None):
    """Seed short RAW offsets with FFT correlation, then verify real stars.

    Correlation alone never authorizes a transform: centroid counts, rigid-fit
    residuals, field spread, and confidence retain their usual checks.
    """
    from modules.astronomy import match_sources
    translation = None
    check_cancelled(cancel_check)
    if source.registration is not None and target.registration is not None:
        if source.registration.shape != target.registration.shape:
            return None
        window = _hanning_window(source.registration.shape)
        # ``phaseCorrelate`` applies the supplied window internally. Keep the
        # source fields read-only and avoid copies when the registration arrays
        # are already contiguous float32 buffers.
        source_registration = np.ascontiguousarray(source.registration, dtype=np.float32)
        target_registration = np.ascontiguousarray(target.registration, dtype=np.float32)
        offset, response = cv2.phaseCorrelate(source_registration,
                                             target_registration, window)
        check_cancelled(cancel_check)
        if np.isfinite([*offset, response]).all() and response >= 0.2:
            translation = np.asarray(offset) * 2
    return match_sources(source.points, target.points, cancel_check,
                         initial_translation=translation)


def denoise_linear(image):
    """Local Wiener shrinkage: smooth noise while retaining high-SNR structure.

    All arithmetic is float32 in linear light; no eight-bit conversion, global
    blur, or spatial threshold is used to erase faint stars from the image.
    """
    result = np.empty(image.shape, np.float32)
    data = np.empty(image.shape[:2], np.float32)
    mean = np.empty_like(data)
    variance = np.empty_like(data)
    work = np.empty_like(data)
    stride = max(1, int(np.sqrt(image.shape[0] * image.shape[1] / 180_000)))
    for channel in range(3):
        np.copyto(data, image[:, :, channel], casting="unsafe")
        cv2.GaussianBlur(data, (0, 0), 1, dst=work)
        np.subtract(data, work, out=work)
        sample = work[::stride, ::stride]
        sigma = float(np.median(np.abs(sample - np.median(sample)))) * 1.4826
        noise = max(sigma * sigma, 1e-8)
        cv2.blur(data, (5, 5), dst=mean)
        np.multiply(data, data, out=work)
        cv2.blur(work, (5, 5), dst=variance)
        np.multiply(mean, mean, out=work)
        np.subtract(variance, work, out=variance)
        np.maximum(variance, 0, out=variance)
        np.subtract(variance, noise, out=work)
        np.maximum(work, 0, out=work)
        np.maximum(variance, noise, out=variance)
        np.divide(work, variance, out=work)
        np.subtract(data, mean, out=data)
        np.multiply(work, data, out=data)
        np.add(mean, data, out=result[:, :, channel])
    np.clip(result, 0, 65535, out=result)
    return result


def display_gamma(linear):
    """Use the existing development path's Rec.709-style display curve."""
    # Chunk the curve rather than quantizing floating inputs to a LUT. Preserve
    # the legacy float64 evaluation of integer inputs and float32 evaluation of
    # linear denoised data, including rounding at uint16 boundaries.
    dtype = np.float32 if linear.dtype == np.float32 else np.float64
    output = np.empty(linear.shape, np.uint16)
    rows = max(1, 262144 // max(1, int(np.prod(linear.shape[1:]))))
    for start in range(0, len(linear), rows):
        chunk = linear[start:start + rows]
        value = np.divide(chunk, 65535.0, dtype=dtype)
        np.clip(value, 0, 1, out=value)
        low = value < 0.018
        encoded = np.power(value, 1 / 2.222)
        np.multiply(encoded, 1.099, out=encoded)
        np.subtract(encoded, 0.099, out=encoded)
        np.multiply(value, 4.5, out=value, where=low)
        np.copyto(encoded, value, where=low)
        np.multiply(encoded, 65535, out=encoded)
        np.rint(encoded, out=encoded)
        np.clip(encoded, 0, 65535, out=encoded)
        output[start:start + rows] = encoded
    return output


@lru_cache(maxsize=16)
def _hanning_window(shape):
    """Cache phase-correlation windows by registration shape."""
    height, width = shape[-2:]
    window = cv2.createHanningWindow((width, height), cv2.CV_32F)
    window.flags.writeable = False
    return window
