"""Cancellation must stop work and preserve previously completed exports."""

from pathlib import Path
from threading import Event
from time import monotonic, sleep
import subprocess
import sys

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.job_manager import JobManager
from core.cancellation import CancellationToken, OperationCancelled
from test_field_alignment import write_sequence


def sources(root, automatic=False):
    if automatic:
        write_sequence(root)
    else:
        for index in range(12):
            image = np.zeros((64, 80, 3), np.uint8)
            cv2.circle(image, (40, 30), 2, (255, 255, 255), -1)
            cv2.imwrite(str(root / f"frame_{index:02}.png"), image)


def config(root, automatic=False, **options):
    return {"input_dir": str(root), "output_file": str(root / "trails.tiff"),
            "sort_by_time": False, "use_checkpoint": False, "use_foreground_mask": False,
            **({} if automatic else {"polaris": (40, 30)}), **options}


@pytest.mark.parametrize("automatic,stage,activity,current", [
    (False, "preparation", "validating", 0),
    (False, "pass1", "tracking", 2),
    (True, "pass1", "tracking", 2),
    (False, "pass2", "processing_frame", 2),
    (True, "pass2", "processing_frame", 2),
    (True, "pass2", "saving", 0),
])
def test_cancel_real_processing_preserves_previous_output(tmp_path, automatic, stage, activity, current):
    sources(tmp_path, automatic)
    output = tmp_path / "trails.tiff"
    output.write_bytes(b"previous completed export")
    manager = JobManager()
    job_id = manager.create_job(config(tmp_path, automatic, extension_factor=2,
                                        ghost_frames_per_real=2))
    updates = []

    def observe(update):
        updates.append(update)
        if (update["stage"] == stage and update.get("activity") == activity
                and update.get("current", 0) >= current and update["status"] == "running"):
            manager.cancel_job(job_id)

    manager.subscribe(job_id, observe)
    manager._run_job(job_id)
    job = manager.get_job(job_id)
    assert job["status"] == "cancelled"
    assert job["result_path"] is None
    assert job["error"] is None
    assert not any(u["status"] == "completed" for u in updates)
    assert output.read_bytes() == b"previous completed export"
    assert not list(tmp_path.glob(".staraligner-*"))
    manager._emit(job_id, {"status": "running", "progress": 1})
    assert manager.cancel_job(job_id)["status"] == "cancelled"


def test_cancel_before_start_does_no_work_and_new_job_can_complete(tmp_path):
    sources(tmp_path)
    manager = JobManager()
    cancelled = manager.create_job(config(tmp_path))
    assert manager.cancel_job(cancelled)["status"] == "cancelled"
    manager.start_job(cancelled)
    assert cancelled not in manager.workers
    assert not (tmp_path / "trails.tiff").exists()
    restarted = manager.create_job(config(tmp_path))
    manager._run_job(restarted)
    assert manager.get_job(restarted)["status"] == "completed"
    assert cv2.imread(str(tmp_path / "trails.tiff")) is not None
    assert manager.cancel_job(restarted)["status"] == "completed"


def test_detection_cancel_endpoint_stops_the_worker(tmp_path, monkeypatch):
    sources(tmp_path)
    manager = JobManager()
    monkeypatch.setattr("backend.api.router.job_manager", manager)
    entered, stopped = Event(), Event()

    def detect(paths, frame_step, cancel_check, workers, raw_noise_reduction):
        assert raw_noise_reduction is False
        entered.set()
        try:
            while True:
                cancel_check()
                sleep(0.005)
        finally:
            stopped.set()

    monkeypatch.setattr("modules.auto_selector.auto_detect_stars", detect)
    with TestClient(app) as client:
        start = client.post("/api/stars/detect/start", json={
            "path": str(tmp_path), "raw_noise_reduction": False,
        })
        assert start.status_code == 200
        job_id = start.json()["job_id"]
        assert entered.wait(2)
        cancelled = client.post(f"/api/jobs/{job_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] in ("cancelling", "cancelled")
        assert stopped.wait(2)
        deadline = monotonic() + 2
        while monotonic() < deadline:
            status = client.get(f"/api/jobs/{job_id}").json()
            if status["status"] == "cancelled":
                break
            sleep(0.005)
        assert status["status"] == "cancelled"
        assert "result" not in status
        assert client.post("/api/jobs/missing/cancel").status_code == 404


def test_real_ghost_generation_stops_between_rotations(monkeypatch):
    import synthesis.synthetic_generator as generator
    token = CancellationToken()
    calls = []
    rotate = generator.rotate_image

    def stop_after_first(*args, **kwargs):
        calls.append(1)
        result = rotate(*args, **kwargs)
        token.cancel()
        return result

    monkeypatch.setattr(generator, "rotate_image", stop_after_first)
    with pytest.raises(OperationCancelled):
        generator.generate_ghost_frames(np.ones((32, 40, 3), np.float32), 0, 2, (20, 16),
                                         num_ghosts=20, extension_factor=2,
                                         cancel_check=token.check)
    assert len(calls) == 1


@pytest.mark.parametrize("automatic", [False, True])
def test_cancelling_video_finalization_terminates_encoder(tmp_path, monkeypatch, automatic):
    from video.ffmpeg_writer import create_video_writer
    sources(tmp_path, automatic)
    previous = tmp_path / "trails.mp4"
    previous.write_bytes(b"previous completed video")
    encoders = []

    def create(output_path, width, height, fps, quality, **options):
        encoder = create_video_writer(output_path, width, height, fps, quality, **options)
        encoders.append(encoder)
        return encoder

    monkeypatch.setattr("video.ffmpeg_writer.create_video_writer", create)
    manager = JobManager()
    job_id = manager.create_job(config(tmp_path, automatic, video_enabled=True))
    manager.subscribe(job_id, lambda update: manager.cancel_job(job_id)
                      if update["stage"] == "video_render" and update["status"] == "running" else None)
    manager._run_job(job_id)
    assert manager.get_job(job_id)["status"] == "cancelled"
    assert len(encoders) == 1
    if hasattr(encoders[0], "pipe"):
        assert encoders[0].pipe.poll() is not None
    else:
        assert encoders[0].writer is None
    assert previous.read_bytes() == b"previous completed video"
    assert not (tmp_path / "trails.tiff").exists()
    assert not list(tmp_path.glob(".staraligner-*"))


def test_cancel_and_publication_have_one_order():
    token = CancellationToken()
    assert token.cancel()
    assert not token.cancel()
    published = []
    with pytest.raises(OperationCancelled):
        token.commit(lambda: published.append(True))
    assert not published
    finished = CancellationToken()
    finished.commit(lambda: published.append(True))
    assert not finished.cancel()
    assert not finished.cancelled


def test_cancel_interrupts_subprocess_finalization_without_ffmpeg_installation():
    from video.ffmpeg_writer import FFmpegPipe
    encoder = FFmpegPipe.__new__(FFmpegPipe)
    encoder.pipe = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                     stdin=subprocess.PIPE)
    token = CancellationToken()
    token.cancel()
    try:
        with pytest.raises(OperationCancelled):
            encoder.close(cancel_check=token.check)
        assert encoder.pipe.poll() is not None
    finally:
        encoder.abort()
