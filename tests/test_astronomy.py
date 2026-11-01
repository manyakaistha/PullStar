"""Deterministic synthetic skies exercise the real astronomy libraries."""
import unittest
from unittest.mock import patch

import cv2
import numpy as np
import astroalign
from scipy.spatial import cKDTree

from modules.astronomy import detect_sources, match_images, match_sources


def make_sky(seed=24, shape=(320, 420)):
    rng = np.random.default_rng(seed)
    stars = rng.uniform((35, 35), (shape[1] - 35, shape[0] - 35), (35, 2))
    yy, xx = np.indices(shape)
    image = rng.normal(20, 1.2, shape)
    for (x, y), peak in zip(stars, rng.uniform(60, 180, len(stars))):
        image += peak * np.exp(-((xx - x)**2 + (yy - y)**2) / (2 * 1.4**2))
    return image.astype(np.float32), stars


class AstronomyTests(unittest.TestCase):
    def test_bright_star_pool_recovers_after_noisy_triangle_search_fails(self):
        rng = np.random.default_rng(81)
        common = rng.uniform(400, 1700, (25, 2))
        source = np.vstack([common, rng.uniform(2000, 3000, (75, 2))])
        target = np.vstack([common + (15, -8), rng.uniform((2100, 0), (3000, 900), (75, 2))])
        find_transform = astroalign.find_transform

        def noisy_pool(*args, **kwargs):
            if kwargs["max_control_points"] == 100:
                raise astroalign.MaxIterError("No consensus in the noisy full pool")
            return find_transform(*args, **kwargs)

        with patch("modules.astronomy.astroalign.find_transform", side_effect=noisy_pool):
            result = match_sources(source, target)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(len(result.source), 20)
        # Confidence retains the full 100-candidate denominator on retries.
        self.assertLessEqual(result.confidence, 0.25)
        np.testing.assert_allclose(result.matrix[:2, 2], (15, -8), atol=0.01)

    def test_smaller_pool_does_not_weaken_the_required_consensus(self):
        rng = np.random.default_rng(29)
        common = rng.uniform(400, 1700, (8, 2))
        source = np.vstack([common, rng.uniform(2000, 3000, (92, 2))])
        target = np.vstack([common + (15, -8), rng.uniform((2100, 0), (3000, 900), (92, 2))])
        self.assertIsNone(match_sources(source, target))

    def test_centroids_and_hot_pixel_rejection_at_both_bit_depths(self):
        image, stars = make_sky()
        hot_pixels = [(12, 20), (390, 280), (250, 15)]
        for x, y in hot_pixels:
            image[y, x] = 255
        for dtype, factor in ((np.uint8, 1), (np.uint16, 240)):
            with self.subTest(dtype=dtype):
                points = detect_sources((image * factor).astype(dtype))
                distance, _ = cKDTree(stars).query(points)
                self.assertGreaterEqual(len(points), 28)
                self.assertTrue(np.all(distance < 0.5), distance)

    def test_offscreen_pole_and_large_motion_match_real_stars(self):
        image, _ = make_sky()
        expected = cv2.getRotationMatrix2D((-280, -150), 3.0, 1.0)
        moved = cv2.warpAffine(image, expected, (420, 320))
        result = match_images(image, moved)
        self.assertIsNotNone(result)
        np.testing.assert_allclose(result.matrix[:2], expected, atol=0.12)
        np.testing.assert_allclose(result.rotation_center, (-280, -150), atol=3)
        self.assertGreaterEqual(len(result.source), 20)

    def test_translation_succeeds_without_inventing_polaris(self):
        image, _ = make_sky()
        moved = cv2.warpAffine(image, np.float32([[1, 0, 16], [0, 1, -9]]), (420, 320))
        result = match_images(image, moved)
        self.assertIsNotNone(result)
        self.assertIsNone(result.rotation_center)
        np.testing.assert_allclose(result.matrix[:2, 2], (16, -9), atol=0.1)

    def test_blank_noise_unrelated_and_invalid_images_do_not_match(self):
        image, _ = make_sky()
        self.assertIsNone(match_images(image, np.zeros_like(image)))
        self.assertIsNone(match_images(image, make_sky(seed=123)[0]))
        self.assertEqual(len(detect_sources(np.full((50, 50), np.nan))), 0)
        self.assertEqual(len(detect_sources(np.zeros((50, 50), np.uint16))), 0)
        self.assertEqual(len(detect_sources(np.random.default_rng(8).normal(20, 1, (100, 100)))), 0)

    def test_faint_16_bit_stars_survive_saturated_foreground(self):
        image, stars = make_sky()
        image = (image * 0.25).astype(np.uint16)
        image[10, 10] = 65535
        image[280:310, 380:410] = 65535
        original = image.copy()
        points = detect_sources(image)
        errors, _ = cKDTree(stars).query(points)
        self.assertGreaterEqual(np.count_nonzero(errors < 0.5), 27)
        self.assertTrue(np.all(np.linalg.norm(points - (10, 10), axis=1) > 4))
        np.testing.assert_array_equal(image, original)

    def test_exposure_gain_does_not_change_matching_or_modify_images(self):
        image, _ = make_sky()
        expected = np.float32([[1, 0, 11], [0, 1, -6]])
        moved = cv2.warpAffine(image, expected, (420, 320))
        first = image * 0.0001
        second = moved * 0.003 + 0.2
        originals = first.copy(), second.copy()
        result = match_images(first, second)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(len(result.source), 25)
        np.testing.assert_allclose(result.matrix[:2], expected, atol=0.12)
        np.testing.assert_array_equal(first, originals[0])
        np.testing.assert_array_equal(second, originals[1])

    def test_local_noise_keeps_faint_stars_in_a_quiet_sky(self):
        image, stars = make_sky()
        image *= 0.003
        rng = np.random.default_rng(51)
        # The noisy bright region must not set a global threshold for the sky.
        image[:, 260:] = rng.normal(100, 4, image[:, 260:].shape)
        points = detect_sources(image)
        sky_stars = stars[stars[:, 0] < 230]
        distances, _ = cKDTree(points).query(sky_stars)
        self.assertGreaterEqual(np.count_nonzero(distances < 0.5), int(np.ceil(0.8 * len(sky_stars))))

    def test_twenty_precise_matches_allow_a_large_dim_candidate_pool(self):
        rng = np.random.default_rng(81)
        common = rng.uniform(400, 1700, (25, 2))
        source = np.vstack([common, rng.uniform(2000, 3000, (75, 2))])
        target = np.vstack([common + (15, -8), rng.uniform((2100, 0), (3000, 900), (75, 2))])
        result = match_sources(source, target)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(len(result.source), 20)
        np.testing.assert_allclose(result.matrix[:2, 2], (15, -8), atol=0.01)

    def test_downsampled_detection_returns_original_pixel_coordinates(self):
        rng = np.random.default_rng(94)
        image = rng.normal(8, 0.4, (1800, 2600)).astype(np.float32)
        stars = rng.uniform((40, 40), (2560, 1760), (30, 2))
        for x, y in stars:
            xi, yi = round(x), round(y)
            yy, xx = np.mgrid[yi-7:yi+8, xi-7:xi+8]
            image[yi-7:yi+8, xi-7:xi+8] += 30 * np.exp(-((xx-x)**2+(yy-y)**2)/(2*1.8**2))
        points = detect_sources(image)
        distances, _ = cKDTree(points).query(stars)
        self.assertGreaterEqual(np.count_nonzero(distances < 0.6), 28)
        self.assertEqual(len(detect_sources(image, max_stars=0)), 0)

    def test_integer_resize_preserves_faint_flux_like_the_float_copy(self):
        rng = np.random.default_rng(132)
        image = rng.normal(5, 0.4, (1800, 2600)).astype(np.float32)
        for x, y in rng.uniform((40, 40), (2560, 1760), (30, 2)):
            xi, yi = round(x), round(y)
            yy, xx = np.mgrid[yi-7:yi+8, xi-7:xi+8]
            image[yi-7:yi+8, xi-7:xi+8] += 3 * np.exp(-((xx-x)**2+(yy-y)**2)/(2*1.8**2))
        integer = image.astype(np.uint8)
        integer_points = detect_sources(integer)
        float_points = detect_sources(integer.astype(np.float32))
        self.assertGreaterEqual(len(integer_points), 20)
        np.testing.assert_allclose(integer_points, float_points, atol=1e-6)


if __name__ == "__main__":
    unittest.main()
