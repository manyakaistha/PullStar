"""Exercise real image/video exports, publication, and cancellation."""
import json
from pathlib import Path
from unittest.mock import patch
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.engine.alignment_engine import AlignmentEngine
from backend.services.job_manager import JobManager
from modules.export_images import save_export_image
from test_cancellation import sources, config


@pytest.mark.parametrize("format", ["tiff", "png", "jpg"])
@pytest.mark.parametrize("automatic", [False, True])
def test_images_only_skips_all_stacking(tmp_path, format, automatic):
    sources(tmp_path, automatic)
    output = tmp_path / "exported"
    manager = JobManager()
    job = manager.create_job(config(tmp_path, automatic, output_file=str(output),
                                    no_stack=True, save_frames=True, image_format=format))
    with patch.object(AlignmentEngine, "_render_pass2", side_effect=AssertionError("Must not stack")):
        manager._run_job(job)
    result = manager.get_job(job)
    assert result["status"] == "completed", result["error"]
    manifest = json.loads((output / "sequence.json").read_text())
    assert len(manifest["files"]) == result["frame_count"] >= 10
    for name in manifest["files"]:
        pixels = cv2.imread(str(output / name), cv2.IMREAD_UNCHANGED)
        assert pixels.shape[:2] == (manifest["crop"]["height"], manifest["crop"]["width"])
    assert Path(result["preview_path"]).is_file()
    assert not list(tmp_path.glob("*.tiff"))
    assert not list(tmp_path.glob(".staraligner-*"))
    response = TestClient(app).get("/api/images/download-sequence", params={"path": str(output)})
    assert response.status_code == 200 and response.content[:2] == b"PK"
    assert not list(tmp_path.glob("*.zip"))


@pytest.mark.parametrize("format,dtype", [("tiff", np.uint16), ("png", np.uint16), ("jpg", np.uint8)])
def test_fixed_brightness_and_bit_depth(tmp_path, format, dtype):
    image = np.full((16, 16, 3), 10000, np.uint16)
    for index, peak in enumerate([20000, 50000]):
        image[0, 0] = peak
        path = tmp_path / f"image{index}.{format}"
        save_export_image(image, path, format, "uint16")
        decoded = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        assert decoded.dtype == dtype
        expected = 10000 if dtype == np.uint16 else 10000 / 257
        assert abs(float(decoded[-1, -1, 0]) - expected) < 2


def test_cancel_image_export_publishes_nothing(tmp_path):
    sources(tmp_path)
    manager = JobManager()
    output = tmp_path / "exported"
    job = manager.create_job(config(tmp_path, output_file=str(output), no_stack=True, save_frames=True))
    manager.subscribe(job, lambda state: manager.cancel_job(job)
                      if state.get("activity") == "exporting_frames" and state.get("current", 0) >= 2 else None)
    manager._run_job(job)
    assert manager.get_job(job)["status"] == "cancelled"
    assert not output.exists()
    assert not list(tmp_path.glob(".staraligner-*"))


@pytest.mark.parametrize("automatic", [False, True])
def test_stack_and_frames_and_mov_export(tmp_path, automatic):
    from video.ffmpeg_writer import is_ffmpeg_available
    if not is_ffmpeg_available():
        pytest.skip("FFmpeg required for MOV")
    sources(tmp_path, automatic)
    manager = JobManager()
    job = manager.create_job(config(tmp_path, automatic, image_format="png", save_frames=True,
                                    video_enabled=True, video_format="mov"))
    manager._run_job(job)
    result = manager.get_job(job)
    assert result["status"] == "completed", result["error"]
    assert Path(result["result_path"]).suffix == ".png"
    assert cv2.imread(result["result_path"]) is not None
    assert Path(result["frames_dir"]).is_dir()
    video = cv2.VideoCapture(result["video_path"])
    assert video.isOpened() and video.read()[0]
    video.release()
    assert TestClient(app).get("/api/images/download", params={"path": result["video_path"]}).status_code == 200


def test_existing_sequence_is_preserved(tmp_path):
    sources(tmp_path)
    output = tmp_path / "exported"
    output.mkdir()
    (output / "keep.txt").write_text("existing work")
    manager = JobManager()
    job = manager.create_job(config(tmp_path, output_file=str(output), no_stack=True, save_frames=True))
    manager._run_job(job)
    assert manager.get_job(job)["status"] == "failed"
    assert (output / "keep.txt").read_text() == "existing work"


@pytest.mark.parametrize("options", [
    {"no_stack": True}, {"no_stack": True, "save_frames": True, "video_enabled": True},
    {"video_enabled": True, "quality": "prores", "video_format": "mp4"},
    {"image_format": "raw"}, {"video_fps": 0},
])
def test_invalid_exports_rejected_before_start(tmp_path, options):
    response = TestClient(app).post("/api/jobs", json={"input_dir": str(tmp_path), **options})
    assert response.status_code == 422


def test_three_exposures_can_be_exported_without_trails(tmp_path):
    sources(tmp_path)
    for path in sorted(tmp_path.glob("*.png"))[3:]:
        path.unlink()
    manager = JobManager()
    job = manager.create_job(config(tmp_path, output_file=str(tmp_path / "three"), no_stack=True, save_frames=True))
    manager._run_job(job)
    assert manager.get_job(job)["status"] == "completed"
    assert manager.get_job(job)["frame_count"] == 3


def test_encoder_failure_is_reported(monkeypatch, tmp_path):
    from video.ffmpeg_writer import FFmpegPipe
    class Process:
        returncode = 1
        def wait(self, **kwargs): return 1
        class Input:
            closed = False
            def close(self): self.closed = True
        stdin = Input()
    monkeypatch.setattr("video.ffmpeg_writer.subprocess.Popen", lambda *args, **kwargs: Process())
    writer = FFmpegPipe(tmp_path / "broken.mp4", 32, 32)
    with pytest.raises(RuntimeError, match="Video encoding failed"):
        writer.close()
