"""Match an entire stellar field and remove wobble while retaining star trails.

Without plate solving, pointing metadata, or a fixed ground reference, smooth
camera motion is indistinguishable from smooth sky motion. We therefore retain
the robust constant-speed field trajectory, correcting its framewise residuals.
No coordinate in this module is assumed to be Polaris.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
import math
import hashlib
import json
import time as time_module

import cv2
import numpy as np
from scipy.optimize import least_squares

from modules.astronomy import MIN_MATCHES, detect_sources, match_sources
from modules.io_utils import get_timestamps_for_files, load_image, save_tiff
from modules.transform import CropRegion, TransformData
from core.cancellation import check_cancelled
from core.parallel import ordered_map
from core.compute import adaptive_checkpoint_interval
from core.video_schedule import video_step_repeats
from core.trail_effects import tail_opacity, within_tail_angle
from backend.engine.render_backend import create_renderer
from backend.engine.live_preview import write_live_preview


@dataclass
class FieldFrame:
    frame_index: int
    num_matches: int
    confidence: float
    is_valid: bool


@dataclass
class FieldAnalysis:
    frames: list[FieldFrame]
    transforms: list[TransformData]
    times: np.ndarray  # elapsed median exposure intervals
    angle_coefficients: np.ndarray
    translation_coefficients: np.ndarray
    time_span: float
    curved: bool
    reference_stars: np.ndarray

    def motion_at(self, time: float) -> np.ndarray:
        t = time / self.time_span
        angle = self.angle_coefficients @ [1, t]
        basis = _translation_basis(np.asarray([t]), self.angle_coefficients[1], self.curved)[0]
        matrix = np.eye(3)
        matrix[:2, :2] = [[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]]
        matrix[:2, 2] = basis @ self.translation_coefficients
        return matrix

    @property
    def skipped_frames(self) -> list[int]:
        return [f.frame_index for f in self.frames if not f.is_valid]


def _translation_basis(times, angular_speed, curved):
    if not curved:
        return np.column_stack([np.ones_like(times), times])
    # Normalized circular basis remains well-conditioned for small arcs.
    return np.column_stack([np.ones_like(times),
                            np.sin(angular_speed * times) / angular_speed,
                            (1 - np.cos(angular_speed * times)) / angular_speed**2])


def _robust_fit(design, values, noise=2.0):
    initial = np.linalg.lstsq(design, values, rcond=None)[0]
    return least_squares(lambda c: design @ c - values, initial,
                         loss="soft_l1", f_scale=noise).x


def sequence_times(paths: list[Path], cancel_check=None) -> np.ndarray:
    timestamps = get_timestamps_for_files(paths, cancel_check=cancel_check)
    intervals = np.array([(b - a).total_seconds() for a, b in zip(timestamps, timestamps[1:])])
    # Copied/generated files often only have almost identical filesystem mtimes.
    # They are not useful exposure times; fall back to uniform frame spacing.
    if len(intervals) and np.all(intervals > 0) and np.median(intervals) >= 1:
        return np.r_[0, np.cumsum(intervals)] / np.median(intervals)
    return np.arange(len(paths), dtype=float)


def iter_field_sources(paths, workers=1, cancel_check=None, raw_noise_reduction=True,
                        measurements=False):
    """Extract independent fields in parallel, yielding original exposure order."""
    def extract(path):
        check_cancelled(cancel_check)
        from modules.raw_recovery import measure_field
        result = measure_field(path, recovery=raw_noise_reduction, cancel_check=cancel_check)
        return result if measurements else (result.shape, result.points)

    yield from ordered_map(extract, paths, workers=workers, cancel_check=cancel_check)


def analyze_field(paths: list[Path], progress_callback: Optional[Callable] = None,
                   cancel_check=None, workers=1, raw_noise_reduction=True) -> FieldAnalysis:
    """Find six or more matching stars per exposure; skip untrustworthy frames."""
    if len(paths) < 3:
        raise ValueError("Automatic trail alignment needs at least three exposures.")
    frames, observations = [], []
    reference = previous = None
    previous_matrix = np.eye(3)
    reference_stars = np.empty((0, 2))
    shape = None

    from modules.raw_recovery import match_fields
    for index, field in enumerate(iter_field_sources(
            paths, workers, cancel_check, raw_noise_reduction, measurements=True)):
        frame_shape, points = field.shape, field.points
        path = paths[index]
        if shape is not None and frame_shape != shape:
            raise ValueError(f"Frame dimensions differ: {path.name}")
        shape = frame_shape
        matrix, count, confidence = None, 0, 0.0
        if reference is None and len(points) >= MIN_MATCHES:
            reference = previous = field
            reference_stars = points
            matrix, count, confidence = np.eye(3), len(points), 1.0
        elif reference is not None:
            # Nearby RAW exposures minimize PSF/projection changes; periodically
            # try the original field to bound accumulated registration drift.
            recent_first = field.registration is not None and index % 20 != 0
            anchor = previous if recent_first else reference
            match = match_fields(anchor, field, cancel_check=cancel_check)
            if match is not None:
                matrix = match.matrix @ previous_matrix if recent_first else match.matrix
            elif previous is not None:
                # Reacquire after a long sequence moves beyond the first field.
                fallback = reference if recent_first else previous
                match = match_fields(fallback, field, cancel_check=cancel_check)
                if match is not None:
                    matrix = match.matrix if recent_first else match.matrix @ previous_matrix
            if match is not None:
                count, confidence = len(match.source), match.confidence
        valid = matrix is not None
        if valid:
            previous, previous_matrix = field, matrix
        observations.append(matrix)
        frames.append(FieldFrame(index, count, confidence, valid))
        if progress_callback:
            progress_callback(index + 1, len(paths))
    valid_indices = np.array([f.frame_index for f in frames if f.is_valid])
    if len(valid_indices) < max(3, math.ceil(len(paths) / 2)):
        raise ValueError("Not enough reliable star matches. At least six visible stars must "
                         "match in half the exposures; check focus, clouds, and sequence overlap.")
    check_cancelled(cancel_check)
    times = sequence_times(paths, cancel_check=cancel_check)
    span = max(float(times[-1]), 1.0)
    t = times[valid_indices] / span
    observed = np.array([observations[i] for i in valid_indices])
    angles = np.unwrap(np.arctan2(observed[:, 1, 0], observed[:, 0, 0]))
    angle_coefficients = _robust_fit(np.column_stack([np.ones_like(t), t]), angles, noise=0.002)
    curved = abs(angle_coefficients[1]) >= np.radians(0.1) and len(t) >= 6
    basis = _translation_basis(t, angle_coefficients[1], curved)
    translations = np.column_stack([_robust_fit(basis, observed[:, axis, 2]) for axis in (0, 1)])
    analysis = FieldAnalysis(frames, [], times, angle_coefficients, translations,
                             span, curved, reference_stars)
    for index, observed_matrix in enumerate(observations):
        check_cancelled(cancel_check)
        # Full stellar registration would erase all trails. Only remove the
        # difference between observed motion and its smooth sky trajectory.
        correction = (analysis.motion_at(times[index]) @ np.linalg.inv(observed_matrix)
                      if observed_matrix is not None else np.eye(3))
        analysis.transforms.append(TransformData(
            index, float(correction[0, 2]), float(correction[1, 2]),
            float(np.arctan2(correction[1, 0], correction[0, 0])),
            correction[:2], observed_matrix is not None))
    return analysis


def field_crop(transforms: list[TransformData], width: int, height: int) -> CropRegion:
    """Conservatively crop transformed footprints, including camera roll."""
    left = top = 0.0
    right, bottom = float(width), float(height)
    for transform in transforms:
        if not transform.is_valid:
            continue
        matrix = transform.matrix
        # Bound the displacement of every corner. These maximum axis margins
        # ensure that the remaining rectangle is inside every rotated image.
        corners = np.array([[0, 0], [width, 0], [width, height], [0, height]], dtype=float)
        displacement = corners @ matrix[:, :2].T + matrix[:, 2] - corners
        left = max(left, float(displacement[:, 0].max()))
        top = max(top, float(displacement[:, 1].max()))
        right = min(right, width + float(displacement[:, 0].min()))
        bottom = min(bottom, height + float(displacement[:, 1].min()))
    x0, y0 = math.ceil(left) + 2, math.ceil(top) + 2
    x1, y1 = math.floor(right) - 2, math.floor(bottom) - 2
    # Video encoders using 4:2:0 chroma need even dimensions.
    x1 -= (x1 - x0) % 2
    y1 -= (y1 - y0) % 2
    if x1 <= x0 or y1 <= y0:
        raise ValueError("Camera movement leaves no common image area to stack.")
    return CropRegion(x0, x1, y0, y1, x1 - x0, y1 - y0)


def _checkpoint_signature(engine, analysis, crop):
    payload = {
        "version": 1,
        # Temporary conversion paths differ on every run; identify the original
        # exposures so a cancelled converted job can still resume.
        "files": [(str(p.resolve()), p.stat().st_size, p.stat().st_mtime_ns)
                  for p in (engine.source_image_paths or engine.image_paths)],
        "crop": vars(crop),
        "options": [engine.extension_factor, engine.ghost_frames_per_real,
                    engine.synthetic_fade_factor, engine.use_foreground_mask,
                    engine.fill_gaps, engine.blend_mode, engine.save_frames, engine.no_stack,
                    engine.raw_noise_reduction, engine.raw_exposure_ev,
                    engine.video_slowdown, engine.image_resolution,
                    engine.tail_taper_strength, engine.tail_angle_threshold],
        "transforms": [np.round(t.matrix, 6).tolist() for t in analysis.transforms],
        "valid": [t.is_valid for t in analysis.transforms],
    }
    if engine.conversion_format != "none":
        payload["conversion_format"] = engine.conversion_format
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def stack_field(engine, analysis: FieldAnalysis, crop: CropRegion) -> str:
    """Render real and synthetic frames along the fitted field trajectory.

    Synthetic motion is a relative field transform, so even pure translation
    and an off-image pole work without a fabricated image-centre fallback.
    """
    engine.check_cancelled()
    accumulator_shape = (crop.height, crop.width, 3)
    valid_indices = [f.frame_index for f in analysis.frames if f.is_valid]
    extension_duration = analysis.times[-1] * (engine.extension_factor - 1)
    extra_times = (np.linspace(analysis.times[-1], analysis.times[-1] + extension_duration,
                               max(1, math.ceil(extension_duration)) + 1)[1:]
                   if extension_duration > 0 else [])
    # Store a compact schedule, not full-resolution images.
    schedule = []
    for position, index in enumerate(valid_indices):
        engine.check_cancelled()
        schedule.append((index, analysis.times[index], False))
        if position + 1 < len(valid_indices):
            next_time = analysis.times[valid_indices[position + 1]]
            interval = next_time - analysis.times[index]
            count = engine.ghost_frames_per_real if engine.extension_factor > 1 else 0
            if engine.fill_gaps and interval > 1.5:
                count = max(count, math.ceil(interval) - 1)
            for time in np.linspace(analysis.times[index], next_time, count + 2)[1:-1]:
                engine.check_cancelled()
                schedule.append((index, time, True))
    schedule.extend((valid_indices[-1], time, True) for time in extra_times)
    # The cutoff applies to the synthetic future after the last observed
    # exposure. Gap interpolation remains intact, so this control cannot
    # remove missing-exposure repair frames.
    def angle_at(time):
        """Return the fitted field angle in degrees at a schedule time."""
        return np.degrees(float(
            analysis.angle_coefficients @ [1, time / analysis.time_span]
        ))

    last_real_time = float(analysis.times[valid_indices[-1]])
    last_real_angle = angle_at(last_real_time)
    if engine.tail_angle_threshold > 0:
        schedule = [
            item for item in schedule
            if not (item[2] and item[1] > last_real_time
                    and not within_tail_angle(
                        angle_at(item[1]) - last_real_angle,
                        engine.tail_angle_threshold))
        ]
    future_tail_angles = [
        abs(angle_at(item[1]) - last_real_angle)
        for item in schedule if item[2] and item[1] > last_real_time
    ]
    tail_span = max(future_tail_angles, default=0.0)
    total = len(schedule) + 1
    video_steps = video_step_repeats(schedule, engine.video_slowdown, engine.video_hyperlapse)
    checkpoint = engine.output_file.with_suffix(".field-checkpoint.npz")
    signature = _checkpoint_signature(engine, analysis, crop)
    renderer, reason = create_renderer(accumulator_shape, engine.compute_backend, engine.check_cancelled)
    engine.compute_info.update(backend=renderer.backend, device=renderer.device_name)
    if reason:
        engine.compute_info["fallback_reason"] = reason
    start_step = 0
    # An encoded video cannot resume from an accumulator alone; replay its whole
    # schedule so the beginning of the movie is never silently lost.
    if engine.use_checkpoint and engine.resume and checkpoint.exists() and not engine.video_enabled:
        with np.load(checkpoint, allow_pickle=False) as saved:
            if str(saved["signature"]) != signature or saved["accumulator"].shape != accumulator_shape:
                raise ValueError("Recovery checkpoint belongs to different inputs or settings. Disable resume to start again.")
            start_step = int(saved["step"])
            if not 0 <= start_step <= len(schedule):
                raise ValueError("Invalid recovery checkpoint progress. Disable resume to start again.")
            renderer.restore(saved["accumulator"])
    encoder = None
    cached_index, aligned, sky_mask = None, None, None
    sky_source = None
    # Keep this display artifact beside the requested output so the browser can
    # read it while the final TIFF is still being rendered in a temp directory.
    live_preview_path = engine.output_file.with_suffix(".live.jpg")
    last_live_preview = 0.0
    live_preview_revision = 0
    real_frames_since_checkpoint = 0
    # Keep short schedules resumable after an early interruption. Larger
    # sequences use the lower-I/O ten-real-frame cadence.
    checkpoint_real_interval = (1 if len(valid_indices) < 10 else
                                max(10, adaptive_checkpoint_interval(
                                    int(np.prod(accumulator_shape)) * 4,
                                    base=10)))
    needed_indices = dict.fromkeys(index for index, _, _ in schedule[start_step:])

    def read(index):
        engine.check_cancelled()
        image = load_image(engine.image_paths[index], for_export=True,
                           raw_noise_reduction=engine.raw_noise_reduction,
                           raw_exposure_ev=engine.raw_exposure_ev)
        engine.check_cancelled()
        return index, image

    images = ordered_map(read, needed_indices, workers=engine.cpu_workers,
                          cancel_check=engine.check_cancelled)
    crop_translation = np.array([[1, 0, -crop.x_start], [0, 1, -crop.y_start], [0, 0, 1]])
    engine.emit_progress({"stage": "pass2", "status": "stacking", "progress": 0,
                          "current": 0, "total": total, "compute": dict(engine.compute_info)})
    try:
        if engine.video_enabled:
            from video.ffmpeg_writer import create_video_writer
            video_width, video_height = engine.video_dimensions(crop.width, crop.height)
            encoder = create_video_writer(engine.render_output_file.with_suffix(".mp4"),
                                          video_width, video_height,
                                          engine.video_fps, engine.quality, container=engine.video_format)
        for step, (index, time, synthetic) in enumerate(schedule, 1):
            engine.check_cancelled()
            if step <= start_step:
                continue
            if not synthetic:
                real_frames_since_checkpoint += 1
            if index != cached_index:
                loaded_index, image = next(images)
                if loaded_index != index:
                    raise RuntimeError("Prefetched frame order differs from the render schedule")
                engine.check_cancelled()
                aligned = renderer.align(image, analysis.transforms[index].matrix, crop)
                del image
                cached_index = index
                sky_mask, sky_source = None, None
                if engine.use_foreground_mask and (engine.extension_factor > 1 or engine.fill_gaps):
                    from synthesis.foreground_mask import segment_sky_ground
                    pixels = renderer.download(aligned)
                    preview = np.clip(pixels / max(float(pixels.max()), 1) * 255, 0, 255).astype(np.uint8)
                    sky_mask = renderer.upload_mask(segment_sky_ground(preview).astype(np.float32) / 255)
                    sky_source = renderer.masked(aligned, sky_mask)
            frame = aligned
            tail_fade = 1.0
            if synthetic:
                relative = analysis.motion_at(time) @ np.linalg.inv(analysis.motion_at(analysis.times[index]))
                relative = crop_translation @ relative @ np.linalg.inv(crop_translation)
                source = aligned if sky_source is None else sky_source
                frame = renderer.warp(source, relative[:2])
                if time > last_real_time:
                    angle_delta = angle_at(time) - last_real_angle
                    tail_fade = tail_opacity(angle_delta, tail_span, engine.tail_taper_strength)
            # Additive stacks must not brighten with interpolation density.
            renderer.blend(frame, add=engine.blend_mode == "add" and not synthetic,
                            fade=((1 - engine.synthetic_fade_factor) * tail_fade
                                  if synthetic else 1),
                            mask=sky_mask if synthetic else None)
            if engine.save_frames and not synthetic:
                engine.check_cancelled()
                bit_depth = 16 if engine.first_info["dtype"] == "uint16" else 8
                save_tiff(renderer.download(aligned), engine.output_file.parent / "aligned_frames" / f"frame_{index:05}.tiff", bit_depth)
            video_snapshot = None
            if encoder and step in video_steps:
                engine.check_cancelled()
                video_snapshot = renderer.snapshot()
                for _ in range(video_steps[step]):
                    encoder.write_accumulator_snapshot(video_snapshot)
            # Keep the working image visible while the stack grows. Read back
            # occasionally so preview encoding never becomes the bottleneck.
            now = time_module.monotonic()
            if (not synthetic and (step == 1 or step == total or now - last_live_preview >= 0.25)):
                # Reuse the video readback when this real step was encoded;
                # GPU stacks otherwise paid for two full-frame downloads.
                preview_source = video_snapshot if video_snapshot is not None else renderer
                if write_live_preview(preview_source, live_preview_path):
                    last_live_preview = now
                    live_preview_revision += 1
            # Ghost frames are derived views and can be emitted much more
            # frequently than real exposures. Checkpoint only after every ten
            # real frames so extension density does not multiply disk writes.
            if (engine.use_checkpoint and not synthetic
                    and real_frames_since_checkpoint >= checkpoint_real_interval):
                real_frames_since_checkpoint = 0
                checkpoint.parent.mkdir(parents=True, exist_ok=True)
                temporary = checkpoint.with_suffix(".tmp")
                with temporary.open("wb") as stream:
                    np.savez(stream, signature=signature, step=step, accumulator=renderer.snapshot())
                temporary.replace(checkpoint)
            progress = {"stage": "pass2", "status": "processing_frame",
                        "progress": step / total, "current": step, "total": total}
            if live_preview_revision:
                progress["live_preview_path"] = str(live_preview_path)
                progress["live_preview_revision"] = live_preview_revision
            engine.emit_progress(progress)
        engine.check_cancelled()
        result = engine.output_file.parent / "aligned_frames"
        if not engine.no_stack:
            bit_depth = 16 if engine.first_info["dtype"] == "uint16" else 8
            from modules.export_images import save_stack_export
            result = save_stack_export(renderer.snapshot(), engine.render_output_file, bit_depth, engine.image_format)
        engine.emit_progress({"stage": "pass2", "status": "saving", "progress": 1,
                              "current": total, "total": total})
    finally:
        try:
            images.close()
            if encoder:
                try:
                    engine.emit_progress({"stage": "video_render", "status": "finalizing_video", "progress": 0})
                    encoder.close(cancel_check=engine.check_cancelled)
                except BaseException:
                    encoder.abort()
                    raise
        finally:
            renderer.close()
    return str(result)
