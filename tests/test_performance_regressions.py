"""Small regression tests for the allocation-reduced hot paths."""

import cv2
import numpy as np

from backend.api.images_router import preview_image
from backend.engine.render_backend import CPURenderer
from modules import io_utils
from modules.transform import CropRegion, TransformData, WarpWorkspace, warp_to_crop


def test_header_metadata_does_not_decode_pixels(tmp_path, monkeypatch):
    path = tmp_path / "frame.png"
    cv2.imwrite(str(path), np.zeros((23, 31, 3), np.uint16))

    def fail_decode(*args, **kwargs):
        raise AssertionError("header metadata unexpectedly decoded pixels")

    monkeypatch.setattr(io_utils.cv2, "imread", fail_decode)
    assert io_utils.get_image_info(path) == {
        "width": 31, "height": 23, "channels": 3,
        "dtype": "uint16", "is_raw": False,
    }


def test_preview_cache_reuses_encoded_bytes(tmp_path, monkeypatch):
    path = tmp_path / "frame.tiff"
    cv2.imwrite(str(path), np.full((24, 32, 3), 1024, np.uint16))
    original = io_utils.load_image
    calls = []

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(io_utils, "load_image", counted)
    first = preview_image(str(path), max_size=64)
    second = preview_image(str(path), max_size=64)
    assert first.body == second.body
    assert first.headers["etag"] == second.headers["etag"]
    assert len(calls) == 1


def test_cpu_crop_warp_preserves_full_frame_lanczos_grid():
    rng = np.random.default_rng(14)
    image = rng.uniform(0, 65535, (80, 96, 3)).astype(np.uint16)
    matrix = cv2.getRotationMatrix2D((-18, 27), -1.7, 1)
    matrix[:, 2] += (1.25, -0.75)
    crop = CropRegion(5, 89, 7, 73, 84, 66)
    expected = cv2.warpAffine(image.astype(np.float32), matrix, (96, 80),
                              flags=cv2.INTER_LANCZOS4)[7:73, 5:89]
    actual = CPURenderer((66, 84, 3)).align(image, matrix, crop)
    np.testing.assert_array_equal(actual, expected)


def test_integer_translation_uses_exact_crop_slice():
    rng = np.random.default_rng(22)
    image = rng.uniform(0, 65535, (80, 96, 3)).astype(np.float32)
    matrix = np.float64([[1, 0, 7], [0, 1, -4]])
    crop = CropRegion(12, 84, 9, 70, 72, 61)
    expected = cv2.warpAffine(image, matrix, (96, 80), flags=cv2.INTER_LANCZOS4)[9:70, 12:84]
    actual = warp_to_crop(image, matrix, crop, workspace=WarpWorkspace())
    np.testing.assert_array_equal(actual, expected)
