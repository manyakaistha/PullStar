from pathlib import Path

import cv2
import numpy as np
import pytest

from backend.engine.alignment_engine import AlignmentEngine
from backend.engine import render_backend
from backend.services.job_manager import JobManager
from core.cancellation import CancellationToken, OperationCancelled
from core.compute import gpu_devices
from modules.transform import CropRegion
from test_field_alignment import write_sequence

gpu = pytest.mark.skipif(not gpu_devices(), reason="No usable OpenCL GPU on this test machine")


@gpu
@pytest.mark.parametrize("dtype", [np.uint8, np.uint16, np.float32])
@pytest.mark.parametrize("angle", [0, 0.37, -2.1])
def test_gpu_lanczos_matches_cpu_coordinates_and_precision(dtype, angle):
    rng = np.random.default_rng(83)
    maximum = 255 if dtype == np.uint8 else 65535
    image = rng.uniform(0, maximum, (96, 128, 3)).astype(dtype)
    crop = CropRegion(4, 124, 4, 92, 120, 88)
    matrix = cv2.getRotationMatrix2D((-25, -40), angle, 1)
    if angle:
        matrix[:, 2] += (2.37, -1.41)
    shape = (88, 120, 3)
    cpu = render_backend.CPURenderer(shape)
    renderer, reason = render_backend.create_renderer(shape, "opencl")
    try:
        assert renderer.backend == "opencl", reason
        expected = cpu.align(image, matrix, crop)
        frame = renderer.align(image, matrix, crop)
        actual = renderer.download(frame)
        np.testing.assert_allclose(actual, expected, rtol=0, atol=0.1)
        renderer.blend(frame)
        cpu.blend(expected)
        np.testing.assert_allclose(renderer.snapshot(), cpu.snapshot(), rtol=0, atol=0.1)
    finally:
        renderer.close()


@gpu
def test_gpu_masked_synthetic_frames_add_and_checkpoint_restore():
    image = np.random.default_rng(92).uniform(0, 65000, (96, 128, 3)).astype(np.float32)
    shape = image.shape
    crop = CropRegion(0, 128, 0, 96, 128, 96)
    cpu = render_backend.CPURenderer(shape)
    renderer, reason = render_backend.create_renderer(shape, "opencl")
    mask = np.linspace(0, 1, 96, dtype=np.float32)[:, None] * np.ones((1, 128), np.float32)
    matrix = cv2.getRotationMatrix2D((64, 48), 0.29, 1)
    try:
        assert renderer.backend == "opencl", reason
        first = renderer.align(image, np.eye(2, 3), crop)
        uploaded = renderer.upload_mask(mask)
        synthetic = renderer.warp(renderer.masked(first, uploaded), matrix)
        expected = cpu.warp(cpu.masked(image, mask), matrix)
        renderer.blend(synthetic, fade=0.8, mask=uploaded)
        cpu.blend(expected, fade=0.8, mask=mask)
        renderer.blend(first, add=True)
        cpu.blend(image, add=True)
        np.testing.assert_allclose(renderer.snapshot(), cpu.snapshot(), rtol=0, atol=0.2)
        saved = renderer.snapshot()
        renderer.restore(saved)
        np.testing.assert_array_equal(renderer.snapshot(), saved)
    finally:
        renderer.close()


def test_unavailable_gpu_falls_back_with_a_reason(monkeypatch):
    monkeypatch.setattr(render_backend, "gpu_devices", lambda: [])
    renderer, reason = render_backend.create_renderer((32, 40, 3), "opencl")
    assert renderer.backend == "cpu"
    assert "No usable OpenCL" in reason


def test_gpu_memory_budget_rejects_before_allocation(monkeypatch):
    from types import SimpleNamespace
    device = SimpleNamespace(name="Small GPU", max_mem_alloc_size=1024, global_mem_size=4096)
    monkeypatch.setattr(render_backend, "gpu_devices", lambda: [device])
    renderer, reason = render_backend.create_renderer((32, 40, 3), "opencl")
    assert renderer.backend == "cpu"
    assert "memory budget" in reason


def test_failed_device_quality_check_uses_cpu(monkeypatch):
    closed = []
    class BadRenderer(render_backend.CPURenderer):
        def __init__(self, shape, device, cancel_check):
            super().__init__(shape, cancel_check)
        def validate(self):
            raise render_backend.AccelerationError("GPU quality check failed")
        def close(self):
            closed.append(True)
    monkeypatch.setattr(render_backend, "gpu_devices", lambda: [object()])
    monkeypatch.setattr(render_backend, "OpenCLRenderer", BadRenderer)
    renderer, reason = render_backend.create_renderer((32, 40, 3), "opencl")
    assert renderer.backend == "cpu"
    assert "quality check" in reason
    assert closed == [True]


@gpu
def test_gpu_frame_boundary_honors_cancellation():
    token = CancellationToken()
    renderer, reason = render_backend.create_renderer((32, 40, 3), "opencl", token.check)
    try:
        assert renderer.backend == "opencl", reason
        token.cancel()
        with pytest.raises(OperationCancelled):
            renderer.align(np.zeros((32, 40, 3), np.uint8), np.eye(2, 3),
                            CropRegion(0, 40, 0, 32, 40, 32))
    finally:
        renderer.close()


@gpu
def test_real_gpu_trails_preserve_16_bit_cpu_output(tmp_path):
    write_sequence(tmp_path, dtype=np.uint16)
    engine = AlignmentEngine(tmp_path, tmp_path / "cpu.tiff", extension_factor=1.5,
                              ghost_frames_per_real=2, use_foreground_mask=True,
                              use_checkpoint=False, compute_backend="cpu", cpu_workers=3)
    engine.prepare()
    _, transforms = engine.run_pass1()
    crop = engine.calculate_crop(transforms)
    reference = cv2.imread(engine.run_pass2(transforms, crop), cv2.IMREAD_UNCHANGED)
    engine.output_file = tmp_path / "gpu.tiff"
    engine.compute_backend = "opencl"
    actual = cv2.imread(engine.run_pass2(transforms, crop), cv2.IMREAD_UNCHANGED)
    assert engine.compute_info["backend"] == "opencl"
    assert actual.dtype == reference.dtype == np.uint16
    np.testing.assert_allclose(actual, reference, rtol=0, atol=1)


def test_mid_render_gpu_failure_replays_on_cpu(tmp_path, monkeypatch):
    write_sequence(tmp_path)
    engine = AlignmentEngine(tmp_path, tmp_path / "reference.tiff", extension_factor=2,
                              ghost_frames_per_real=2, use_foreground_mask=False,
                              use_checkpoint=False, compute_backend="cpu")
    engine.prepare()
    _, transforms = engine.run_pass1()
    crop = engine.calculate_crop(transforms)
    reference = cv2.imread(engine.run_pass2(transforms, crop), cv2.IMREAD_UNCHANGED)

    class FailingRenderer(render_backend.CPURenderer):
        backend = "opencl"
        device_name = "Simulated failing GPU"
        def warp(self, frame, matrix):
            raise render_backend.AccelerationError("GPU memory lost")

    create = render_backend.create_renderer
    def factory(shape, preference="auto", cancel_check=None):
        if preference != "cpu":
            return FailingRenderer(shape, cancel_check), None
        return create(shape, preference, cancel_check)

    monkeypatch.setattr("backend.engine.field_alignment.create_renderer", factory)
    engine.compute_backend = "auto"
    engine.output_file = tmp_path / "replayed.tiff"
    actual = cv2.imread(engine.run_pass2(transforms, crop), cv2.IMREAD_UNCHANGED)
    assert engine.compute_info["backend"] == "cpu"
    assert "GPU memory lost" in engine.compute_info["fallback_reason"]
    np.testing.assert_array_equal(actual, reference)
    assert not list(tmp_path.glob(".staraligner-*"))


@gpu
def test_gpu_trail_cancel_stops_without_publishing(tmp_path):
    write_sequence(tmp_path)
    manager = JobManager()
    output = tmp_path / "gpu-cancel.tiff"
    job_id = manager.create_job({"input_dir": str(tmp_path), "output_file": str(output),
                                 "compute_backend": "opencl", "use_checkpoint": False,
                                 "extension_factor": 2, "ghost_frames_per_real": 2})
    backends = []
    def observe(update):
        if (update.get("stage") == "pass2" and update.get("current", 0) >= 2
                and update["status"] == "running"):
            backends.append(update.get("compute", {}).get("backend"))
            manager.cancel_job(job_id)
    manager.subscribe(job_id, observe)
    manager._run_job(job_id)
    assert manager.get_job(job_id)["status"] == "cancelled"
    assert backends and all(b == "opencl" for b in backends)
    assert not output.exists()
    assert not list(tmp_path.glob(".staraligner-*"))
