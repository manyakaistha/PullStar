"""
PullStar - Model Context Protocol (MCP) Server.

Exposes tools, resources, and prompts that allow AI agents to:
1. Inspect astrophotography exposure sequences (RAW/TIFF/JPEG/PNG, EXIF timestamps, gaps, sky/foreground).
2. Detect stars and benchmark alignment strategies (automatic multi-star field alignment vs manual Kalman star tracking).
3. Find the optimal stacking & synthesis settings for any sequence and creative goal.
4. Render fast preview stacks, execute full-resolution stacks (synchronously or asynchronously), and verify stack quality.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:  # pragma: no cover - fallback for mcp 1.x environments
    from mcp.server.fastmcp import FastMCP as MCPServer  # type: ignore

import config as app_config
from backend.services.job_manager import job_manager
from core.compute import system_capabilities, worker_count
from mcp_server.diagnostics import (
    analyze_star_field_data,
    compare_alignment_candidates_data,
    evaluate_alignment_config,
    evaluate_stack_image,
    execute_stack_pipeline,
    inspect_sequence_data,
    recommend_stack_settings,
    render_annotated_preview_image,
    render_preview_stack_data,
)

SERVER_INSTRUCTIONS = """
You are connected to the PullStar MCP Server.

To find the right settings and create a high-quality star trail stack:
1. Start with `inspect_sequence(input_dir)` or `recommend_settings(input_dir, goal=...)` to understand:
   - Frame count, resolution, RAW vs 8/16-bit format, and hardware worker sizing.
   - EXIF timestamp intervals and whether dropped-exposure gaps exist (`fill_gaps`).
   - Foreground landscape fraction (`use_foreground_mask`).
   - Whether the celestial rotation pole is inside or outside the frame and whether automatic `star_field` alignment (`polaris_x=None, polaris_y=None`) or `manual_tracking` is best.
2. When comparing alignment strategies or tuning tracking parameters, call `compare_alignment_candidates(input_dir)` or `evaluate_alignment_settings(input_dir, ...)` to run a fast Pass 1 dry-run and inspect `alignment_score`, `valid_frame_ratio`, `area_retention_ratio`, and `rms_step_jitter_px`.
3. To test trail synthesis parameters (`extension_factor`, `tail_taper_strength`, `tail_angle_threshold`, `ghost_frames_per_real`, `synthetic_fade_factor`, `fill_gaps`, `use_foreground_mask`, `blend_mode`) quickly on large datasets, call `render_preview_stack(input_dir, ...)`.
4. To produce the final stack, call `create_stack(...)` (or `auto_tune_and_stack(...)` for automated closed-loop tuning + verification, or `start_stack_job(...)` for background execution) and check `quality_report` (`overall_quality_score`, `trail_continuity_score`, `clipping_fraction`, `tuning_suggestions`). Use `image_resolution` to reduce stack processing cost, and `video_resolution` to choose the encoded video size. For trail-lapse video, use `video_slowdown=1` for the fastest export or 2, 4, or 8 for progressively slower pacing.
""".strip()


def create_mcp_server(name: str = "pullstar") -> MCPServer:
    """Create and configure the PullStar MCPServer instance."""
    mcp = MCPServer(name, instructions=SERVER_INSTRUCTIONS)

    # =========================================================================
    # DISCOVERY & SEQUENCE DIAGNOSTICS TOOLS
    # =========================================================================

    @mcp.tool()
    def inspect_sequence(
        input_dir: str,
        sort_by_time: bool = True,
        sample_frames: int = 5,
        raw_noise_reduction: bool = True,
    ) -> Dict[str, Any]:
        """
        Inspect an astrophotography exposure sequence directory.

        Returns image dimensions, RAW/bit-depth metadata, validation checks,
        EXIF timestamp intervals & timeline gaps, sampled star counts & brightness
        percentiles, sky/foreground segmentation coverage, manual reference star
        candidates, and recommended compute worker count.
        """
        return inspect_sequence_data(
            input_dir=input_dir,
            sort_by_time=sort_by_time,
            sample_frames=sample_frames,
            raw_noise_reduction=raw_noise_reduction,
        )

    @mcp.tool()
    def detect_and_analyze_stars(
        input_dir: str,
        frame_step: int = 10,
        sort_by_time: bool = True,
        raw_noise_reduction: bool = True,
        max_candidates: int = 8,
    ) -> Dict[str, Any]:
        """
        Run automatic star detection and multi-frame geometric matching across the
        sequence, and identify bright isolated candidate stars (`polaris` and `second_star`)
        for manual tracking.

        Indicates whether the celestial rotation pole is inside or outside the frame
        and recommends either `"star_field"` alignment (`polaris_x=None, polaris_y=None`)
        or `"manual_tracking"`.
        """
        return analyze_star_field_data(
            input_dir=input_dir,
            frame_step=frame_step,
            sort_by_time=sort_by_time,
            raw_noise_reduction=raw_noise_reduction,
            max_candidates=max_candidates,
        )

    @mcp.tool()
    def get_hardware_capabilities(
        width: int = 4000,
        height: int = 3000,
        is_raw: bool = False,
        requested_workers: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Query system CPU cores, memory, OpenCL GPU availability, and the recommended
        parallel worker count for a given image resolution and format.
        """
        caps = system_capabilities()
        rec_workers = worker_count(width, height, is_raw, requested_workers)
        return {
            **caps,
            "query": {"width": width, "height": height, "is_raw": is_raw},
            "recommended_workers": rec_workers,
            "recommended_compute_backend": "auto",
        }

    # =========================================================================
    # SETTINGS OPTIMIZATION & PASS 1 DRY-RUN TOOLS ("FIND THE RIGHT SETTINGS")
    # =========================================================================

    @mcp.tool()
    def recommend_settings(
        input_dir: str,
        goal: Literal[
            "balanced",
            "natural",
            "dramatic_extended",
            "gap_repair",
            "maximum_sharpness",
            "trail_lapse_video",
            "faint_stars_boost",
        ] = "balanced",
        include_pass1_probe: bool = True,
        video_export: bool = False,
    ) -> Dict[str, Any]:
        """
        Analyze an exposure sequence and synthesize the optimal settings to create
        a high-quality star trail stack for the specified `goal`.

        Returns:
        - `recommended_settings`: Complete parameter dictionary ready to pass to `create_stack`.
        - `rationale`: Detailed explanation for why each parameter was selected.
        - `pass1_probe`: Pass 1 alignment dry-run metrics verifying the recommended strategy.
        - `alternative_presets`: Ready-to-use configurations (`natural_faithful`,
          `dramatic_extended_trails`, `pure_no_synthesis`, `trail_lapse_export`).
        """
        return recommend_stack_settings(
            input_dir=input_dir,
            goal=goal,
            include_pass1_probe=include_pass1_probe,
            video_export=video_export,
        )

    @mcp.tool()
    def evaluate_alignment_settings(
        input_dir: str,
        polaris_x: Optional[float] = None,
        polaris_y: Optional[float] = None,
        star2_x: Optional[float] = None,
        star2_y: Optional[float] = None,
        use_rotation: bool = False,
        use_kalman: bool = True,
        kalman_process_noise: float = 0.01,
        kalman_measurement_noise: float = 2.0,
        search_window_size: int = 100,
        max_jump_threshold: float = 50.0,
        star_threshold_percentile: float = 99.5,
        sort_by_time: bool = True,
        raw_noise_reduction: bool = True,
        max_frames: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Run a fast Pass 1 alignment dry-run (without Pass 2 rendering) to evaluate how well
        a set of alignment/tracking parameters performs on `input_dir`.

        - Leave `polaris_x=None, polaris_y=None` to evaluate automatic multi-star field alignment (`star_field`).
        - Provide `polaris_x, polaris_y` (and optional `star2_x, star2_y`) to evaluate manual centroid tracking.

        Returns `alignment_score` (0–100), `valid_frame_ratio`, `crop` dimensions and area
        retention ratio, `transform_stats` (drift and RMS step jitter), and diagnostic feedback.
        """
        settings = {
            "polaris_x": polaris_x,
            "polaris_y": polaris_y,
            "star2_x": star2_x,
            "star2_y": star2_y,
            "use_rotation": use_rotation,
            "use_kalman": use_kalman,
            "kalman_process_noise": kalman_process_noise,
            "kalman_measurement_noise": kalman_measurement_noise,
            "search_window_size": search_window_size,
            "max_jump_threshold": max_jump_threshold,
            "star_threshold_percentile": star_threshold_percentile,
            "sort_by_time": sort_by_time,
            "raw_noise_reduction": raw_noise_reduction,
        }
        return evaluate_alignment_config(
            input_dir=input_dir,
            settings=settings,
            max_frames=max_frames,
        )

    @mcp.tool()
    def compare_alignment_candidates(
        input_dir: str,
        candidates: Optional[List[Dict[str, Any]]] = None,
        max_frames: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Benchmark multiple candidate alignment strategies side-by-side on `input_dir`
        and rank them by `alignment_score` (weighing valid frame rate, crop area retention,
        tracking confidence, and trajectory smoothness).

        If `candidates` is omitted, automatically benchmarks:
        1. `auto_star_field` (multi-star trajectory fitting & wobble removal)
        2. `manual_1star_kalman` (single-star Kalman translation tracking)
        3. `manual_2star_kalman_rotation` (two-star Kalman rotation + translation tracking)
        """
        return compare_alignment_candidates_data(
            input_dir=input_dir,
            candidates=candidates,
            max_frames=max_frames,
        )

    # =========================================================================
    # STACKING, PREVIEWING & QUALITY VERIFICATION TOOLS ("CREATE A GOOD STACK")
    # =========================================================================

    @mcp.tool()
    def render_preview_stack(
        input_dir: str,
        output_file: Optional[str] = None,
        polaris_x: Optional[float] = None,
        polaris_y: Optional[float] = None,
        star2_x: Optional[float] = None,
        star2_y: Optional[float] = None,
        use_rotation: bool = False,
        use_kalman: bool = True,
        extension_factor: float = 1.0,
        tail_taper_strength: float = 0.0,
        tail_angle_threshold: float = 0.0,
        ghost_frames_per_real: int = 10,
        synthetic_fade_factor: float = 0.2,
        use_foreground_mask: bool = True,
        fill_gaps: bool = False,
        blend_mode: Literal["lighten", "add"] = "lighten",
        sort_by_time: bool = True,
        raw_noise_reduction: bool = True,
        raw_exposure_ev: float = 0.0,
        max_dimension: int = 960,
        max_frames: int = 24,
    ) -> Dict[str, Any]:
        """
        Render a fast downscaled preview stack from a subset of frames (`max_frames` at
        `max_dimension` px) and evaluate its visual/numerical quality.

        Use this tool to quickly experiment with `extension_factor`, `tail_taper_strength`,
        `tail_angle_threshold`, `ghost_frames_per_real`,
        `synthetic_fade_factor`, `fill_gaps`, `use_foreground_mask`, `blend_mode`, and
        `raw_exposure_ev` before running a full-resolution stack.
        """
        settings = {
            "polaris_x": polaris_x,
            "polaris_y": polaris_y,
            "star2_x": star2_x,
            "star2_y": star2_y,
            "use_rotation": use_rotation,
            "use_kalman": use_kalman,
            "extension_factor": extension_factor,
            "tail_taper_strength": tail_taper_strength,
            "tail_angle_threshold": tail_angle_threshold,
            "ghost_frames_per_real": ghost_frames_per_real,
            "synthetic_fade_factor": synthetic_fade_factor,
            "use_foreground_mask": use_foreground_mask,
            "fill_gaps": fill_gaps,
            "blend_mode": blend_mode,
            "sort_by_time": sort_by_time,
            "raw_noise_reduction": raw_noise_reduction,
            "raw_exposure_ev": raw_exposure_ev,
        }
        return render_preview_stack_data(
            input_dir=input_dir,
            output_file=output_file,
            settings=settings,
            max_dimension=max_dimension,
            max_frames=max_frames,
        )

    @mcp.tool()
    def create_stack(
        input_dir: str,
        output_file: Optional[str] = None,
        polaris_x: Optional[float] = None,
        polaris_y: Optional[float] = None,
        star2_x: Optional[float] = None,
        star2_y: Optional[float] = None,
        use_rotation: bool = False,
        use_kalman: bool = True,
        kalman_process_noise: float = 0.01,
        kalman_measurement_noise: float = 2.0,
        search_window_size: int = 100,
        max_jump_threshold: float = 50.0,
        star_threshold_percentile: float = 99.5,
        extension_factor: float = 1.0,
        tail_taper_strength: float = 0.0,
        tail_angle_threshold: float = 0.0,
        ghost_frames_per_real: int = 10,
        synthetic_fade_factor: float = 0.2,
        use_foreground_mask: bool = True,
        fill_gaps: bool = False,
        blend_mode: Literal["lighten", "add"] = "lighten",
        sort_by_time: bool = True,
        raw_noise_reduction: bool = True,
        raw_exposure_ev: float = 0.0,
        conversion_format: Literal["none", "jpg", "tiff"] = "none",
        conversion_output_dir: Optional[str] = None,
        video_enabled: bool = False,
        video_fps: int = 30,
        video_slowdown: Literal[1, 2, 4, 8] = 1,
        image_resolution: Literal["source", "4k", "2k", "1080p", "720p"] = "source",
        video_resolution: Literal["source", "4k", "2k", "1080p", "720p"] = "source",
        quality: Literal["high", "prores", "lossless", "medium", "hevc"] = "high",
        image_format: Literal["tiff", "png", "jpg"] = "tiff",
        video_format: Literal["auto", "mp4", "mov"] = "auto",
        video_hyperlapse: bool = False,
        save_frames: bool = False,
        no_stack: bool = False,
        use_checkpoint: bool = True,
        resume: bool = False,
        compute_backend: Literal["auto", "cpu", "opencl"] = "auto",
        cpu_workers: Optional[int] = None,
        evaluate_output: bool = True,
        generate_preview_jpeg: bool = True,
    ) -> Dict[str, Any]:
        """
        Execute the full end-to-end Pass 1 (Alignment) + Pass 2 (Stacking & Synthesis)
        pipeline and evaluate the resulting star trail stack.

        - Omit `polaris_x` and `polaris_y` (`None`) to use automatic multi-star field alignment
          and trajectory wobble correction (`star_field` mode).
        - Provide `polaris_x` and `polaris_y` (and optional `star2_x`, `star2_y`) to use manual
          reference star tracking.

        Returns the saved TIFF `result_path`, optional `video_path`, `preview_jpeg_path`,
        alignment & crop telemetry, and a comprehensive `quality_report`.
        """
        settings = {
            "polaris_x": polaris_x,
            "polaris_y": polaris_y,
            "star2_x": star2_x,
            "star2_y": star2_y,
            "use_rotation": use_rotation,
            "use_kalman": use_kalman,
            "kalman_process_noise": kalman_process_noise,
            "kalman_measurement_noise": kalman_measurement_noise,
            "search_window_size": search_window_size,
            "max_jump_threshold": max_jump_threshold,
            "star_threshold_percentile": star_threshold_percentile,
            "extension_factor": extension_factor,
            "tail_taper_strength": tail_taper_strength,
            "tail_angle_threshold": tail_angle_threshold,
            "ghost_frames_per_real": ghost_frames_per_real,
            "synthetic_fade_factor": synthetic_fade_factor,
            "use_foreground_mask": use_foreground_mask,
            "fill_gaps": fill_gaps,
            "blend_mode": blend_mode,
            "sort_by_time": sort_by_time,
            "raw_noise_reduction": raw_noise_reduction,
            "raw_exposure_ev": raw_exposure_ev,
            "conversion_format": conversion_format,
            "conversion_output_dir": conversion_output_dir,
            "video_enabled": video_enabled,
            "video_fps": video_fps,
            "video_slowdown": video_slowdown,
            "image_resolution": image_resolution,
            "video_resolution": video_resolution,
            "quality": quality,
            "image_format": image_format,
            "video_format": video_format,
            "video_hyperlapse": video_hyperlapse,
            "save_frames": save_frames,
            "no_stack": no_stack,
            "use_checkpoint": use_checkpoint,
            "resume": resume,
            "compute_backend": compute_backend,
            "cpu_workers": cpu_workers,
        }
        return execute_stack_pipeline(
            input_dir=input_dir,
            output_file=output_file,
            settings=settings,
            evaluate_output=evaluate_output,
            generate_preview_jpeg=generate_preview_jpeg,
        )

    @mcp.tool()
    def auto_tune_and_stack(
        input_dir: str,
        output_file: Optional[str] = None,
        goal: Literal[
            "balanced",
            "natural",
            "dramatic_extended",
            "gap_repair",
            "maximum_sharpness",
            "trail_lapse_video",
            "faint_stars_boost",
        ] = "balanced",
        video_export: bool = False,
        verify_and_refine: bool = True,
        conversion_format: Literal["none", "jpg", "tiff"] = "none",
        conversion_output_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Autonomous end-to-end tool that:
        1. Inspects the sequence and runs `recommend_settings` for `goal`.
        2. Benchmarks candidate alignment strategies if the initial Pass 1 probe score is < 80.
        3. Renders the full stack.
        4. Evaluates the output stack quality (`evaluate_stack_quality`).
        5. If `verify_and_refine=True` and quality evaluation detects avoidable trail beading/gaps
           or clipping, automatically refines the parameters and re-renders for a superior stack.
        """
        rec = recommend_stack_settings(
            input_dir=input_dir,
            goal=goal,
            include_pass1_probe=True,
            video_export=video_export,
        )
        chosen_settings = dict(rec["recommended_settings"])
        chosen_settings["conversion_format"] = conversion_format
        chosen_settings["conversion_output_dir"] = conversion_output_dir
        if output_file is not None:
            chosen_settings["output_file"] = str(Path(output_file).expanduser().resolve())

        probe = rec.get("pass1_probe")
        comparison_used: Optional[Dict[str, Any]] = None
        if probe is None or float(probe.get("alignment_score", 0.0)) < 80.0:
            comp = compare_alignment_candidates_data(input_dir=input_dir, max_frames=30)
            comparison_used = {
                "best_candidate": comp["best_candidate"],
                "best_alignment_score": comp["best_alignment_score"],
            }
            if comp["best_settings"]:
                for k, v in comp["best_settings"].items():
                    chosen_settings[k] = v

        initial_run = execute_stack_pipeline(
            input_dir=input_dir,
            output_file=chosen_settings.get("output_file"),
            settings=chosen_settings,
            evaluate_output=True,
            generate_preview_jpeg=True,
        )

        refinement_applied = False
        refinement_reason: Optional[str] = None
        final_run = initial_run

        if verify_and_refine and initial_run.get("quality_report") and goal != "maximum_sharpness":
            q = initial_run["quality_report"]
            t_metrics = q.get("trail_metrics", {})
            continuity = float(t_metrics.get("trail_continuity_score", 1.0))
            clipping = float(t_metrics.get("clipping_fraction", 0.0))

            refined_settings = dict(chosen_settings)
            if clipping > 0.05 and refined_settings.get("blend_mode") == "add":
                refined_settings["blend_mode"] = "lighten"
                refinement_applied = True
                refinement_reason = (
                    f"Switched blend_mode from 'add' to 'lighten' due to {clipping * 100:.1f}% highlight clipping."
                )
            elif (
                continuity < 0.45
                and int(t_metrics.get("trail_component_count", 0)) >= 10
                and not refined_settings.get("fill_gaps")
                and float(refined_settings.get("extension_factor", 1.0)) <= 1.0
            ):
                refined_settings["fill_gaps"] = True
                refined_settings["extension_factor"] = 1.3
                refined_settings["ghost_frames_per_real"] = max(
                    12, int(refined_settings.get("ghost_frames_per_real", 10))
                )
                refined_settings["use_foreground_mask"] = True
                refinement_applied = True
                refinement_reason = (
                    f"Detected beaded trails (continuity_score={continuity:.2f}); enabled fill_gaps=True "
                    "and extension_factor=1.3 with ghost_frames_per_real=12 to bridge inter-exposure gaps."
                )

            if refinement_applied:
                cand_run = execute_stack_pipeline(
                    input_dir=input_dir,
                    output_file=refined_settings.get("output_file"),
                    settings=refined_settings,
                    evaluate_output=True,
                    generate_preview_jpeg=True,
                )
                cand_score = float(cand_run.get("quality_report", {}).get("overall_quality_score", 0.0))
                init_score = float(q.get("overall_quality_score", 0.0))
                if cand_score >= init_score:
                    final_run = cand_run
                    chosen_settings = refined_settings

        return {
            "goal": goal,
            "final_settings_used": chosen_settings,
            "recommendation_rationale": rec["rationale"],
            "candidate_comparison": comparison_used,
            "refinement_applied": refinement_applied,
            "refinement_reason": refinement_reason,
            "stack_result": final_run,
        }

    @mcp.tool()
    def evaluate_stack_quality(
        stack_path: str,
        reference_frame_path: Optional[str] = None,
        preview_output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Analyze an existing stack image (`.tiff`, `.tif`, `.png`, `.jpg`) and compute
        objective quality metrics:
        - Brightness distribution and dynamic range (dB)
        - Highlight clipping fraction
        - Sky trail coverage fraction
        - Trail continuity score (smooth continuous arcs vs beaded/gapped dots)
        - Foreground sharpness retention (when `reference_frame_path` is provided)
        - Overall quality score (0–100), verdict, and actionable `tuning_suggestions`.
        """
        return evaluate_stack_image(
            stack_path=stack_path,
            reference_frame_path=reference_frame_path,
            preview_output_path=preview_output_path,
        )

    @mcp.tool()
    def render_annotated_preview(
        image_path: str,
        output_path: Optional[str] = None,
        max_size: int = 1600,
        annotate_stars: bool = False,
        polaris_x: Optional[float] = None,
        polaris_y: Optional[float] = None,
        star2_x: Optional[float] = None,
        star2_y: Optional[float] = None,
        rotation_center_x: Optional[float] = None,
        rotation_center_y: Optional[float] = None,
        show_foreground_mask: bool = False,
        raw_noise_reduction: bool = True,
        raw_exposure_ev: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Render any source frame (including RAW `.ARW`/`.CR2`/`.NEF`/`.DNG` or 16-bit TIFF)
        or output stack to an 8-bit JPEG preview, with optional visual overlays for
        detected stars, manual reference stars, celestial pole (`rotation_center`),
        and `foreground_mask` segmentation boundary.
        """
        polaris = (polaris_x, polaris_y) if polaris_x is not None and polaris_y is not None else None
        second_star = (star2_x, star2_y) if star2_x is not None and star2_y is not None else None
        rot_center = (
            (rotation_center_x, rotation_center_y)
            if rotation_center_x is not None and rotation_center_y is not None
            else None
        )
        return render_annotated_preview_image(
            image_path=image_path,
            output_path=output_path,
            max_size=max_size,
            annotate_stars=annotate_stars,
            polaris=polaris,
            second_star=second_star,
            rotation_center=rot_center,
            show_foreground_mask=show_foreground_mask,
            raw_noise_reduction=raw_noise_reduction,
            raw_exposure_ev=raw_exposure_ev,
        )

    # =========================================================================
    # ASYNCHRONOUS BACKGROUND JOB MANAGEMENT TOOLS
    # =========================================================================

    @mcp.tool()
    def start_stack_job(
        input_dir: str,
        output_file: Optional[str] = None,
        polaris_x: Optional[float] = None,
        polaris_y: Optional[float] = None,
        star2_x: Optional[float] = None,
        star2_y: Optional[float] = None,
        use_rotation: bool = False,
        use_kalman: bool = True,
        kalman_process_noise: float = 0.01,
        kalman_measurement_noise: float = 2.0,
        extension_factor: float = 1.0,
        tail_taper_strength: float = 0.0,
        tail_angle_threshold: float = 0.0,
        ghost_frames_per_real: int = 10,
        synthetic_fade_factor: float = 0.2,
        use_foreground_mask: bool = True,
        fill_gaps: bool = False,
        blend_mode: Literal["lighten", "add"] = "lighten",
        sort_by_time: bool = True,
        raw_noise_reduction: bool = True,
        raw_exposure_ev: float = 0.0,
        conversion_format: Literal["none", "jpg", "tiff"] = "none",
        conversion_output_dir: Optional[str] = None,
        video_enabled: bool = False,
        video_fps: int = 30,
        video_slowdown: Literal[1, 2, 4, 8] = 1,
        image_resolution: Literal["source", "4k", "2k", "1080p", "720p"] = "source",
        video_resolution: Literal["source", "4k", "2k", "1080p", "720p"] = "source",
        quality: Literal["high", "prores", "lossless", "medium", "hevc"] = "high",
        image_format: Literal["tiff", "png", "jpg"] = "tiff",
        video_format: Literal["auto", "mp4", "mov"] = "auto",
        video_hyperlapse: bool = False,
        save_frames: bool = False,
        no_stack: bool = False,
        compute_backend: Literal["auto", "cpu", "opencl"] = "auto",
        cpu_workers: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Launch a background alignment and stacking job via `JobManager` and return
        its `job_id` immediately. Poll progress with `get_job_status(job_id)` or
        cancel with `cancel_job(job_id)`.
        """
        folder = Path(input_dir).expanduser().resolve()
        if not folder.exists() or not folder.is_dir():
            raise ValueError(f"Input directory does not exist: {input_dir}")

        out_path = (
            str(Path(output_file).expanduser().resolve())
            if output_file
            else str(folder / "aligned_output.tiff")
        )
        config: Dict[str, Any] = {
            "input_dir": str(folder),
            "output_file": out_path,
            "extension_factor": extension_factor,
            "tail_taper_strength": tail_taper_strength,
            "tail_angle_threshold": tail_angle_threshold,
            "use_rotation": use_rotation,
            "use_kalman": use_kalman,
            "kalman_process_noise": kalman_process_noise,
            "kalman_measurement_noise": kalman_measurement_noise,
            "ghost_frames_per_real": ghost_frames_per_real,
            "synthetic_fade_factor": synthetic_fade_factor,
            "use_foreground_mask": use_foreground_mask,
            "fill_gaps": fill_gaps,
            "video_enabled": video_enabled,
            "video_fps": video_fps,
            "video_slowdown": video_slowdown,
            "image_resolution": image_resolution,
            "video_resolution": video_resolution,
            "quality": quality,
            "image_format": image_format,
            "video_format": video_format,
            "video_hyperlapse": video_hyperlapse,
            "sort_by_time": sort_by_time,
            "blend_mode": blend_mode,
            "compute_backend": compute_backend,
            "cpu_workers": cpu_workers,
            "raw_noise_reduction": raw_noise_reduction,
            "raw_exposure_ev": raw_exposure_ev,
            "conversion_format": conversion_format,
            "conversion_output_dir": conversion_output_dir,
        }
        if polaris_x is not None and polaris_y is not None:
            config["polaris"] = (float(polaris_x), float(polaris_y))
        if star2_x is not None and star2_y is not None:
            config["second_star"] = (float(star2_x), float(star2_y))

        from backend.api.router import JobCreateRequest
        config.update(save_frames=save_frames, no_stack=no_stack)
        try:
            JobCreateRequest(**config)
        except ValueError as exc:
            from mcp.server.mcpserver.exceptions import ToolError
            raise ToolError(str(exc)) from exc
        job_id = job_manager.create_job(config, kind="alignment")
        job_manager.start_job(job_id)
        return {
            "job_id": job_id,
            "status": "running",
            "output_file": out_path,
        }

    @mcp.tool()
    def get_job_status(job_id: str) -> Dict[str, Any]:
        """
        Retrieve the live status, stage, progress (0.0–1.0), drift telemetry, and
        result path of a background job launched via `start_stack_job` or the REST API.
        """
        try:
            return job_manager.get_job(job_id)
        except KeyError as exc:
            raise ValueError(f"Job not found: {job_id}") from exc

    @mcp.tool()
    def cancel_job(job_id: str) -> Dict[str, Any]:
        """
        Cancel a running or queued background job by `job_id`.
        """
        try:
            return job_manager.cancel_job(job_id)
        except KeyError as exc:
            raise ValueError(f"Job not found: {job_id}") from exc

    @mcp.tool()
    def list_jobs() -> Dict[str, Any]:
        """
        List all jobs tracked by the `JobManager` in this process.
        """
        with job_manager._lock:
            jobs = [dict(j) for j in job_manager.jobs.values()]
        return {"count": len(jobs), "jobs": jobs}

    # =========================================================================
    # MCP RESOURCES
    # =========================================================================

    @mcp.resource("staraligner://system/capabilities")
    def resource_system_capabilities() -> str:
        """Hardware compute capabilities (CPU count, RAM, OpenCL GPUs)."""
        return json.dumps(system_capabilities(), indent=2)

    @mcp.resource("staraligner://config/defaults")
    def resource_config_defaults() -> str:
        """Default configuration constants and parameter ranges for PullStar."""
        defaults = {
            "tracking": {
                "SEARCH_WINDOW_SIZE": getattr(app_config, "SEARCH_WINDOW_SIZE", 100),
                "MAX_JUMP_THRESHOLD": getattr(app_config, "MAX_JUMP_THRESHOLD", 50.0),
                "STAR_THRESHOLD_PERCENTILE": getattr(app_config, "STAR_THRESHOLD_PERCENTILE", 99.5),
                "MIN_BLOB_AREA": getattr(app_config, "MIN_BLOB_AREA", 5),
                "MAX_BLOB_AREA": getattr(app_config, "MAX_BLOB_AREA", 500),
                "USE_KALMAN_FILTER": getattr(app_config, "USE_KALMAN_FILTER", True),
                "KALMAN_PROCESS_NOISE": getattr(app_config, "KALMAN_PROCESS_NOISE", 0.01),
                "KALMAN_MEASUREMENT_NOISE": getattr(app_config, "KALMAN_MEASUREMENT_NOISE", 2.0),
            },
            "stacking": {
                "DEFAULT_BLEND_MODE": getattr(app_config, "DEFAULT_BLEND_MODE", "lighten"),
                "SUPPORTED_BLEND_MODES": ["lighten", "add"],
                "DEFAULT_EXTENSION_FACTOR": getattr(app_config, "DEFAULT_EXTENSION_FACTOR", 1.0),
                "MAX_EXTENSION_FACTOR": getattr(app_config, "MAX_EXTENSION_FACTOR", 5.0),
                "GHOST_FRAMES_PER_REAL": getattr(app_config, "GHOST_FRAMES_PER_REAL", 10),
                "SYNTHETIC_FADE_FACTOR": getattr(app_config, "SYNTHETIC_FADE_FACTOR", 0.2),
                "USE_FOREGROUND_MASK": getattr(app_config, "USE_FOREGROUND_MASK", True),
            },
            "video": {
                "VIDEO_FPS": getattr(app_config, "VIDEO_FPS", 30),
                "SUPPORTED_QUALITIES": ["high", "prores", "lossless", "medium", "web"],
            },
            "supported_extensions": sorted(getattr(app_config, "ALL_SUPPORTED_EXTENSIONS", [])),
        }
        return json.dumps(defaults, indent=2)

    @mcp.resource("staraligner://guide/parameter-tuning")
    def resource_parameter_tuning_guide() -> str:
        """Expert parameter tuning guide for AI agents creating star trail stacks."""
        return """# PullStar — Parameter Tuning Playbook for AI Agents

## 1. Choosing the Alignment Mode (`polaris_x`/`polaris_y` vs `None`)
- **Automatic Stellar Field Mode (`polaris_x=None, polaris_y=None`) — Recommended Default**:
  - Uses `photutils.DAOStarFinder` + `astroalign` triangle matching across up to 100 stars per frame.
  - Fits a smooth sky trajectory and removes only **camera wobble/shake** while preserving natural sky trail rotation and framing.
  - **Essential when the celestial pole (Polaris / Octans) is outside the frame** or when you want a wide common crop without translating the image across the canvas.
- **Manual Reference Star Mode (`polaris_x, polaris_y`, optional `star2_x, star2_y`)**:
  - Tracks a single star (translation only) or two stars (`use_rotation=True`) using sub-pixel moments + `KalmanCentroidTracker`.
  - Best when fewer than 6 stars are visible across the frame (e.g., heavy light pollution or clouds) so triangle matching cannot lock on.
  - When using manual mode on windy nights, keep `use_kalman=True` and increase `kalman_measurement_noise` (e.g., `3.0–5.0`) to smooth jitter, or increase `search_window_size` (e.g., `140–200`) and `max_jump_threshold` (e.g., `80.0`) if the tripod was bumped.

## 2. Fixing Gaps or Beaded Star Trails (`fill_gaps`, `extension_factor`, `ghost_frames_per_real`)
- **Timeline Gaps (`fill_gaps=True`)**:
  - When `inspect_sequence` reports `gap_detected=True` (exposures dropped due to battery swap, intervalometer pause, or passing clouds), enable `fill_gaps=True` so missing arcs are synthesized along the fitted sky motion trajectory.
- **Beaded Trails (Short Exposures / Long Interval Delays)**:
  - If individual exposures have gaps between them causing dotted/beaded trails (`trail_continuity_score < 0.45`), either enable `fill_gaps=True` or set `extension_factor` to `1.2–2.0` with `ghost_frames_per_real=10–15` and `synthetic_fade_factor=0.15`.
- **Dramatic Sweeping Arcs (`extension_factor > 1.0`)**:
  - For short capture sessions (<15 minutes), set `extension_factor` between `1.5` and `3.0` to extrapolate trails forward along the celestial rotation trajectory.

## 3. Preserving Foreground Landscapes (`use_foreground_mask`)
- Whenever `extension_factor > 1.0` or `fill_gaps=True` is used on a scene containing ground, trees, mountains, or buildings (`foreground_fraction >= 0.03`), keep `use_foreground_mask=True` so synthetic rotation only rotates the sky mask and keeps the landscape sharp.

## 4. Exposure, RAW Development & Blending (`blend_mode`, `raw_exposure_ev`, `raw_noise_reduction`)
- **`blend_mode="lighten"` (Default)**:
  - Computes per-pixel maximum across aligned frames. Prevents skyglow buildup and highlight clipping while recording peak star trails.
- **`blend_mode="add"`**:
  - Sums pixel values across frames. Only use for very short, ultra-dim sequences; monitor `clipping_fraction` in `evaluate_stack_quality`.
- **RAW Controls (`raw_exposure_ev`, `raw_noise_reduction`)**:
  - For dark RAW sequences (`.ARW`, `.CR2`, `.NEF`, `.DNG`), set `raw_exposure_ev` between `0.5` and `2.0` EV and keep `raw_noise_reduction=True`.
"""

    @mcp.resource("staraligner://jobs/active")
    def resource_active_jobs() -> str:
        """Current background jobs tracked by JobManager."""
        with job_manager._lock:
            jobs = [dict(j) for j in job_manager.jobs.values()]
        return json.dumps({"count": len(jobs), "jobs": jobs}, indent=2)

    # =========================================================================
    # MCP PROMPTS
    # =========================================================================

    @mcp.prompt()
    def find_optimal_stack_settings(input_dir: str, goal: str = "balanced") -> str:
        """
        Step-by-step workflow prompt guiding an agent to discover and validate
        the optimal alignment and stacking settings for `input_dir`.
        """
        return (
            f"Find the optimal PullStar settings for the sequence in `{input_dir}` "
            f"with creative goal `{goal}`:\n\n"
            f"1. Call `inspect_sequence(input_dir={input_dir!r})` to examine image count, dimensions, "
            "RAW/bit-depth status, EXIF timestamp gaps, foreground ratio, and sampled star counts.\n"
            f"2. Call `recommend_settings(input_dir={input_dir!r}, goal={goal!r}, include_pass1_probe=True)` "
            "to obtain the recommended configuration, rationale, and Pass 1 alignment probe score.\n"
            f"3. If the Pass 1 probe `alignment_score` is below 85 or you want to verify whether automatic "
            f"`star_field` vs `manual_tracking` is better, call `compare_alignment_candidates(input_dir={input_dir!r})`.\n"
            f"4. Optionally call `render_preview_stack(input_dir={input_dir!r}, ...)` with the winning parameters "
            "to verify `overall_quality_score`, `trail_continuity_score`, and `clipping_fraction` before full rendering.\n"
            "5. Summarize the chosen parameters and why each setting is optimal for this dataset."
        )

    @mcp.prompt()
    def create_verified_stack_workflow(
        input_dir: str,
        output_file: str = "",
        goal: str = "balanced",
    ) -> str:
        """
        End-to-end workflow prompt guiding an agent to inspect, tune, stack,
        and verify a final star trail image.
        """
        out_arg = f", output_file={output_file!r}" if output_file else ""
        return (
            f"Create and verify a high-quality star trail stack from `{input_dir}` (goal=`{goal}`):\n\n"
            f"1. Call `recommend_settings(input_dir={input_dir!r}, goal={goal!r})` to analyze the sequence "
            "and determine the best alignment mode, gap filling, foreground mask, and trail synthesis settings.\n"
            f"2. Call `create_stack(input_dir={input_dir!r}{out_arg}, ...)` using the recommended settings "
            "(or call `auto_tune_and_stack` to perform closed-loop tuning and refinement automatically).\n"
            "3. Inspect the returned `quality_report` (`overall_quality_score`, `verdict`, `trail_continuity_score`, "
            "`clipping_fraction`, and `tuning_suggestions`).\n"
            "4. If `verdict` is `needs_tuning` or `poor`, apply the `tuning_suggestions` and re-run `create_stack`.\n"
            "5. Report the final output TIFF path, preview JPEG path, alignment metrics, and quality score."
        )

    return mcp


mcp = create_mcp_server()


def main(argv: Optional[List[str]] = None) -> None:
    """CLI entrypoint for running the PullStar MCP Server."""
    parser = argparse.ArgumentParser(
        prog="star-aligner-mcp",
        description="PullStar Model Context Protocol (MCP) Server",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="MCP transport protocol to use (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host address when using sse or streamable-http transport (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port when using sse or streamable-http transport (default: 8765)",
    )
    args = parser.parse_args(argv)

    if args.transport == "stdio":
        # The SDK redirects descriptor 1 while serving. Flush each print before
        # it restores stdout so buffered processing logs cannot reach the wire.
        import sys
        sys.stdout.reconfigure(line_buffering=True, write_through=True)
        mcp.run(transport="stdio")
    else:
        import uvicorn

        app = (
            mcp.streamable_http_app()
            if args.transport == "streamable-http"
            else mcp.sse_app()
        )
        uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
