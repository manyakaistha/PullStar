"""Exercise dark CFA data through LibRaw, source detection, and 16-bit export."""

from pathlib import Path
from datetime import datetime, timedelta
import os

import cv2
import numpy as np
import pytest
import tifffile
from scipy.spatial import cKDTree

from modules.astronomy import detect_sources, match_sources
from modules.image_preview import load_raw_preview
from modules.io_utils import get_exif_datetime, get_image_list, load_image, reduce_chroma_noise
from backend.services.job_manager import JobManager


def write_dark_dng(path: Path, *, shift=(0, 0), captured=None, orientation=1):
    rng = np.random.default_rng(28)
    height, width = 384, 512
    stars = rng.uniform((30, 30), (width - 45, height - 45), (30, 2)) + shift
    yy, xx = np.indices((height, width))
    signal = np.full((height, width), 4.0)
    for x, y in stars:
        signal += 90 * np.exp(-((xx - x)**2 + (yy - y)**2) / (2 * 1.6**2))
    # A 10-bit phone sensor: almost all pixels are close to its 64-DN bias.
    sensor = np.round(64 + signal + rng.normal(0, 0.7, signal.shape)).astype(np.uint16)
    # A small bright foreground fixes the display exposure, as in the supplied
    # rooftop frames, so auto-brightening cannot stretch sensor noise to white.
    sensor[-12:] = 950
    identity = (1, 1, 0, 1, 0, 1, 0, 1, 1, 1, 0, 1, 0, 1, 0, 1, 1, 1)
    tags = [
        (271, "s", 0, "Test", False),
        (272, "s", 0, "Dark CFA", False),
        (274, "H", 1, orientation, False),
        (33421, "H", 2, (2, 2), False),
        (33422, "B", 4, (1, 2, 0, 1), False),
        (50706, "B", 4, (1, 4, 0, 0), False),
        (50707, "B", 4, (1, 1, 0, 0), False),
        (50708, "s", 0, "Dark CFA", False),
        (50713, "H", 2, (2, 2), False),
        (50714, "2I", 4, (64, 1) * 4, False),
        (50717, "I", 1, 1023, False),
        (50721, "2i", 9, identity, False),
        (50728, "2I", 3, (3, 5, 1, 1, 3, 5), False),
        (50778, "H", 1, 21, False),
    ]
    if captured:
        tags.append((306, "s", 0, captured, False))
    tifffile.imwrite(path, sensor, photometric=32803, metadata=None, extratags=tags)
    return stars


def test_tracking_preserves_camera_black_levels_in_a_dark_dng(tmp_path):
    path = tmp_path / "dark.dng"
    write_dark_dng(path)
    before = path.read_bytes()
    image = load_image(path)
    assert image.dtype == np.uint16
    # rawpy 0.26 overrides per-channel black with zero and clears the DNG's
    # repeating black table. A biased sky is then developed as bright magenta.
    assert np.median(image) < 1000
    assert image.max() > 5000
    assert path.read_bytes() == before


def test_preview_retains_dark_background_instead_of_bright_magenta(tmp_path):
    path = tmp_path / "dark.dng"
    write_dark_dng(path)
    image = load_raw_preview(path)
    assert image.dtype == np.uint8
    assert np.median(image) < 80
    assert image.max() > 200


def test_dark_dngs_match_real_source_centroids(tmp_path):
    points = []
    for index, shift in enumerate(((0, 0), (9, -6))):
        path = tmp_path / f"frame_{index}.dng"
        truth = write_dark_dng(path, shift=shift)
        detected = detect_sources(load_image(path))
        distances, _ = cKDTree(detected).query(truth)
        assert np.count_nonzero(distances < 0.8) >= 25
        points.append(detected)
    match = match_sources(*points)
    assert match is not None
    assert len(match.source) >= 25
    np.testing.assert_allclose(match.matrix[:2, 2], (9, -6), atol=0.2)


def test_dark_dng_can_be_developed_for_16_bit_export(tmp_path):
    path = tmp_path / "dark.dng"
    write_dark_dng(path)
    image = load_image(path, for_export=True)
    assert image.dtype == np.uint16
    assert image.shape == (384, 512, 3)
    assert np.median(image) < 8000
    assert image.max() > 10000


def test_dng_capture_times_survive_copying_and_archive_extraction(tmp_path):
    earlier, later = tmp_path / "Z.dng", tmp_path / "A.dng"
    write_dark_dng(earlier, captured="2026:10:02 22:32:11")
    write_dark_dng(later, captured="2026:10:02 22:32:41")
    os.utime(earlier, (2000000000, 2000000000))
    os.utime(later, (1000000000, 1000000000))
    assert get_exif_datetime(earlier) == datetime(2026, 10, 2, 22, 32, 11)
    assert get_image_list(tmp_path) == [earlier, later]
    assert get_image_list(tmp_path, sort_by_time=False) == [later, earlier]


def test_cfa_dng_job_detects_aligns_and_exports_without_polaris(tmp_path):
    for index in range(12):
        timestamp = datetime(2026, 10, 2, 22, 32, 11) + timedelta(seconds=30 * index)
        write_dark_dng(tmp_path / f"frame_{index:02}.dng", shift=(index * 0.8, -index * 0.4),
                       captured=timestamp.strftime("%Y:%m:%d %H:%M:%S"))
    manager = JobManager()
    job_id = manager.create_job({
        "input_dir": str(tmp_path), "output_file": str(tmp_path / "trails.tiff"),
        "extension_factor": 1.5, "ghost_frames_per_real": 2,
        "use_foreground_mask": False, "use_checkpoint": False, "compute_backend": "cpu",
    })
    manager._run_job(job_id)
    job = manager.get_job(job_id)
    assert job["status"] == "completed", job.get("error")
    image = cv2.imread(job["result_path"], cv2.IMREAD_UNCHANGED)
    assert image.dtype == np.uint16
    assert min(image.shape[:2]) > 350
    assert np.count_nonzero(image[:, :, 0] > 8000) > 100
    assert not list(tmp_path.glob(".staraligner-*"))


@pytest.mark.parametrize("dtype,maximum", [(np.uint8, 255), (np.uint16, 65535)])
def test_chroma_reduction_supports_both_depths_without_losing_star_luminance(dtype, maximum):
    image = np.full((32, 32, 3), maximum // 20, dtype=dtype)
    image[14:17, 14:17] = maximum * 3 // 4
    original = image.copy()
    filtered = reduce_chroma_noise(image)
    assert filtered.dtype == dtype
    assert filtered[15, 15].mean() > maximum * 0.7
    assert np.abs(filtered.astype(float) - image).max() < max(3, maximum * 0.004)
    np.testing.assert_array_equal(image, original)
