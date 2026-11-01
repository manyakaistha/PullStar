"""Noise recovery must preserve real centroids, flux, and native coordinates."""

import cv2
import numpy as np
import pytest
import rawpy
from scipy.spatial import cKDTree

from core.cancellation import CancellationToken, OperationCancelled
from modules.astronomy import match_sources
from modules.raw_recovery import (MeasuredField, extract_field, denoise_linear,
                                  detect_streak_sources, match_fields, sensor_plane)
from test_raw_processing import write_dark_dng


@pytest.mark.parametrize("orientation", [1, 3, 6, 8])
def test_rotated_raw_centroids_stay_in_full_view_pixel_coordinates(tmp_path, orientation):
    path = tmp_path / "rotated.dng"
    stars = write_dark_dng(path, orientation=orientation)
    shape, points = extract_field(path)
    x, y = stars.T
    truth = {1: stars, 3: np.column_stack([511-x, 383-y]),
             6: np.column_stack([383-y, x]), 8: np.column_stack([y, 511-x])}[orientation]
    assert shape == ((512, 384) if orientation in (6, 8) else (384, 512))
    distances, _ = cKDTree(points).query(truth)
    assert np.count_nonzero(distances < 1.2) >= 24


def test_sensor_sampling_preserves_signed_black_corrected_signal(tmp_path):
    path = tmp_path / "dark.dng"
    write_dark_dng(path)
    with rawpy.imread(str(path)) as raw:
        data = raw.raw_image_visible
        data[:8, :8] = 62
        plane = sensor_plane(raw)
    assert plane.shape == (192, 256)
    np.testing.assert_array_equal(plane[:4, :4], -2)


def streak_sky(seed=14):
    rng = np.random.default_rng(seed)
    shape = (384, 512)
    stars = rng.uniform((24, 24), (488, 360), (35, 2))
    image = rng.normal(5, 1.5, shape).astype(np.float32)
    yy, xx = np.indices(shape)
    for x, y in stars:
        # 25-second exposures need not look like round point sources.
        along = ((xx-x) + (yy-y)) / np.sqrt(2)
        across = ((xx-x) - (yy-y)) / np.sqrt(2)
        image += 65 * np.exp(-0.5 * ((along/3.5)**2 + (across/0.9)**2))
    return image, stars


def test_noisy_short_streaks_are_detected_and_registered_without_hot_pixels():
    image, truth = streak_sky()
    image[12, 12] = image[300, 20] = 5000
    moved = cv2.warpAffine(image, np.float32([[1, 0, 9], [0, 1, -6]]), (512, 384))
    source, target = detect_streak_sources(image), detect_streak_sources(moved)
    distances, _ = cKDTree(source).query(truth)
    assert np.count_nonzero(distances < 0.9) >= 28
    assert np.linalg.norm(source - (12, 12), axis=1).min() > 4
    match = match_sources(source, target)
    assert match is not None
    np.testing.assert_allclose(match.matrix[:2, 2], (9, -6), atol=0.15)


def test_phase_seed_still_requires_real_stellar_consensus():
    rng = np.random.default_rng(41)
    a = rng.normal(10, 2, (384, 512)).astype(np.float32)
    b = cv2.warpAffine(a, np.float32([[1, 0, 7], [0, 1, 4]]), (512, 384))
    # Identical noise textures correlate strongly, but unrelated centroids must
    # never be accepted as a stellar alignment.
    first = MeasuredField((768, 1024), rng.uniform(0, 768, (100, 2)), a)
    second = MeasuredField((768, 1024), rng.uniform(0, 768, (100, 2)), b)
    assert match_fields(first, second) is None


def test_denoising_reduces_sky_variance_and_retains_stellar_flux():
    rng = np.random.default_rng(12)
    yy, xx = np.indices((160, 160))
    star = 1000 * np.exp(-((xx-80)**2 + (yy-80)**2)/(2*2.0**2))
    image = np.stack([80 + star + rng.normal(0, 12, star.shape) for _ in range(3)], axis=2)
    before = image.astype(np.float32)
    original = before.copy()
    filtered = denoise_linear(before)
    assert filtered[:40].std() < before[:40].std() * 0.65
    aperture = (xx-80)**2 + (yy-80)**2 < 7**2
    flux = (filtered[:, :, 1] - 80)[aperture].sum()
    assert 0.90 < flux / star[aperture].sum() < 1.10
    np.testing.assert_array_equal(before, original)


def test_raw_detection_honors_cancellation():
    token = CancellationToken()
    token.cancel()
    with pytest.raises(OperationCancelled):
        detect_streak_sources(np.zeros((100, 100)), token.check)
