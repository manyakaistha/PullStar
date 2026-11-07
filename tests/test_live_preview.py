"""Live preview colour order regression test."""

import cv2
import numpy as np

from backend.engine.live_preview import write_live_preview


def test_live_preview_preserves_bgr_channel_order(tmp_path):
    # A blue night sky in the accumulator's OpenCV BGR order: blue channel brightest.
    accumulator = np.zeros((64, 64, 3), dtype=np.float32)
    accumulator[..., 0] = 200.0  # B
    accumulator[..., 1] = 120.0  # G
    accumulator[..., 2] = 40.0   # R
    path = tmp_path / "preview.jpg"

    assert write_live_preview(accumulator, path)

    preview = cv2.imread(str(path))  # BGR
    blue, green, red = (float(preview[..., c].mean()) for c in range(3))
    assert blue > green > red, f"expected a blue preview, got B={blue:.0f} G={green:.0f} R={red:.0f}"
