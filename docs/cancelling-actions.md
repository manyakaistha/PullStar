# Cancelling an action

While an action is running, its original button becomes a cancel control:

- **Detect references → Cancel detection** in the image workspace.
- **Start alignment → Cancel alignment**, then **Cancel trail creation** while stacking or extending trails.
- **Cancel video render** while finalizing an enabled video.

Press it once. The button shows **Cancelling…** until the server confirms the worker has stopped, then restores its original action. Cancellation is reported separately from failure. You can restart the action after it stops.

Cancellation also works while a job is being created: the client waits for its server ID and then stops that worker. Changing the source folder disposes and cancels its old detection action, so late detection results cannot replace the new folder's references. A failed cancellation request leaves Cancel available to retry. Losing a status connection does not claim the worker stopped.

Workers check cancellation while scanning, validating, detecting sources, tracking exposures, and generating real or synthetic trail frames. An individual native image decode, warp, or astronomy-library call finishes before the next cancellation check. FFmpeg finalization checks while waiting and terminates its subprocess when cancelled; OpenCV video encoders are released.

Final TIFF/video exports are staged in a temporary directory next to the requested output. A cancelled run removes those temporary files and preserves any previous completed export. Cancellation that arrives after final publication cannot undo a completed action. Recovery checkpoints and any individually exported aligned frames already written remain available.

The desktop uses `POST /api/stars/detect/start` for cancellable detection and `POST /api/jobs` for alignment. Both return a job ID. `POST /api/jobs/{id}/cancel` requests stopping; `GET /api/jobs/{id}` reports `cancelling` followed by `cancelled`. Cancellation of an already terminal job is idempotent. The original synchronous `/api/stars/detect` API remains available for existing callers.

Run cancellation regressions with `uv run --group dev pytest -q tests/test_cancellation.py`, and the client lifecycle tests with `cd frontend && npm test`.

The controls were checked in the studio with 24 supplied photographs: cancelling detection, alignment, and GPU trail creation restored their original buttons, and subsequent detection and GPU alignment completed. The native browser request context is covered by a regression test. See [hardware processing](hardware-processing.md) for parallel-worker and GPU cancellation checks.
