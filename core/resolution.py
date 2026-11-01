"""Resolution presets shared by the processing, API, and video layers."""

from __future__ import annotations

from typing import Tuple


RESOLUTION_LIMITS = {
    "source": None,
    "4k": 3840,
    "2k": 2560,
    "1080p": 1920,
    "720p": 1280,
}


def normalize_resolution(value: str | None) -> str:
    """Return a supported, lowercase resolution preset."""
    normalized = str(value or "source").strip().lower()
    if normalized not in RESOLUTION_LIMITS:
        choices = ", ".join(RESOLUTION_LIMITS)
        raise ValueError(f"Resolution must be one of: {choices}")
    return normalized


def fit_dimensions(width: int, height: int, resolution: str | None) -> Tuple[int, int]:
    """Fit dimensions to a preset's long-edge limit without upscaling.

    Video encoders commonly use 4:2:0 chroma, so both dimensions are rounded
    down to even values. The source aspect ratio is retained.
    """
    width, height = max(1, int(width)), max(1, int(height))
    limit = RESOLUTION_LIMITS[normalize_resolution(resolution)]
    if limit is None or max(width, height) <= limit:
        return width - width % 2, height - height % 2
    scale = limit / max(width, height)
    return (
        max(2, int(round(width * scale)) // 2 * 2),
        max(2, int(round(height * scale)) // 2 * 2),
    )


__all__ = ["RESOLUTION_LIMITS", "normalize_resolution", "fit_dimensions"]
