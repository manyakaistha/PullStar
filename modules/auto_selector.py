"""Automatic stellar selection using Photutils and Astroalign, fully offline."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

from modules.astronomy import match_images, detect_sources, match_sources
from modules.io_utils import load_image
from core.cancellation import check_cancelled
from core.parallel import ordered_map
from contextlib import closing


@dataclass
class AutoSelectionResult:
    # Retain the old response key, but never label a fitted centre as Polaris.
    polaris: Optional[Tuple[float, float]]
    second_star: Optional[Tuple[float, float]]
    confidence: float
    num_inliers: int
    rotation_angle: float
    reference_stars: List[Tuple[float, float]] = field(default_factory=list)
    rotation_center: Optional[Tuple[float, float]] = None
    method: str = "photutils-astroalign"
    selection_mode: str = "star_field"


def find_rotation_center(img_first: np.ndarray, img_second: np.ndarray,
                         max_features: int = 500, quality_level: float = 0.01,
                         min_distance: int = 10, cancel_check=None) -> Optional[AutoSelectionResult]:
    """Compatibility entry point: match stars; the centre may be off-image.

    Legacy corner-detector tuning arguments are retained for existing callers.
    ``polaris`` is null because detecting a field does not identify a named star.
    """
    match = match_images(img_first, img_second, cancel_check=cancel_check)
    return _selection_result(match)


def _selection_result(match):
    if match is None:
        return None
    stars = [tuple(float(v) for v in point) for point in match.source]
    primary = np.asarray(stars[0])
    second = stars[int(np.argmax(np.linalg.norm(match.source - primary, axis=1)))]
    return AutoSelectionResult(None, second, match.confidence, len(stars),
                               match.rotation_angle, stars, match.rotation_center)


def auto_detect_stars(image_paths: List[Path], frame_step: int = 10,
                      cancel_check=None, workers=1,
                      raw_noise_reduction=True) -> Optional[AutoSelectionResult]:
    """Match the first frame to a later exposure using the common RAW loader.

    Retry a closer exposure when the requested comparison is cloudy or has too
    little overlap. Star positions always refer to the first input frame.
    """
    check_cancelled(cancel_check)
    if len(image_paths) < 2:
        return None
    if frame_step is None or frame_step < 1:
        raise ValueError("frame_step must be a positive integer")
    indices = dict.fromkeys([min(frame_step, len(image_paths) - 1), 1,
                             min(3, len(image_paths) - 1)])
    def extract(index):
        check_cancelled(cancel_check)
        try:
            from modules.raw_recovery import measure_field
            return measure_field(image_paths[index], recovery=raw_noise_reduction,
                                 cancel_check=cancel_check)
        except (OSError, ValueError):
            if index == 0:
                raise
            return None

    with closing(ordered_map(extract, [0, *indices], workers=workers,
                              cancel_check=cancel_check)) as frames:
        from modules.raw_recovery import match_fields
        first = next(frames)
        for data in frames:
            check_cancelled(cancel_check)
            if data is None or data.shape != first.shape:
                continue
            result = _selection_result(match_fields(first, data, cancel_check=cancel_check))
            if result is not None:
                return result
    return None


def preview_auto_detection(
    image: np.ndarray,
    result: AutoSelectionResult,
    window_name: str = "Auto-Detected Stars (Enter=Accept, Click=Override)"
) -> Tuple[Tuple[float, float], Optional[Tuple[float, float]], bool]:
    """
    Show preview of auto-detected stars and allow user to override.

    Args:
        image: Image to display
        result: AutoSelectionResult from auto detection
        window_name: Window title

    Returns:
        (polaris, second_star, accepted) where accepted=True if user pressed Enter
    """
    display = image.copy()

    # Ensure 8-bit for display
    if display.dtype != np.uint8:
        display = (display / display.max() * 255).astype(np.uint8)

    # Draw detected Polaris (green circle)
    primary = result.reference_stars[0]
    px, py = int(primary[0]), int(primary[1])
    cv2.circle(display, (px, py), 30, (0, 255, 0), 3)
    cv2.circle(display, (px, py), 5, (0, 255, 0), -1)
    cv2.putText(display, "MATCHED STAR", (px + 35, py - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    # Draw second star (blue circle)
    if result.second_star:
        sx, sy = int(result.second_star[0]), int(result.second_star[1])
        cv2.circle(display, (sx, sy), 25, (255, 100, 0), 3)
        cv2.circle(display, (sx, sy), 5, (255, 100, 0), -1)
        cv2.putText(display, "REF STAR", (sx + 30, sy - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 100, 0), 2)

    # Add info text
    info = f"Confidence: {result.confidence:.1%} | Rotation: {result.rotation_angle:.4f} deg"
    cv2.putText(display, info, (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    cv2.putText(display, "Press ENTER to accept | ESC to cancel", (20, 60),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)

    # State for mouse overrides
    overrides = {'polaris': None, 'second': None, 'mode': 'polaris'}

    def mouse_callback(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            if overrides['mode'] == 'polaris':
                overrides['polaris'] = (x, y)
                overrides['mode'] = 'second'
            else:
                overrides['second'] = (x, y)

    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(window_name, mouse_callback)
    cv2.imshow(window_name, display)

    while True:
        key = cv2.waitKey(100) & 0xFF

        if key == 13:  # Enter
            cv2.destroyWindow(window_name)
            final_polaris = overrides['polaris'] or primary
            final_second = overrides['second'] or result.second_star
            return (final_polaris, final_second, True)

        elif key == 27:  # ESC
            cv2.destroyWindow(window_name)
            return (primary, result.second_star, False)

        # Redraw if there are overrides
        if overrides['polaris'] or overrides['second']:
            display = image.copy()
            if display.dtype != np.uint8:
                display = (display / display.max() * 255).astype(np.uint8)

            # Draw original (dimmed)
            cv2.circle(display, (px, py), 30, (0, 100, 0), 1)

            # Draw overrides
            if overrides['polaris']:
                ox, oy = int(overrides['polaris'][0]), int(overrides['polaris'][1])
                cv2.circle(display, (ox, oy), 30, (0, 255, 0), 3)
                cv2.circle(display, (ox, oy), 5, (0, 255, 0), -1)

            if overrides['second']:
                ox, oy = int(overrides['second'][0]), int(overrides['second'][1])
                cv2.circle(display, (ox, oy), 25, (255, 100, 0), 3)
                cv2.circle(display, (ox, oy), 5, (255, 100, 0), -1)

            cv2.imshow(window_name, display)

    cv2.destroyWindow(window_name)
    return (primary, result.second_star, False)
