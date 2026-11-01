import cv2
import numpy as np

from backend.engine.alignment_engine import AlignmentEngine
from core.resolution import fit_dimensions
from video.ffmpeg_writer import create_video_writer


def test_resolution_presets_preserve_aspect_and_do_not_upscale():
    assert fit_dimensions(6000, 4000, "4k") == (3840, 2560)
    assert fit_dimensions(6000, 4000, "1080p") == (1920, 1280)
    assert fit_dimensions(1280, 720, "4k") == (1280, 720)


def test_image_resolution_downsamples_working_sequence(tmp_path):
    for index in range(10):
        frame = np.zeros((1024, 2048, 3), dtype=np.uint8)
        cv2.circle(frame, (800 + index, 400), 8, (255, 255, 255), -1)
        assert cv2.imwrite(str(tmp_path / f"frame_{index:02}.png"), frame)

    engine = AlignmentEngine(
        tmp_path,
        tmp_path / "stack.tiff",
        image_resolution="720p",
        video_resolution="720p",
        use_checkpoint=False,
    )
    try:
        info = engine.prepare()
        assert info["image_resolution"] == "720p"
        assert info["first_info"]["width"] == 1280
        assert info["first_info"]["height"] == 640
        assert engine.video_dimensions(1280, 640) == (1280, 640)
        assert engine.video_dimensions(4096, 3072) == (1280, 960)
    finally:
        engine.cleanup()


def test_video_writer_downscales_accumulator_to_requested_size(tmp_path):
    encoder = create_video_writer(tmp_path / "preview.mp4", 64, 48, 30, "medium")
    try:
        encoder.write_accumulator_snapshot(np.ones((96, 128, 3), dtype=np.float32))
    finally:
        encoder.close()

    video = cv2.VideoCapture(str(tmp_path / "preview.mp4"))
    try:
        assert video.isOpened()
        assert int(video.get(cv2.CAP_PROP_FRAME_WIDTH)) == 64
        assert int(video.get(cv2.CAP_PROP_FRAME_HEIGHT)) == 48
        assert int(video.get(cv2.CAP_PROP_FRAME_COUNT)) == 1
    finally:
        video.release()
