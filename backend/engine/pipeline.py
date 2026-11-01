"""
Star Trail Aligner - Alignment Pipeline

The two-pass alignment and stacking routines used by both the CLI
(`main.py`) and the FastAPI backend (`backend/engine/alignment_engine.py`).

Pass 1 (Analysis):   Track Polaris through all frames, calculate transforms
Pass 2 (Stacking):   Apply transforms, crop, and stack using lighten blend

This module was recovered from the pre-refactor `main.py` (commit 005bad4)
after commit 1a07ef4 replaced `main.py` with a thin CLI wrapper without
moving these functions out of it, which broke `AlignmentEngine`.
"""

import sys
import numpy as np
import cv2
import time as time_module
import threading
from pathlib import Path
from tqdm import tqdm
from contextlib import ExitStack, closing
from core.parallel import ordered_map
from core.compute import adaptive_checkpoint_interval
from core.video_schedule import evenly_spaced
from core.trail_effects import tail_opacity, validate_tail_settings, within_tail_angle

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config import (
    PROGRESS_BAR_FORMAT,
    CHECKPOINT_INTERVAL,
    KALMAN_PROCESS_NOISE,
    KALMAN_MEASUREMENT_NOISE,
    SEARCH_WINDOW_SIZE,
    MAX_JUMP_THRESHOLD,
    STAR_THRESHOLD_PERCENTILE,
    MIN_BLOB_AREA,
    MAX_BLOB_AREA,
)
from modules.io_utils import load_image, save_tiff
from core.cancellation import check_cancelled
from modules.gui import StarSelection
from modules.tracker import track_sequence, get_tracking_summary
from modules.transform import (
    calculate_transforms_from_tracking,
    apply_transform_and_crop,
    get_transform_statistics,
    get_cumulative_rotation_angles,
    CropRegion,
    WarpWorkspace,
)
from backend.engine.live_preview import write_live_preview

# Optional imports for extended features
try:
    from core.checkpoint import save_checkpoint, load_checkpoint
    CHECKPOINT_AVAILABLE = True
except ImportError:
    CHECKPOINT_AVAILABLE = False

try:
    from synthesis.synthetic_generator import iter_ghost_frames as generate_ghost_frames
    from synthesis.foreground_mask import segment_sky_ground
    SYNTHESIS_AVAILABLE = True
except ImportError:
    SYNTHESIS_AVAILABLE = False


def pass1_analysis(
    image_paths: list,
    star_selection: StarSelection,
    use_rotation: bool = False,
    use_kalman: bool = True,
    kalman_process_noise: float = KALMAN_PROCESS_NOISE,
    kalman_measurement_noise: float = KALMAN_MEASUREMENT_NOISE,
    search_window_size: int = SEARCH_WINDOW_SIZE,
    max_jump_threshold: float = MAX_JUMP_THRESHOLD,
    star_threshold_percentile: float = STAR_THRESHOLD_PERCENTILE,
    min_blob_area: int = MIN_BLOB_AREA,
    max_blob_area: int = MAX_BLOB_AREA,
    progress_callback=None,
    cancel_check=None,
    workers=1,
) -> tuple:
    """
    Pass 1: Analyze all images to track stars and calculate transforms.

    Args:
        image_paths: List of paths to image files
        star_selection: StarSelection with Polaris (and optional second star) position
        use_rotation: Whether to use rotation correction
        use_kalman: Whether to use Kalman filtering for tracking
        kalman_process_noise: Process noise variance for Kalman filter
        kalman_measurement_noise: Measurement noise variance for Kalman filter
        search_window_size: ROI size for star search
        max_jump_threshold: Maximum allowed frame-to-frame jump in pixels
        star_threshold_percentile: Percentile threshold for star pixels in ROI
        min_blob_area: Minimum star blob area in pixels
        max_blob_area: Maximum star blob area in pixels
        progress_callback: Optional callable(current, total) invoked per tracked
            frame. When provided, replaces the internal tqdm bar so callers such
            as the Electron backend can stream progress instead.

    Returns:
        Tuple of (tracking_results, transforms)
    """
    print("\n" + "="*60)
    print("PASS 1: ANALYSIS - Tracking stars through all frames")
    print("="*60)

    # Print tracking mode
    tracking_mode = []
    if use_kalman:
        tracking_mode.append("Kalman filtering")
    if use_rotation:
        tracking_mode.append("rotation correction")
    if tracking_mode:
        print(f"Mode: {', '.join(tracking_mode)}")

    check_cancelled(cancel_check)
    # Track stars through sequence
    print("\nTracking Polaris position in each frame...")

    if progress_callback is not None:
        # Caller drives progress (e.g. Electron backend streaming over WebSocket)
        tracking_results = track_sequence(
            images=image_paths,
            initial_polaris=star_selection.polaris,
            initial_second_star=star_selection.second_star if use_rotation else None,
            progress_callback=progress_callback,
            use_kalman=use_kalman,
            kalman_process_noise=kalman_process_noise,
            kalman_measurement_noise=kalman_measurement_noise,
            search_window_size=search_window_size,
            max_jump_threshold=max_jump_threshold,
            star_threshold_percentile=star_threshold_percentile,
            min_blob_area=min_blob_area,
            max_blob_area=max_blob_area,
            cancel_check=cancel_check,
            prefetch_workers=workers,
        )
    else:
        with tqdm(total=len(image_paths), bar_format=PROGRESS_BAR_FORMAT) as pbar:
            def _pbar_callback(current, total):
                pbar.update(1) if current > pbar.n else None
                pbar.n = current
                pbar.refresh()

            tracking_results = track_sequence(
                images=image_paths,
                initial_polaris=star_selection.polaris,
                initial_second_star=star_selection.second_star if use_rotation else None,
                progress_callback=lambda c, t: pbar.update(1) if c == pbar.n else None,
                use_kalman=use_kalman,
                kalman_process_noise=kalman_process_noise,
                kalman_measurement_noise=kalman_measurement_noise,
                search_window_size=search_window_size,
                max_jump_threshold=max_jump_threshold,
                star_threshold_percentile=star_threshold_percentile,
                min_blob_area=min_blob_area,
                max_blob_area=max_blob_area,
                cancel_check=cancel_check,
                prefetch_workers=workers,
            )
            pbar.n = len(image_paths)
            pbar.refresh()

    check_cancelled(cancel_check)
    # Print tracking summary
    summary = get_tracking_summary(tracking_results)
    print(f"\nTracking Summary:")
    print(f"  • Frames processed: {summary['total_frames']}")
    print(f"  • Successful tracks: {summary['successful_tracks']} ({summary['success_rate']*100:.1f}%)")
    print(f"  • Fallback frames: {summary['fallback_used']}")
    print(f"  • Total drift: {summary['max_drift']:.1f} pixels")

    # Calculate transforms
    print("\nCalculating alignment transforms...")
    transforms = calculate_transforms_from_tracking(
        tracking_results,
        use_rotation=use_rotation
    )

    # Print transform statistics
    stats = get_transform_statistics(transforms)
    print(f"\nTransform Statistics:")
    print(f"  • Max horizontal shift: {stats['max_dx']:.1f} px")
    print(f"  • Max vertical shift: {stats['max_dy']:.1f} px")
    print(f"  • Average shift: ({stats['avg_dx']:.1f}, {stats['avg_dy']:.1f}) px")
    if use_rotation and stats.get('total_rotation_deg', 0) != 0:
        print(f"  • Total rotation: {stats['total_rotation_deg']:.3f}°")

    return tracking_results, transforms




def pass2_stacking(
    image_paths: list,
    transforms: list,
    crop: CropRegion,
    output_path: Path,
    sample_is_raw: bool,
    sample_dtype: str = 'uint8',
    video_encoder=None,
    extension_factor: float = 1.0,
    video_slowdown: int = 1,
    tail_taper_strength: float = 0.0,
    tail_angle_threshold: float = 0.0,
    reference_polaris: tuple = None,
    use_foreground_mask: bool = True,
    video_hyperlapse: bool = False,
    blend_mode: str = 'lighten',
    checkpoint_dir: str = None,
    use_checkpoint: bool = True,
    resume: bool = False,
    ghost_frames_per_real: int = 10,
    synthetic_fade_factor: float = 0.2,
    fill_gaps: bool = False,
    progress_callback=None,
    cancel_check=None,
    workers=1,
    raw_noise_reduction=True,
    raw_exposure_ev=0.0,
    live_preview_path: Path = None,
    live_preview_callback=None,
    conversion_format="none",
    image_format="tiff",
) -> None:
    """
    Pass 2: Apply transforms and stack all images.

    Args:
        image_paths: List of paths to image files
        transforms: List of TransformData for each frame
        crop: CropRegion defining the output dimensions
        output_path: Path for output file
        sample_is_raw: Whether the source images are RAW files
        sample_dtype: Data type of the source images (e.g., 'uint8', 'uint16')
        video_encoder: Optional TrailLapseEncoder for video output
        extension_factor: Trail extension multiplier (1.0 = no extension)
        video_slowdown: Approximate video snapshots per real exposure interval
            in slow-motion mode. The stack's ghost density is unchanged.
        tail_taper_strength: Fade strength for the synthetic future tail (0–1).
        tail_angle_threshold: Stop synthetic future frames after this angle in
            degrees; zero disables the cutoff.
        reference_polaris: Polaris position for extension (required if extension > 1.0)
        use_foreground_mask: Whether to use foreground masking during extension
        video_hyperlapse: If True, write one video frame per image (fast). If False, write each ghost frame (slow-motion)
        blend_mode: 'lighten' (np.maximum) or 'add' (np.add) stacking mode
        checkpoint_dir: Directory for checkpoint files
        use_checkpoint: Whether to save checkpoints periodically
        resume: Whether to resume from a saved checkpoint
    """
    print("\n" + "="*60)
    print("PASS 2: STACKING - Applying transforms and blending")
    print("="*60)

    tail_taper_strength, tail_angle_threshold = validate_tail_settings(
        tail_taper_strength, tail_angle_threshold
    )

    # Show mode info
    modes = []
    if extension_factor > 1.0:
        modes.append(f"trail extension {extension_factor:.1f}x")
    if video_encoder:
        modes.append("video recording")
    if blend_mode == 'add':
        modes.append('additive blending')
    if modes:
        print(f"Mode: {', '.join(modes)}")

    check_cancelled(cancel_check)
    video_slowdown = max(1, int(video_slowdown))
    # Initialize 32-bit float accumulator
    print(f"\nInitializing canvas: {crop.width}x{crop.height} pixels")
    accumulator = np.zeros((crop.height, crop.width, 3), dtype=np.float32)

    # Resume from checkpoint if available
    start_frame = 0
    if resume and use_checkpoint and checkpoint_dir and CHECKPOINT_AVAILABLE:
        cp_data, last_frame, additional = load_checkpoint(Path(checkpoint_dir), pass_num=2)
        if cp_data is not None and additional and 'accumulator' in additional:
            if additional.get('conversion_format', 'none') != conversion_format:
                raise ValueError("Recovery checkpoint uses a different conversion format. Disable resume to start again.")
            if (additional.get('tail_taper_strength', 0.0) != tail_taper_strength
                    or additional.get('tail_angle_threshold', 0.0) != tail_angle_threshold):
                raise ValueError("Recovery checkpoint uses different tail settings. Disable resume to start again.")
            try:
                accumulator = additional['accumulator']
                start_frame = last_frame + 1
                print(f"  Resumed from checkpoint at frame {last_frame}")
            except Exception as e:
                print(f"  Warning: Could not restore accumulator from checkpoint: {e}")
                start_frame = 0

    # Get cumulative rotation angles for synthetic extension/extrapolation
    rotation_angles = None
    if extension_factor > 1.0:
        rotation_angles = get_cumulative_rotation_angles(transforms)

        # Check if we have valid rotation data (if max rotation is tiny, we probably didn't track rotation)
        max_rot = max(abs(a) for a in rotation_angles) if rotation_angles else 0
        if max_rot < 0.1:
            print("  Note: No significant rotation detected from alignment.")

            # Try estimating from translation (if Polaris is far enough)
            est_angles = []
            if reference_polaris:
                # Need absolute center of original image
                # crop.x_start + crop.width/2 is center of CROP, not original
                # But estimate function expects image_center of ORIGINAL frame relative to polaris
                # We can approximate using crop center if crop is centered, but safer to use timestamps
                pass

            # Primary Fallback: Earth rotation rate based on timestamps
            # This is the most robust method for extrapolation
            print("  Using Earth rotation rate from timestamps...")
            try:
                from modules.io_utils import get_timestamps_for_files
                timestamps = get_timestamps_for_files(image_paths)

                if len(timestamps) >= 2 and timestamps[-1] > timestamps[0]:
                    start_time = timestamps[0]
                    # Earth rate: 360 deg / 86164 sec (sidereal day) ~= 0.004178 deg/sec
                    EARTH_RATE = 360.0 / 86164.0

                    rotation_angles = []
                    for ts in timestamps:
                        delta_sec = (ts - start_time).total_seconds()
                        rotation_angles.append(delta_sec * EARTH_RATE)

                    print(f"  ✓ Calculated rotation from timestamps: {rotation_angles[-1]:.2f}° total ({len(rotation_angles)} frames)")
                else:
                    print("  Warning: Invalid timestamps, falling back to 30s interval default.")
                    # Default: 30s per frame = 0.125 deg/frame
                    rotation_angles = [i * 0.125 for i in range(len(image_paths))]
            except ImportError:
                print("  Warning: Timestamp module not available, using default speed.")
                rotation_angles = [i * 0.125 for i in range(len(image_paths))]

    # Create foreground mask from first frame if using extension
    ext_schedule = None
    if extension_factor > 1.0 and rotation_angles is not None and len(rotation_angles) >= 2:
        from core.scheduler import generate_extension_schedule
        ext_schedule = generate_extension_schedule(
            num_real_frames=len(image_paths),
            rotation_angles=rotation_angles,
            extension_factor=extension_factor
        )
        if tail_angle_threshold > 0:
            extension_angles = [
                angle for angle in ext_schedule.extension_rotation_angles
                if within_tail_angle(angle, tail_angle_threshold)
            ]
            ext_schedule = ext_schedule.__class__(
                num_real_frames=ext_schedule.num_real_frames,
                num_extension_frames=len(extension_angles),
                rotation_speed=ext_schedule.rotation_speed,
                extension_rotation_angles=extension_angles,
            )
    total_steps = len(image_paths) + (ext_schedule.num_extension_frames if ext_schedule else 0) + 1
    completed_steps = 0
    live_preview_revision = 0
    last_live_preview = 0.0
    checkpoint_interval = adaptive_checkpoint_interval(accumulator.nbytes,
                                                       base=CHECKPOINT_INTERVAL)

    def publish_live_preview(force=False):
        nonlocal live_preview_revision, last_live_preview
        if live_preview_path is None:
            return
        now = time_module.monotonic()
        if not force and now - last_live_preview < 0.25:
            return
        if write_live_preview(accumulator, live_preview_path):
            last_live_preview = now
            live_preview_revision += 1
            if live_preview_callback:
                live_preview_callback(str(live_preview_path), live_preview_revision)

    def write_video_snapshot(repeats=1):
        if not video_encoder:
            return
        for _ in range(max(1, int(repeats))):
            check_cancelled(cancel_check)
            video_encoder.write_accumulator_snapshot(accumulator)

    if progress_callback:
        progress_callback(completed_steps, total_steps)

    sky_mask = None
    # On a fresh run the first aligned frame below is also the best source for
    # the foreground mask. Building it in the stacking loop avoids decoding
    # and warping that exposure a second time. A resumed run still uses the
    # original first frame so its mask remains identical to the pre-checkpoint
    # render.
    if (extension_factor > 1.0 and SYNTHESIS_AVAILABLE and use_foreground_mask
            and start_frame > 0):
        check_cancelled(cancel_check)
        first_image = load_image(image_paths[0], for_export=True,
                                 raw_noise_reduction=raw_noise_reduction,
                                 raw_exposure_ev=raw_exposure_ev)
        first_image_float = first_image.astype(np.float32)
        first_aligned = apply_transform_and_crop(first_image_float, transforms[0], crop)
        sky_mask = segment_sky_ground(first_aligned.astype(np.uint8))
        del first_image
        del first_image_float
        del first_aligned

    # Adjust Polaris position for crop
    adjusted_polaris = None
    if reference_polaris and extension_factor > 1.0:
        # Polaris position relative to cropped frame
        adjusted_polaris = (
            reference_polaris[0] - crop.x_start,
            reference_polaris[1] - crop.y_start
        )

    # Process each frame
    print("\nProcessing frames...")

    # Decode and warp in the bounded prefetch workers. OpenCV releases the GIL
    # for both operations, so this overlaps I/O and Lanczos work while the
    # main thread remains responsible for ordered blending/checkpoints.
    worker_state = threading.local()

    def read(item):
        img_path, transform = item
        check_cancelled(cancel_check)
        image = load_image(img_path, for_export=True,
                           raw_noise_reduction=raw_noise_reduction, raw_exposure_ev=raw_exposure_ev)
        check_cancelled(cancel_check)
        image_float = image.astype(np.float32)
        workspace = getattr(worker_state, "workspace", None)
        if workspace is None:
            workspace = worker_state.workspace = WarpWorkspace()
        aligned = apply_transform_and_crop(image_float, transform, crop, workspace=workspace)
        return aligned

    with ExitStack() as resources:
        # A resumed checkpoint already contains every frame before
        # ``start_frame``. Avoid decoding and warping those images again.
        frames = resources.enter_context(closing(ordered_map(
            read, zip(image_paths[start_frame:], transforms[start_frame:]),
            workers=workers, cancel_check=cancel_check)))
        pbar = resources.enter_context(tqdm(total=len(image_paths), bar_format=PROGRESS_BAR_FORMAT))
        for offset, aligned in enumerate(frames):
            i = start_frame + offset
            check_cancelled(cancel_check)

            if (sky_mask is None and extension_factor > 1.0 and SYNTHESIS_AVAILABLE
                    and use_foreground_mask):
                sky_mask = segment_sky_ground(aligned.astype(np.uint8))

            # Blend: lighten (keep brightest) or add (accumulate brightness)
            if blend_mode == 'add':
                np.add(accumulator, aligned, out=accumulator)
            else:
                np.maximum(accumulator, aligned, out=accumulator)

            # In slow-motion mode, repeat real-only frames when no synthetic
            # states exist. With extension enabled, synthetic states sampled
            # below provide the requested cadence.
            wrote_real_video = False
            if video_encoder:
                repeats = 1 if video_hyperlapse or extension_factor > 1.0 else video_slowdown
                write_video_snapshot(repeats)
                wrote_real_video = True

            # Generate and add ghost frames for trail extension
            if extension_factor > 1.0 and SYNTHESIS_AVAILABLE and rotation_angles is not None:
                if i < len(image_paths) - 1:
                    ghosts = generate_ghost_frames(
                        aligned,
                        rotation_angles[i],
                        rotation_angles[i + 1],
                        adjusted_polaris if adjusted_polaris else (crop.width / 2, crop.height / 2),
                        num_ghosts=ghost_frames_per_real,
                        fade_factor=synthetic_fade_factor,
                        extension_factor=extension_factor,
                        tail_taper_strength=tail_taper_strength,
                        tail_angle_threshold=tail_angle_threshold,
                        sky_mask=sky_mask,
                        cancel_check=cancel_check,
                    )
                    ghost_count = (max(1, int(ghost_frames_per_real * (extension_factor - 1.0)))
                                   if ghost_frames_per_real >= 1
                                   and abs(rotation_angles[i + 1] - rotation_angles[i]) >= 0.001
                                   else 0)
                    selected_ghosts = set(evenly_spaced(
                        range(ghost_count), max(0, video_slowdown - 1)))
                    for ghost_index, ghost in enumerate(ghosts):
                        check_cancelled(cancel_check)
                        np.maximum(accumulator, ghost, out=accumulator)

                        # Write only the evenly spaced video subset. Every
                        # generated ghost still contributes to the final TIFF.
                        if (video_encoder and not video_hyperlapse
                                and ghost_index in selected_ghosts):
                            write_video_snapshot()

            # Write final state to video in slow-motion mode (if no ghosts were generated)
            if (video_encoder and not wrote_real_video and not video_hyperlapse
                    and (extension_factor <= 1.0 or not SYNTHESIS_AVAILABLE)):
                write_video_snapshot(video_slowdown)


            # Memory cleanup
            del aligned

            # Save checkpoint periodically
            if use_checkpoint and checkpoint_dir and CHECKPOINT_AVAILABLE:
                if (i + 1) % checkpoint_interval == 0:
                    save_checkpoint(
                        alignment_data=[],
                        pass_num=2,
                        frame_num=i,
                        checkpoint_dir=Path(checkpoint_dir),
                        additional_data={
                            'accumulator': accumulator,
                            'conversion_format': conversion_format,
                            'tail_taper_strength': tail_taper_strength,
                            'tail_angle_threshold': tail_angle_threshold,
                        }
                    )

            pbar.update(1)
            completed_steps += 1
            publish_live_preview()
            if progress_callback:
                progress_callback(completed_steps, total_steps)

    # =====================================================================
    # SYNTHETIC FUTURE EXTRAPOLATION (Trail Extension Beyond Reality)
    # =====================================================================
    # After processing all real frames, generate synthetic future frames
    # by rotating the last aligned frame to extend the trails.

    if ext_schedule is not None:
        check_cancelled(cancel_check)

        if ext_schedule.num_extension_frames > 0:
            print(f"\nGenerating {ext_schedule.num_extension_frames} synthetic future frames...")
            print(f"  Rotation speed: {ext_schedule.rotation_speed:.4f}°/frame")

            # Load and align the last real frame
            last_image = load_image(image_paths[-1], for_export=True,
                                    raw_noise_reduction=raw_noise_reduction,
                                    raw_exposure_ev=raw_exposure_ev).astype(np.float32)
            last_aligned = apply_transform_and_crop(last_image, transforms[-1], crop)
            del last_image

            # Center of rotation (Polaris position in cropped coordinates)
            center = adjusted_polaris if adjusted_polaris else (crop.width / 2, crop.height / 2)

            with tqdm(total=ext_schedule.num_extension_frames,
                      bar_format=PROGRESS_BAR_FORMAT, desc="Extrapolating") as pbar2:

                extension_angles = ext_schedule.extension_rotation_angles
                # The actual generated extension can be shorter than the
                # configured cutoff. Normalize the fade over the frames that
                # really exist so the tail still reaches its requested fade.
                tail_span = max(extension_angles, default=0.0)
                selected_extension = set(evenly_spaced(
                    range(len(extension_angles)),
                    video_slowdown * max(1, len(image_paths) - 1)))
                for extension_index, angle_offset in enumerate(extension_angles):
                    check_cancelled(cancel_check)
                    # Rotate the last frame around Polaris
                    rotation_matrix = cv2.getRotationMatrix2D(center, angle_offset, 1.0)
                    rotated = cv2.warpAffine(
                        last_aligned,
                        rotation_matrix,
                        (crop.width, crop.height),
                        flags=cv2.INTER_LANCZOS4,
                        borderMode=cv2.BORDER_CONSTANT,
                        borderValue=(0, 0, 0)
                    )

                    # Apply sky mask to avoid extending foreground
                    if sky_mask is not None and use_foreground_mask:
                        rotated = rotated * (sky_mask[:, :, np.newaxis] / 255.0)

                    if tail_taper_strength > 0:
                        rotated = rotated * tail_opacity(
                            angle_offset, tail_span, tail_taper_strength
                        )

                    # Accumulate (lighten blend)
                    np.maximum(accumulator, rotated, out=accumulator)

                    # Write to video
                    if (video_encoder and not video_hyperlapse
                            and extension_index in selected_extension):
                        write_video_snapshot()

                    pbar2.update(1)
                    completed_steps += 1
                    publish_live_preview()
                    if progress_callback:
                        progress_callback(completed_steps, total_steps)

            del last_aligned
            print(f"  ✓ Trail extension complete!")

    # Determine output bit depth (16-bit for RAW or 16-bit TIFF input)
    bit_depth = 16 if (sample_is_raw or sample_dtype == 'uint16') else 8

    # Save result
    check_cancelled(cancel_check)
    print(f"\nSaving result to: {output_path}")
    from modules.export_images import save_stack_export
    actual_output_path = save_stack_export(accumulator, output_path, bit_depth, image_format)
    publish_live_preview(force=True)
    if progress_callback:
        progress_callback(total_steps, total_steps)

    # Final statistics
    print(f"\n✓ Successfully created star trail stack!")
    print(f"  • Output file: {actual_output_path}")
    print(f"  • Dimensions: {crop.width}x{crop.height}")
    print(f"  • Bit depth: {bit_depth}-bit")
    print(f"  • Frames stacked: {len(image_paths)}")
    if extension_factor > 1.0:
        print(f"  • Trail extension: {extension_factor}x")
