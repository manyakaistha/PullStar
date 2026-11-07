"""Small, atomic display previews for the in-progress accumulator."""

from pathlib import Path

import cv2
import numpy as np


def write_live_preview(source, path: Path) -> bool:
    """Encode a display-only JPEG without changing the scientific output."""
    try:
        pixels = np.asarray(source.snapshot() if hasattr(source, "snapshot") else source)
        pixels = np.nan_to_num(pixels, nan=0.0, posinf=0.0, neginf=0.0)
        if pixels.size == 0 or float(pixels.max()) <= 0:
            return False
        # Percentiles over a full 50 MP accumulator create a large temporary
        # positive-pixel array on every refresh. A small area-preserving sample
        # is sufficient for display tone mapping and keeps preview generation
        # out of the stacking hot path.
        sample = pixels
        preview_sample_size = 512
        if max(sample.shape[:2]) > preview_sample_size:
            ratio = preview_sample_size / max(sample.shape[:2])
            sample = cv2.resize(
                sample,
                (max(1, round(sample.shape[1] * ratio)),
                 max(1, round(sample.shape[0] * ratio))),
                interpolation=cv2.INTER_AREA,
            )
        positive = sample[sample > 0]
        scale = float(np.percentile(positive, 99.7)) if positive.size else 0.0
        if not np.isfinite(scale) or scale <= 0:
            scale = float(pixels.max())
        display = np.clip(pixels / scale * 255.0, 0, 255).astype(np.uint8)
        max_size = 2048
        if max(display.shape[:2]) > max_size:
            ratio = max_size / max(display.shape[:2])
            display = cv2.resize(
                display,
                (max(1, round(display.shape[1] * ratio)), max(1, round(display.shape[0] * ratio))),
                interpolation=cv2.INTER_AREA,
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.stem}.tmp{path.suffix}")
        # The accumulator is already in OpenCV BGR order (frames are loaded with
        # cv2.imread / converted RGB->BGR in modules.io_utils), which is what
        # cv2.imwrite expects. Converting again would swap red and blue.
        if not cv2.imwrite(str(temporary), display, [cv2.IMWRITE_JPEG_QUALITY, 88]):
            return False
        temporary.replace(path)
        return True
    except (OSError, ValueError, cv2.error):
        return False
