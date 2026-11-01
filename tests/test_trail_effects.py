import numpy as np
import pytest

from core.trail_effects import tail_opacity, validate_tail_settings, within_tail_angle
from synthesis.synthetic_generator import generate_ghost_frames


def test_tail_settings_are_normalized_and_bounded():
    assert validate_tail_settings("0.35", "24") == (0.35, 24.0)

    with pytest.raises(ValueError, match="between 0 and 1"):
        validate_tail_settings(-0.01, 20)
    with pytest.raises(ValueError, match="between 0 and 1"):
        validate_tail_settings(1.01, 20)
    with pytest.raises(ValueError, match="between 0 and 360"):
        validate_tail_settings(0.5, 361)


def test_tail_opacity_fades_linearly_and_angle_zero_disables_cutoff():
    assert tail_opacity(0, 30, 1) == 1.0
    assert tail_opacity(15, 30, 1) == 0.5
    assert tail_opacity(30, 30, 0.5) == 0.5
    assert tail_opacity(30, 0, 1) == 1.0
    assert within_tail_angle(12, 12)
    assert not within_tail_angle(12.01, 12)
    assert within_tail_angle(999, 0)


def test_ghost_generation_applies_cutoff_and_taper():
    # A uniform frame makes the brightness change independent of star geometry;
    # the rotation still exercises the same code path used by real trails.
    frame = np.full((128, 128, 3), 100, dtype=np.uint8)
    baseline = generate_ghost_frames(
        frame, 0, 30, (64, 64), num_ghosts=10, fade_factor=0,
        extension_factor=2,
    )
    tapered = generate_ghost_frames(
        frame, 0, 30, (64, 64), num_ghosts=10, fade_factor=0,
        extension_factor=2, tail_taper_strength=1, tail_angle_threshold=12,
    )

    # Ghost angles are 30/11, 2*30/11, ...; only the first four are <= 12°.
    assert len(baseline) == 10
    assert len(tapered) == 4
    assert max(image.max() for image in tapered) < max(image.max() for image in baseline)
    assert tapered[0].max() > tapered[-1].max()
