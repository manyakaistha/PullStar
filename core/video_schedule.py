"""Helpers for sampling stack states into a controllable trail-lapse video."""


def evenly_spaced(items, count):
    """Return up to ``count`` items, retaining the first and last states."""
    items = tuple(items)
    count = max(0, int(count))
    if not items or count == 0:
        return ()
    if count >= len(items):
        return items
    if count == 1:
        return (items[-1],)
    positions = {
        round(index * (len(items) - 1) / (count - 1))
        for index in range(count)
    }
    return tuple(items[index] for index in sorted(positions))


def video_step_repeats(schedule, slowdown=1, hyperlapse=False):
    """Map scheduled render steps to the number of video snapshots to write.

    ``slowdown`` is the approximate number of snapshots per real exposure
    interval. Synthetic stack frames remain available for the final TIFF, but
    only an evenly spaced subset is sent to the encoder. This prevents the
    encoder and GPU readbacks from multiplying with ``ghost_frames_per_real``.
    """
    schedule = tuple(schedule)
    slowdown = max(1, int(slowdown))
    real_positions = [index for index, item in enumerate(schedule) if not item[2]]
    if not real_positions:
        return {}
    if hyperlapse:
        return {position + 1: 1 for position in real_positions}

    has_synthetic = any(item[2] for item in schedule)
    if not has_synthetic:
        return {position + 1: slowdown for position in real_positions}

    selected = {}
    for real_index, position in enumerate(real_positions):
        selected[position + 1] = 1
        end = (real_positions[real_index + 1]
               if real_index + 1 < len(real_positions) else len(schedule))
        synthetic_positions = [step for step in range(position + 1, end)
                               if schedule[step][2]]
        if not synthetic_positions:
            continue
        if real_index + 1 < len(real_positions):
            target = slowdown - 1
        else:
            # The final group represents synthetic future extension. Give it
            # one sampled state per real interval at the selected pace.
            target = slowdown * max(1, len(real_positions) - 1)
        for step in evenly_spaced(synthetic_positions, target):
            selected[step + 1] = 1
    return selected


__all__ = ["evenly_spaced", "video_step_repeats"]
