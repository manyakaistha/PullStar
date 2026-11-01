"""Shared controls for synthetic trail tails.

The renderer keeps real exposures at full strength and applies these controls
only to synthetic frames.  That makes a tapered extension predictable: the
observed sky remains unchanged while the generated tail fades or stops at a
chosen angular distance.
"""

from __future__ import annotations


def validate_tail_settings(taper_strength: float, angle_threshold: float) -> tuple[float, float]:
    """Validate and normalize tail controls used by all render paths.

    ``angle_threshold == 0`` disables the cutoff.  A taper strength of zero
    preserves the previous uniform synthetic-frame brightness; one fades the
    synthetic tail to black at its end.
    """
    taper = float(taper_strength)
    threshold = float(angle_threshold)
    if not 0.0 <= taper <= 1.0:
        raise ValueError("Tail taper strength must be between 0 and 1")
    if not 0.0 <= threshold <= 360.0:
        raise ValueError("Tail angle threshold must be between 0 and 360 degrees")
    return taper, threshold


def within_tail_angle(angle_degrees: float, threshold_degrees: float) -> bool:
    """Return whether a synthetic state is inside the optional angle cutoff."""
    return threshold_degrees <= 0.0 or abs(float(angle_degrees)) <= threshold_degrees + 1e-9


def tail_opacity(angle_degrees: float, span_degrees: float, taper_strength: float) -> float:
    """Return the opacity multiplier for a synthetic state.

    ``span_degrees`` is the angular distance represented by the complete
    synthetic tail (usually the configured cutoff, or the generated extension
    span when no cutoff is configured).  Opacity is one at the real-tail edge
    and reaches ``1 - taper_strength`` at the far edge.
    """
    if taper_strength <= 0.0 or span_degrees <= 1e-9:
        return 1.0
    progress = min(1.0, max(0.0, abs(float(angle_degrees)) / float(span_degrees)))
    return max(0.0, 1.0 - float(taper_strength) * progress)


__all__ = ["tail_opacity", "validate_tail_settings", "within_tail_angle"]
