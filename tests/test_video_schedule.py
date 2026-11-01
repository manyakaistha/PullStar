from core.video_schedule import video_step_repeats


def test_fast_slow_motion_repeats_real_exposures_without_synthetic_states():
    schedule = [(index, float(index), False) for index in range(3)]

    assert video_step_repeats(schedule, slowdown=1) == {1: 1, 2: 1, 3: 1}
    assert video_step_repeats(schedule, slowdown=4) == {1: 4, 2: 4, 3: 4}


def test_synthetic_schedule_samples_evenly_and_preserves_stack_states():
    schedule = [
        (0, 0.0, False),
        (0, 0.5, True),
        (1, 1.0, False),
        (1, 1.5, True),
        (2, 2.0, False),
    ]

    # Slowdown controls encoded snapshots, while all synthetic states remain
    # available to the stack renderer.
    assert video_step_repeats(schedule, slowdown=1) == {1: 1, 3: 1, 5: 1}
    assert video_step_repeats(schedule, slowdown=4) == {1: 1, 2: 1, 3: 1, 4: 1, 5: 1}


def test_hyperlapse_selects_only_real_exposures():
    schedule = [
        (0, 0.0, False),
        (0, 0.5, True),
        (1, 1.0, False),
        (1, 1.5, True),
    ]

    assert video_step_repeats(schedule, slowdown=8, hyperlapse=True) == {1: 1, 3: 1}
