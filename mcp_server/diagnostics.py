"""
Star Trail Aligner - MCP Diagnostics, Settings Optimization & Quality Assessment Engine.

Provides deterministic analysis routines used by the MCP server tools to:
1. Inspect image sequences (dimensions, RAW/bit-depth, EXIF timeline gaps, photometry, foreground coverage).
2. Detect and analyze star fields (automatic multi-star rigid matching vs manual reference star candidates).
3. Run fast Pass 1 alignment dry-runs and side-by-side candidate comparisons.
4. Recommend optimal stacking settings tailored to sequence characteristics and user goals.
5. Render fast preview stacks and evaluate final stack image quality (trail continuity, clipping, contrast, foreground sharpness).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, List, Optional, Sequence, Tuple
import math
import os
import time

import cv2
import numpy as np

from backend.engine.alignment_engine import AlignmentEngine
from backend.engine.field_alignment import analyze_field, field_crop
from backend.engine.pipeline import pass1_analysis
from config import (
    DEFAULT_BLEND_MODE,
    KALMAN_MEASUREMENT_NOISE,
    KALMAN_PROCESS_NOISE,
    MAX_BLOB_AREA,
    MAX_JUMP_THRESHOLD,
    MIN_BLOB_AREA,
    SEARCH_WINDOW_SIZE,
    STAR_THRESHOLD_PERCENTILE,
)
from core.compute import configure_native_threads, system_capabilities, worker_count
from core.validator import validate_image_consistency, validate_inputs
from modules.astronomy import detect_sources
from modules.auto_selector import auto_detect_stars
from modules.gui import StarSelection
from modules.io_utils import (
    get_exif_datetime,
    get_image_info,
    get_image_list,
    load_image,
    save_tiff,
)
from modules.tracker import get_tracking_summary
from modules.transform import (
    TransformData,
    calculate_common_crop,
    get_transform_statistics,
)
from synthesis.foreground_mask import detect_horizon_line, segment_sky_ground

KNOWN_OUTPUT_PREFIXES = (
    "aligned_star_trails",
    "aligned_output",
    "mcp_stack",
    "mcp_preview",
    "preview_",
)
VIDEO_SUFFIXES = (".mp4", ".mov", ".avi", ".mkv", ".webm")


def filter_source_images(
    input_dir: str | Path,
    sort_by_time: bool = True,
    exclude_paths: Optional[Sequence[str | Path]] = None,
) -> Tuple[List[Path], List[str]]:
    """
    Return the ordered list of source exposure files in `input_dir`, excluding
    previously generated stack outputs, previews, or video files.
    """
    folder = Path(input_dir).expanduser().resolve()
    if not folder.exists() or not folder.is_dir():
        raise ValueError(f"Input directory does not exist: {input_dir}")

    raw_paths = get_image_list(folder, sort_by_time=sort_by_time)
    excluded_resolved = set()
    if exclude_paths:
        for p in exclude_paths:
            if p:
                try:
                    excluded_resolved.add(Path(p).expanduser().resolve())
                except OSError:
                    pass

    filtered: List[Path] = []
    skipped_names: List[str] = []
    for path in raw_paths:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path

        stem_lower = path.stem.lower()
        suffix_lower = path.suffix.lower()
        if (
            resolved in excluded_resolved
            or suffix_lower in VIDEO_SUFFIXES
            or any(stem_lower.startswith(prefix) for prefix in KNOWN_OUTPUT_PREFIXES)
            or stem_lower.endswith("_preview")
            or stem_lower.endswith("_annotated")
        ):
            skipped_names.append(path.name)
            continue
        filtered.append(path)

    # Also guard against a stray differently-sized TIFF output sitting in the input folder
    if len(filtered) >= 3:
        dims_by_path: List[Tuple[Path, Tuple[int, int], str]] = []
        dim_counts: Dict[Tuple[int, int], int] = {}
        for p in filtered:
            try:
                info = get_image_info(p)
                dim = (int(info["width"]), int(info["height"]))
                dims_by_path.append((p, dim, p.suffix.lower()))
                dim_counts[dim] = dim_counts.get(dim, 0) + 1
            except Exception:
                dims_by_path.append((p, (0, 0), p.suffix.lower()))

        if dim_counts:
            dominant_dim = max(dim_counts.items(), key=lambda item: item[1])[0]
            if dim_counts[dominant_dim] >= 2:
                consistent_filtered: List[Path] = []
                for p, dim, sfx in dims_by_path:
                    if dim != dominant_dim and sfx in (".tif", ".tiff") and dim_counts.get(dim, 0) == 1:
                        skipped_names.append(p.name)
                    else:
                        consistent_filtered.append(p)
                filtered = consistent_filtered

    if not filtered:
        raise ValueError(f"No valid source images found in {input_dir}")

    return filtered, skipped_names


def _to_uint8_bgr(image: np.ndarray) -> np.ndarray:
    """Normalize an image array (uint8, uint16, or float) to 8-bit BGR for preview/masking."""
    if image.dtype == np.uint16:
        out = np.clip(image.astype(np.float32) / 257.0, 0, 255).astype(np.uint8)
    elif np.issubdtype(image.dtype, np.floating):
        max_val = float(np.max(image)) if image.size else 1.0
        if max_val > 255.0:
            out = np.clip(image / 257.0, 0, 255).astype(np.uint8)
        elif max_val <= 1.0 and max_val > 0.0:
            out = np.clip(image * 255.0, 0, 255).astype(np.uint8)
        else:
            out = np.clip(image, 0, 255).astype(np.uint8)
    else:
        out = image.astype(np.uint8)

    if out.ndim == 2:
        return cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)
    if out.shape[2] == 4:
        return cv2.cvtColor(out, cv2.COLOR_BGRA2BGR)
    return out


def _sample_star_flux(gray: np.ndarray, x: float, y: float, radius: int = 3) -> float:
    """Measure local peak intensity around (x, y) in a grayscale image."""
    h, w = gray.shape[:2]
    ix = int(round(x))
    iy = int(round(y))
    x0 = max(0, ix - radius)
    x1 = min(w, ix + radius + 1)
    y0 = max(0, iy - radius)
    y1 = min(h, iy + radius + 1)
    patch = gray[y0:y1, x0:x1]
    return float(np.max(patch)) if patch.size else 0.0


def _analyze_timeline(image_paths: Sequence[Path]) -> Dict[str, Any]:
    """Extract EXIF timestamps, exposure intervals, total duration, and timeline gaps."""
    raw_timestamps: List[Optional[datetime]] = [get_exif_datetime(p) for p in image_paths]
    exif_count = sum(1 for ts in raw_timestamps if ts is not None)
    has_exif = exif_count >= max(2, len(image_paths) // 2)

    resolved_timestamps: List[datetime] = []
    for p, ts in zip(image_paths, raw_timestamps):
        if ts is not None:
            resolved_timestamps.append(ts)
        else:
            try:
                resolved_timestamps.append(datetime.fromtimestamp(p.stat().st_mtime))
            except OSError:
                resolved_timestamps.append(datetime.fromtimestamp(0))

    deltas: List[float] = []
    for i in range(1, len(resolved_timestamps)):
        dt = (resolved_timestamps[i] - resolved_timestamps[i - 1]).total_seconds()
        if dt > 0:
            deltas.append(float(dt))

    median_interval = float(np.median(deltas)) if deltas else 0.0
    min_interval = float(np.min(deltas)) if deltas else 0.0
    max_interval = float(np.max(deltas)) if deltas else 0.0
    total_duration = (
        float((resolved_timestamps[-1] - resolved_timestamps[0]).total_seconds())
        if len(resolved_timestamps) >= 2
        else 0.0
    )

    gaps: List[Dict[str, Any]] = []
    if median_interval > 0:
        for i in range(1, len(resolved_timestamps)):
            dt = (resolved_timestamps[i] - resolved_timestamps[i - 1]).total_seconds()
            if dt > median_interval * 1.5 and (dt - median_interval) >= 2.0:
                missing_est = max(1, int(round(dt / median_interval)) - 1)
                gaps.append(
                    {
                        "frame_index": i,
                        "prev_filename": image_paths[i - 1].name,
                        "filename": image_paths[i].name,
                        "delta_seconds": round(float(dt), 2),
                        "expected_seconds": round(median_interval, 2),
                        "estimated_missing_frames": missing_est,
                    }
                )

    earth_rate_deg_per_sec = 360.0 / 86164.0905
    estimated_rotation_deg = (
        round(total_duration * earth_rate_deg_per_sec, 3) if total_duration > 0 else None
    )

    by_name = sorted(image_paths, key=lambda p: p.name.lower())
    order_differs_from_filename = [p.name for p in image_paths] != [p.name for p in by_name]

    return {
        "has_exif_timestamps": has_exif,
        "exif_timestamp_count": exif_count,
        "median_interval_seconds": round(median_interval, 3),
        "min_interval_seconds": round(min_interval, 3),
        "max_interval_seconds": round(max_interval, 3),
        "total_duration_seconds": round(total_duration, 2),
        "estimated_sidereal_rotation_deg": estimated_rotation_deg,
        "gap_detected": len(gaps) > 0,
        "gap_count": len(gaps),
        "total_missing_frames_estimate": sum(g["estimated_missing_frames"] for g in gaps),
        "gaps": gaps[:25],
        "time_order_differs_from_filename": order_differs_from_filename,
    }


def _extract_manual_star_candidates(
    image: np.ndarray,
    max_candidates: int = 8,
    reference_point: Optional[Tuple[float, float]] = None,
) -> List[Dict[str, Any]]:
    """
    Find bright, well-isolated stars in the image suitable for manual tracking
    (`polaris` and `second_star`).
    """
    h, w = image.shape[:2]
    coords = detect_sources(image, max_stars=80)
    if len(coords) == 0:
        return []

    u8 = _to_uint8_bgr(image)
    gray = cv2.cvtColor(u8, cv2.COLOR_BGR2GRAY).astype(np.float32)
    fluxes = np.array([_sample_star_flux(gray, float(pt[0]), float(pt[1])) for pt in coords], dtype=np.float32)

    margin_x = max(16.0, w * 0.06)
    margin_y = max(16.0, h * 0.06)
    max_flux = float(np.max(fluxes)) if len(fluxes) else 1.0

    candidates: List[Dict[str, Any]] = []
    for idx, ((x, y), flux) in enumerate(zip(coords, fluxes)):
        fx, fy = float(x), float(y)
        in_safe_interior = (margin_x <= fx <= (w - margin_x)) and (margin_y <= fy <= (h - margin_y))
        if len(coords) > 1:
            dists = np.hypot(coords[:, 0] - fx, coords[:, 1] - fy)
            dists[idx] = np.inf
            nearest_neighbor_px = float(np.min(dists))
        else:
            nearest_neighbor_px = float(min(w, h))

        dist_to_ref = (
            float(math.hypot(fx - reference_point[0], fy - reference_point[1]))
            if reference_point is not None
            else float(math.hypot(fx - w / 2.0, fy - h / 2.0))
        )
        flux_ratio = float(flux) / max(max_flux, 1e-6)
        isolation_score = min(1.0, nearest_neighbor_px / 25.0)
        interior_bonus = 1.0 if in_safe_interior else 0.4
        suitability = round((0.55 * flux_ratio + 0.45 * isolation_score) * interior_bonus, 4)

        candidates.append(
            {
                "rank": idx + 1,
                "x": round(fx, 2),
                "y": round(fy, 2),
                "flux": round(float(flux), 2),
                "flux_ratio": round(flux_ratio, 4),
                "nearest_neighbor_px": round(nearest_neighbor_px, 2),
                "distance_to_reference_px": round(dist_to_ref, 2),
                "in_safe_interior": bool(in_safe_interior),
                "suitability_score": suitability,
            }
        )

    candidates.sort(key=lambda c: (-c["suitability_score"], c["distance_to_reference_px"]))
    for i, c in enumerate(candidates[:max_candidates]):
        c["rank"] = i + 1
    return candidates[:max_candidates]


def inspect_sequence_data(
    input_dir: str | Path,
    sort_by_time: bool = True,
    sample_frames: int = 5,
    raw_noise_reduction: bool = True,
) -> Dict[str, Any]:
    """
    Perform a comprehensive diagnostic inspection of an exposure sequence.
    """
    image_paths, skipped_outputs = filter_source_images(input_dir, sort_by_time=sort_by_time)
    num_images = len(image_paths)

    validation_errors, validation_warnings = validate_inputs(
        image_list=image_paths,
        extension_factor=1.0,
        output_path=Path(input_dir) / "aligned_output.tiff",
    )
    consistency_errors, consistency_warnings = validate_image_consistency(
        image_paths,
        check_timestamps=True,
    )

    first_info = get_image_info(image_paths[0])
    width = int(first_info["width"])
    height = int(first_info["height"])
    is_raw = bool(first_info["is_raw"])
    dtype = str(first_info["dtype"])
    recommended_bit_depth = 16 if (is_raw or dtype == "uint16") else 8

    timeline = _analyze_timeline(image_paths)

    sample_count = max(1, min(int(sample_frames), num_images))
    sample_indices = sorted(set(np.linspace(0, num_images - 1, num=sample_count, dtype=int).tolist()))

    sampled_frame_metrics: List[Dict[str, Any]] = []
    first_frame_img: Optional[np.ndarray] = None
    for idx in sample_indices:
        img = load_image(image_paths[idx], raw_noise_reduction=raw_noise_reduction)
        if first_frame_img is None:
            first_frame_img = img
        u8 = _to_uint8_bgr(img)
        gray = cv2.cvtColor(u8, cv2.COLOR_BGR2GRAY).astype(np.float32)
        coords = detect_sources(img, max_stars=100)
        top_flux = (
            _sample_star_flux(gray, float(coords[0][0]), float(coords[0][1]))
            if len(coords) > 0
            else 0.0
        )
        sampled_frame_metrics.append(
            {
                "frame_index": int(idx),
                "filename": image_paths[idx].name,
                "detected_stars": int(len(coords)),
                "mean_brightness_u8": round(float(np.mean(gray)), 2),
                "std_brightness_u8": round(float(np.std(gray)), 2),
                "p50_brightness_u8": round(float(np.percentile(gray, 50)), 2),
                "p99_5_brightness_u8": round(float(np.percentile(gray, 99.5)), 2),
                "max_brightness_u8": round(float(np.max(gray)), 2),
                "top_star_flux": round(float(top_flux), 2),
            }
        )

    assert first_frame_img is not None
    first_u8 = _to_uint8_bgr(first_frame_img)
    sky_mask = segment_sky_ground(first_u8, method="combined")
    sky_fraction = float(np.count_nonzero(sky_mask)) / float(sky_mask.size)
    foreground_fraction = 1.0 - sky_fraction
    horizon = detect_horizon_line(first_u8)

    star_counts = [m["detected_stars"] for m in sampled_frame_metrics]
    min_stars = min(star_counts) if star_counts else 0
    max_stars = max(star_counts) if star_counts else 0
    mean_stars = float(np.mean(star_counts)) if star_counts else 0.0

    manual_candidates = _extract_manual_star_candidates(first_frame_img, max_candidates=6)

    configure_native_threads()
    recommended_workers = worker_count(width, height, is_raw, None)
    caps = system_capabilities()

    scene_warnings: List[str] = list(validation_warnings) + list(consistency_warnings)
    if min_stars < 6:
        scene_warnings.append(
            f"Low star count detected in at least one sampled frame (min={min_stars}). "
            "If some exposures are cloudy or very dim, consider RAW exposure boost or Kalman tracking."
        )
    if timeline["gap_detected"]:
        scene_warnings.append(
            f"Detected {timeline['gap_count']} timeline gap(s) (~{timeline['total_missing_frames_estimate']} missing exposures). "
            "Enable fill_gaps=True to interpolate across missing exposures."
        )
    if timeline["time_order_differs_from_filename"]:
        scene_warnings.append(
            "EXIF chronological order differs from alphabetical filename order; keep sort_by_time=True."
        )

    return {
        "input_dir": str(Path(input_dir).expanduser().resolve()),
        "num_images": num_images,
        "skipped_non_source_files": skipped_outputs,
        "first_frame": image_paths[0].name,
        "last_frame": image_paths[-1].name,
        "extensions": sorted({p.suffix.lower() for p in image_paths}),
        "image_info": {
            "width": width,
            "height": height,
            "channels": int(first_info["channels"]),
            "dtype": dtype,
            "is_raw": is_raw,
            "recommended_output_bit_depth": recommended_bit_depth,
            "megapixels": round((width * height) / 1_000_000.0, 3),
        },
        "validation": {
            "is_valid": len(validation_errors) == 0 and len(consistency_errors) == 0,
            "errors": list(validation_errors) + list(consistency_errors),
            "warnings": scene_warnings,
        },
        "timeline": timeline,
        "scene_analysis": {
            "sampled_frames": sampled_frame_metrics,
            "star_count_summary": {
                "min": int(min_stars),
                "max": int(max_stars),
                "mean": round(mean_stars, 1),
            },
            "foreground_analysis": {
                "sky_fraction": round(sky_fraction, 4),
                "foreground_fraction": round(foreground_fraction, 4),
                "has_significant_foreground": bool(0.03 <= foreground_fraction <= 0.85),
                "detected_horizon_y": int(horizon[0]) if horizon is not None else None,
                "detected_horizon_angle_deg": round(float(horizon[1]), 2) if horizon is not None else None,
            },
            "manual_star_candidates": manual_candidates,
        },
        "compute": {
            "recommended_workers": recommended_workers,
            "gpu_available": len(caps.get("gpus", [])) > 0,
            "gpus": caps.get("gpus", []),
            "cpu_count": caps.get("cpu_count"),
            "memory_gb": caps.get("memory_gb"),
        },
    }


def analyze_star_field_data(
    input_dir: str | Path,
    frame_step: int = 10,
    sort_by_time: bool = True,
    raw_noise_reduction: bool = True,
    max_candidates: int = 8,
) -> Dict[str, Any]:
    """
    Run automatic star detection & multi-frame geometric matching, plus identify
    candidate reference stars (`polaris` and `second_star`) for manual tracking.
    """
    image_paths, _ = filter_source_images(input_dir, sort_by_time=sort_by_time)
    first_info = get_image_info(image_paths[0])
    width = int(first_info["width"])
    height = int(first_info["height"])

    configure_native_threads()
    workers = worker_count(width, height, bool(first_info["is_raw"]), None)

    auto_result = auto_detect_stars(
        image_paths,
        frame_step=max(1, int(frame_step)),
        workers=workers,
        raw_noise_reduction=raw_noise_reduction,
    )

    first_img = load_image(image_paths[0], raw_noise_reduction=raw_noise_reduction)
    rot_center: Optional[Tuple[float, float]] = None
    pole_in_frame = False
    pole_distance_from_center_px: Optional[float] = None
    auto_summary: Dict[str, Any]

    if auto_result is not None:
        if auto_result.rotation_center is not None:
            rx, ry = float(auto_result.rotation_center[0]), float(auto_result.rotation_center[1])
            rot_center = (round(rx, 2), round(ry, 2))
            pole_in_frame = (0.0 <= rx < width) and (0.0 <= ry < height)
            pole_distance_from_center_px = round(
                float(math.hypot(rx - width / 2.0, ry - height / 2.0)), 2
            )
        rot_angle = float(getattr(auto_result, "rotation_angle", 0.0))
        auto_summary = {
            "succeeded": True,
            "confidence": round(float(auto_result.confidence), 4),
            "num_inliers": int(auto_result.num_inliers),
            "rotation_angle_deg": round(rot_angle, 4),
            "rotation_center": rot_center,
            "pole_in_frame": pole_in_frame,
            "pole_distance_from_center_px": pole_distance_from_center_px,
            "selection_mode": auto_result.selection_mode,
            "method": auto_result.method,
            "reference_stars_count": len(auto_result.reference_stars),
            "reference_stars_sample": [
                [round(float(pt[0]), 2), round(float(pt[1]), 2)]
                for pt in auto_result.reference_stars[:15]
            ],
            "second_star": (
                [round(float(auto_result.second_star[0]), 2), round(float(auto_result.second_star[1]), 2)]
                if auto_result.second_star is not None
                else None
            ),
        }
    else:
        auto_summary = {
            "succeeded": False,
            "confidence": 0.0,
            "num_inliers": 0,
            "rotation_angle_deg": 0.0,
            "rotation_center": None,
            "pole_in_frame": False,
            "pole_distance_from_center_px": None,
            "selection_mode": None,
            "method": "failed",
            "reference_stars_count": 0,
            "reference_stars_sample": [],
            "second_star": None,
        }

    candidates = _extract_manual_star_candidates(
        first_img,
        max_candidates=max_candidates,
        reference_point=rot_center,
    )

    recommended_manual_polaris: Optional[Dict[str, float]] = None
    recommended_manual_second_star: Optional[Dict[str, float]] = None
    interior_candidates = [c for c in candidates if c["in_safe_interior"]] or candidates
    if interior_candidates:
        if pole_in_frame and rot_center is not None:
            primary = min(
                interior_candidates,
                key=lambda c: math.hypot(c["x"] - rot_center[0], c["y"] - rot_center[1]),
            )
        else:
            primary = interior_candidates[0]
        recommended_manual_polaris = {"x": primary["x"], "y": primary["y"]}

        if len(interior_candidates) >= 2:
            min_baseline = min(width, height) * 0.2
            far_candidates = [
                c
                for c in interior_candidates
                if math.hypot(c["x"] - primary["x"], c["y"] - primary["y"]) >= min_baseline
            ]
            secondary_pool = far_candidates if far_candidates else [c for c in interior_candidates if c is not primary]
            if secondary_pool:
                secondary = max(
                    secondary_pool,
                    key=lambda c: c["suitability_score"]
                    * math.hypot(c["x"] - primary["x"], c["y"] - primary["y"]),
                )
                recommended_manual_second_star = {"x": secondary["x"], "y": secondary["y"]}

    if auto_summary["succeeded"] and auto_summary["num_inliers"] >= 6 and auto_summary["confidence"] >= 0.45:
        recommended_alignment_mode = "star_field"
        mode_reason = (
            f"Automatic star-field matching succeeded with {auto_summary['num_inliers']} inlier stars "
            f"(confidence={auto_summary['confidence']:.2f}). "
            + (
                "The celestial rotation pole is outside the frame, where multi-star trajectory fitting "
                "is significantly more accurate than single-star tracking."
                if not pole_in_frame
                else "The celestial rotation pole is inside the frame and well-constrained by the star field."
            )
        )
    elif recommended_manual_polaris is not None:
        recommended_alignment_mode = "manual_tracking"
        mode_reason = (
            "Automatic multi-star triangle matching had low inliers/confidence, "
            "so manual centroid tracking with Kalman filtering on isolated bright reference stars is recommended."
        )
    else:
        recommended_alignment_mode = "star_field"
        mode_reason = "Defaulting to star_field alignment; consider increasing raw_exposure_ev if frames are underexposed."

    return {
        "input_dir": str(Path(input_dir).expanduser().resolve()),
        "num_images": len(image_paths),
        "dimensions": {"width": width, "height": height},
        "auto_field_detection": auto_summary,
        "manual_tracking_candidates": {
            "recommended_polaris": recommended_manual_polaris,
            "recommended_second_star": recommended_manual_second_star,
            "candidates": candidates,
        },
        "recommended_alignment_mode": recommended_alignment_mode,
        "recommendation_reason": mode_reason,
    }


def _compute_transform_jitter(transforms: Sequence[TransformData]) -> float:
    """
    Compute RMS second-difference (acceleration jitter) of frame-to-frame
    translations (`dx`, `dy`). Lower jitter indicates a smoother, more stable
    alignment trajectory.
    """
    if len(transforms) < 3:
        return 0.0
    dxs = np.array([float(t.dx) for t in transforms], dtype=np.float64)
    dys = np.array([float(t.dy) for t in transforms], dtype=np.float64)
    ddx = np.diff(dxs, n=2)
    ddy = np.diff(dys, n=2)
    return float(np.sqrt(np.mean(ddx * ddx + ddy * ddy)))


def evaluate_alignment_config(
    input_dir: str | Path,
    settings: Optional[Dict[str, Any]] = None,
    max_frames: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Run Pass 1 alignment analysis (dry-run without Pass 2 image rendering) for a
    given configuration and compute an objective Alignment Quality Report.
    """
    cfg = dict(settings or {})
    sort_by_time = bool(cfg.get("sort_by_time", True))
    raw_noise_reduction = bool(cfg.get("raw_noise_reduction", True))

    image_paths, _ = filter_source_images(input_dir, sort_by_time=sort_by_time)
    if max_frames is not None and int(max_frames) >= 2 and int(max_frames) < len(image_paths):
        indices = sorted(set(np.linspace(0, len(image_paths) - 1, num=int(max_frames), dtype=int).tolist()))
        eval_paths = [image_paths[i] for i in indices]
    else:
        eval_paths = image_paths

    first_info = get_image_info(eval_paths[0])
    width = int(first_info["width"])
    height = int(first_info["height"])
    is_raw = bool(first_info["is_raw"])

    configure_native_threads()
    workers = worker_count(width, height, is_raw, cfg.get("cpu_workers"))

    polaris = cfg.get("polaris")
    if polaris is None and cfg.get("polaris_x") is not None and cfg.get("polaris_y") is not None:
        polaris = (float(cfg["polaris_x"]), float(cfg["polaris_y"]))
    elif polaris is not None:
        polaris = (float(polaris[0]), float(polaris[1]))

    second_star = cfg.get("second_star")
    if second_star is None and cfg.get("star2_x") is not None and cfg.get("star2_y") is not None:
        second_star = (float(cfg["star2_x"]), float(cfg["star2_y"]))
    elif second_star is not None:
        second_star = (float(second_star[0]), float(second_star[1]))

    started = time.perf_counter()
    diagnostics: List[str] = []

    if polaris is None:
        mode = "star_field"
        analysis = analyze_field(
            eval_paths,
            workers=workers,
            raw_noise_reduction=raw_noise_reduction,
        )
        transforms = analysis.transforms
        crop = field_crop(transforms, width, height)
        valid_count = sum(1 for t in transforms if t.is_valid)
        skipped_count = len(analysis.skipped_frames)
        valid_ratio = float(valid_count) / max(1, len(eval_paths))
        inlier_counts = [f.num_matches for f in analysis.frames if f.is_valid]
        confidences = [f.confidence for f in analysis.frames if f.is_valid]
        mean_inliers = float(np.mean(inlier_counts)) if inlier_counts else 0.0
        min_inliers = int(np.min(inlier_counts)) if inlier_counts else 0
        mean_confidence = float(np.mean(confidences)) if confidences else 0.0

        sky_rotation_deg = math.degrees(float(analysis.angle_coefficients[1]))

        mode_details = {
            "reference_stars_detected": int(len(analysis.reference_stars)),
            "curved_trajectory_fit": bool(analysis.curved),
            "mean_inliers": round(mean_inliers, 2),
            "min_inliers": min_inliers,
            "mean_confidence": round(mean_confidence, 4),
            "skipped_frame_indices": list(analysis.skipped_frames),
            "modeled_sky_rotation_deg": round(sky_rotation_deg, 4),
        }
    else:
        mode = "manual_tracking"
        use_rotation = bool(cfg.get("use_rotation", second_star is not None))
        use_kalman = bool(cfg.get("use_kalman", True))
        kalman_process_noise = float(cfg.get("kalman_process_noise", KALMAN_PROCESS_NOISE))
        kalman_measurement_noise = float(cfg.get("kalman_measurement_noise", KALMAN_MEASUREMENT_NOISE))
        search_window_size = int(cfg.get("search_window_size", SEARCH_WINDOW_SIZE))
        max_jump_threshold = float(cfg.get("max_jump_threshold", MAX_JUMP_THRESHOLD))
        star_threshold_percentile = float(cfg.get("star_threshold_percentile", STAR_THRESHOLD_PERCENTILE))
        min_blob_area = int(cfg.get("min_blob_area", MIN_BLOB_AREA))
        max_blob_area = int(cfg.get("max_blob_area", MAX_BLOB_AREA))

        selection = StarSelection(polaris=polaris, second_star=second_star)
        tracking_results, transforms = pass1_analysis(
            eval_paths,
            selection,
            use_rotation=use_rotation,
            use_kalman=use_kalman,
            kalman_process_noise=kalman_process_noise,
            kalman_measurement_noise=kalman_measurement_noise,
            search_window_size=search_window_size,
            max_jump_threshold=max_jump_threshold,
            star_threshold_percentile=star_threshold_percentile,
            min_blob_area=min_blob_area,
            max_blob_area=max_blob_area,
            progress_callback=lambda *a, **kw: None,
            workers=workers,
        )
        crop = calculate_common_crop(transforms, width, height)
        summary = get_tracking_summary(tracking_results)
        valid_count = int(summary["successful_tracks"])
        skipped_count = int(summary["fallback_used"])
        valid_ratio = float(summary["success_rate"])
        confidences = [r.polaris.confidence for r in tracking_results]
        mean_confidence = float(np.mean(confidences)) if confidences else 0.0

        status_counts: Dict[str, int] = {}
        for r in tracking_results:
            key = r.polaris.status.value
            status_counts[key] = status_counts.get(key, 0) + 1

        mode_details = {
            "polaris": [round(polaris[0], 2), round(polaris[1], 2)],
            "second_star": [round(second_star[0], 2), round(second_star[1], 2)] if second_star else None,
            "use_rotation": use_rotation,
            "use_kalman": use_kalman,
            "kalman_process_noise": kalman_process_noise,
            "kalman_measurement_noise": kalman_measurement_noise,
            "search_window_size": search_window_size,
            "max_jump_threshold": max_jump_threshold,
            "star_threshold_percentile": star_threshold_percentile,
            "successful_tracks": valid_count,
            "fallback_frames": skipped_count,
            "mean_confidence": round(mean_confidence, 4),
            "status_breakdown": status_counts,
        }

    elapsed_sec = time.perf_counter() - started
    t_stats = get_transform_statistics(transforms)
    jitter_px = _compute_transform_jitter(transforms)

    area_retention = float(crop.width * crop.height) / max(1.0, float(width * height))
    width_retention = float(crop.width) / max(1.0, float(width))
    height_retention = float(crop.height) / max(1.0, float(height))

    score_valid = 45.0 * min(1.0, max(0.0, valid_ratio))
    score_crop = 25.0 * min(1.0, max(0.0, area_retention))
    score_conf = 20.0 * min(1.0, max(0.0, mean_confidence))
    score_smooth = 10.0 * max(0.0, 1.0 - min(1.0, jitter_px / 10.0))

    alignment_score = round(score_valid + score_crop + score_conf + score_smooth, 2)

    if valid_ratio < 0.8:
        diagnostics.append(
            f"Only {valid_ratio * 100:.1f}% of frames tracked cleanly without fallback/skipping."
        )
    if area_retention < 0.75:
        diagnostics.append(
            f"Common crop retains {area_retention * 100:.1f}% of original frame area due to large drift/rotation shifts. "
            + (
                "In manual mode, tracking a non-pole star translates the entire frame to freeze that star; "
                "switch to automatic star_field mode (polaris=None) to remove only camera wobble while preserving framing."
                if mode == "manual_tracking"
                else "Sequence has substantial camera motion between exposures."
            )
        )
    if jitter_px > 3.0:
        diagnostics.append(
            f"Frame-to-frame transform jitter is relatively high ({jitter_px:.2f}px RMS). "
            + (
                "Consider enabling use_kalman=True or increasing kalman_measurement_noise."
                if mode == "manual_tracking"
                else "Check for wind shake or cloud interference."
            )
        )
    if not diagnostics:
        diagnostics.append("Pass 1 alignment converged cleanly with high frame retention and smooth transforms.")

    if alignment_score >= 85.0:
        verdict = "excellent"
    elif alignment_score >= 70.0:
        verdict = "good"
    elif alignment_score >= 50.0:
        verdict = "marginal"
    else:
        verdict = "poor"

    return {
        "mode": mode,
        "alignment_score": alignment_score,
        "verdict": verdict,
        "elapsed_seconds": round(elapsed_sec, 3),
        "num_frames_analyzed": len(eval_paths),
        "total_frames_in_dir": len(image_paths),
        "valid_frames": valid_count,
        "skipped_or_fallback_frames": skipped_count,
        "valid_frame_ratio": round(valid_ratio, 4),
        "crop": {
            "x_start": int(crop.x_start),
            "x_end": int(crop.x_end),
            "y_start": int(crop.y_start),
            "y_end": int(crop.y_end),
            "width": int(crop.width),
            "height": int(crop.height),
            "original_width": width,
            "original_height": height,
            "area_retention_ratio": round(area_retention, 4),
            "width_retention_ratio": round(width_retention, 4),
            "height_retention_ratio": round(height_retention, 4),
        },
        "transform_stats": {
            "max_dx": round(float(t_stats["max_dx"]), 3),
            "max_dy": round(float(t_stats["max_dy"]), 3),
            "avg_dx": round(float(t_stats["avg_dx"]), 3),
            "avg_dy": round(float(t_stats["avg_dy"]), 3),
            "total_rotation_deg": round(float(t_stats["total_rotation_deg"]), 4),
            "rms_step_jitter_px": round(jitter_px, 4),
        },
        "mode_details": mode_details,
        "diagnostics": diagnostics,
        "evaluated_settings": cfg,
    }


def compare_alignment_candidates_data(
    input_dir: str | Path,
    candidates: Optional[List[Dict[str, Any]]] = None,
    max_frames: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Benchmark multiple candidate alignment configurations side-by-side on `input_dir`
    and return them ranked by `alignment_score`.
    """
    if not candidates:
        star_analysis = analyze_star_field_data(input_dir)
        manual_info = star_analysis["manual_tracking_candidates"]
        pol = manual_info["recommended_polaris"]
        sec = manual_info["recommended_second_star"]

        candidates = [
            {
                "name": "auto_star_field",
                "description": "Automatic multi-star field trajectory fitting and wobble correction (polaris=None)",
                "settings": {
                    "polaris_x": None,
                    "polaris_y": None,
                    "sort_by_time": True,
                },
            }
        ]
        if pol is not None:
            candidates.append(
                {
                    "name": "manual_1star_kalman",
                    "description": "Manual single-star tracking with Kalman smoothing (translation only)",
                    "settings": {
                        "polaris_x": pol["x"],
                        "polaris_y": pol["y"],
                        "use_rotation": False,
                        "use_kalman": True,
                        "kalman_process_noise": 0.01,
                        "kalman_measurement_noise": 2.0,
                        "sort_by_time": True,
                    },
                }
            )
            if sec is not None:
                candidates.append(
                    {
                        "name": "manual_2star_kalman_rotation",
                        "description": "Manual two-star tracking with Kalman smoothing and rotation correction",
                        "settings": {
                            "polaris_x": pol["x"],
                            "polaris_y": pol["y"],
                            "star2_x": sec["x"],
                            "star2_y": sec["y"],
                            "use_rotation": True,
                            "use_kalman": True,
                            "kalman_process_noise": 0.01,
                            "kalman_measurement_noise": 2.0,
                            "sort_by_time": True,
                        },
                    }
                )

    results: List[Dict[str, Any]] = []
    for idx, item in enumerate(candidates):
        name = item.get("name") or f"candidate_{idx + 1}"
        description = item.get("description") or ""
        cand_settings = item.get("settings") if isinstance(item.get("settings"), dict) else dict(item)
        try:
            report = evaluate_alignment_config(input_dir, settings=cand_settings, max_frames=max_frames)
            results.append(
                {
                    "name": name,
                    "description": description,
                    "succeeded": True,
                    "alignment_score": report["alignment_score"],
                    "verdict": report["verdict"],
                    "mode": report["mode"],
                    "valid_frame_ratio": report["valid_frame_ratio"],
                    "area_retention_ratio": report["crop"]["area_retention_ratio"],
                    "rms_step_jitter_px": report["transform_stats"]["rms_step_jitter_px"],
                    "settings": cand_settings,
                    "report": report,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "name": name,
                    "description": description,
                    "succeeded": False,
                    "alignment_score": 0.0,
                    "verdict": "failed",
                    "error": str(exc),
                    "settings": cand_settings,
                }
            )

    results.sort(key=lambda r: (r["succeeded"], r["alignment_score"]), reverse=True)
    winner = results[0] if results else None

    return {
        "input_dir": str(Path(input_dir).expanduser().resolve()),
        "candidate_count": len(results),
        "best_candidate": winner["name"] if winner else None,
        "best_alignment_score": winner["alignment_score"] if winner else 0.0,
        "best_settings": winner["settings"] if winner else {},
        "ranked_candidates": results,
    }


def recommend_stack_settings(
    input_dir: str | Path,
    goal: str = "balanced",
    include_pass1_probe: bool = True,
    video_export: bool = False,
) -> Dict[str, Any]:
    """
    Analyze the exposure sequence in `input_dir` and synthesize optimal,
    justified settings for creating a high-quality star trail stack.
    """
    normalized_goal = (goal or "balanced").strip().lower()
    inspection = inspect_sequence_data(input_dir, sort_by_time=True, sample_frames=5)
    star_info = analyze_star_field_data(input_dir, frame_step=max(1, inspection["num_images"] // 5))

    num_images = inspection["num_images"]
    img_info = inspection["image_info"]
    timeline = inspection["timeline"]
    fg_info = inspection["scene_analysis"]["foreground_analysis"]
    sampled = inspection["scene_analysis"]["sampled_frames"]
    compute = inspection["compute"]

    rationale: Dict[str, str] = {}

    sort_by_time = True
    rationale["sort_by_time"] = (
        "Enabled EXIF timestamp sorting so exposures are stacked in true chronological order."
        if timeline["has_exif_timestamps"]
        else "Enabled sort_by_time=True (falls back to file order when EXIF timestamps are absent)."
    )

    polaris_x: Optional[float] = None
    polaris_y: Optional[float] = None
    star2_x: Optional[float] = None
    star2_y: Optional[float] = None
    use_rotation = False
    use_kalman = True
    kalman_process_noise = 0.01
    kalman_measurement_noise = 2.0

    probe_report: Optional[Dict[str, Any]] = None
    if star_info["recommended_alignment_mode"] == "star_field":
        rationale["alignment_mode"] = star_info["recommendation_reason"]
        if include_pass1_probe:
            try:
                probe_report = evaluate_alignment_config(
                    input_dir,
                    settings={"polaris_x": None, "polaris_y": None, "sort_by_time": sort_by_time},
                    max_frames=min(num_images, 30),
                )
            except Exception:
                probe_report = None
    else:
        pol = star_info["manual_tracking_candidates"]["recommended_polaris"]
        sec = star_info["manual_tracking_candidates"]["recommended_second_star"]
        if pol is not None:
            polaris_x, polaris_y = pol["x"], pol["y"]
        if sec is not None:
            star2_x, star2_y = sec["x"], sec["y"]
            use_rotation = True
        rationale["alignment_mode"] = star_info["recommendation_reason"]
        if include_pass1_probe and polaris_x is not None and polaris_y is not None:
            try:
                probe_report = evaluate_alignment_config(
                    input_dir,
                    settings={
                        "polaris_x": polaris_x,
                        "polaris_y": polaris_y,
                        "star2_x": star2_x,
                        "star2_y": star2_y,
                        "use_rotation": use_rotation,
                        "use_kalman": use_kalman,
                        "sort_by_time": sort_by_time,
                    },
                    max_frames=min(num_images, 30),
                )
            except Exception:
                probe_report = None

    fill_gaps = bool(timeline["gap_detected"]) and normalized_goal != "maximum_sharpness"
    if normalized_goal == "gap_repair":
        fill_gaps = True
    rationale["fill_gaps"] = (
        f"Enabled fill_gaps=True because {timeline['gap_count']} timestamp gap(s) "
        f"(~{timeline['total_missing_frames_estimate']} missing frames) were detected."
        if fill_gaps and timeline["gap_detected"]
        else (
            "Enabled fill_gaps=True as requested by the gap_repair goal."
            if fill_gaps
            else "Set fill_gaps=False because exposure intervals are uniform with no missing-frame gaps."
        )
    )

    auto_rot_deg = abs(float(star_info["auto_field_detection"].get("rotation_angle_deg") or 0.0))
    sidereal_rot_deg = abs(float(timeline.get("estimated_sidereal_rotation_deg") or 0.0))
    observed_span_deg = max(auto_rot_deg, sidereal_rot_deg)

    if normalized_goal in ("dramatic_extended", "extended", "extended_trails"):
        if observed_span_deg > 0.5:
            target_factor = max(1.5, min(3.0, round(18.0 / observed_span_deg, 1)))
        else:
            target_factor = 2.0
        extension_factor = float(target_factor)
        ghost_frames_per_real = 12 if num_images <= 60 else 8
        synthetic_fade_factor = 0.15
        rationale["extension_factor"] = (
            f"Set extension_factor={extension_factor} with ghost_frames_per_real={ghost_frames_per_real} "
            f"and synthetic_fade_factor={synthetic_fade_factor} to produce longer, continuous sweeping star arcs."
        )
    elif normalized_goal == "maximum_sharpness":
        extension_factor = 1.0
        ghost_frames_per_real = 5
        synthetic_fade_factor = 0.2
        rationale["extension_factor"] = (
            "Set extension_factor=1.0 (no synthetic extrapolation) to preserve 100% authentic observational star profiles."
        )
    else:
        extension_factor = 1.0
        ghost_frames_per_real = 10 if fill_gaps else 8
        synthetic_fade_factor = 0.15 if fill_gaps else 0.2
        rationale["extension_factor"] = (
            "Set extension_factor=1.0 to match the real exposure duration while correcting camera drift/wobble."
        )

    has_fg = bool(fg_info["has_significant_foreground"])
    use_foreground_mask = bool(has_fg or extension_factor > 1.0 or fill_gaps)
    rationale["use_foreground_mask"] = (
        f"Enabled use_foreground_mask=True because foreground covers {fg_info['foreground_fraction'] * 100:.1f}% "
        "of the frame; masking prevents landscape smearing during synthetic interpolation/extension."
        if has_fg
        else "Enabled use_foreground_mask=True as a safeguard for any synthetic trail interpolation."
    )

    mean_p99 = float(np.mean([m["p99_5_brightness_u8"] for m in sampled])) if sampled else 128.0
    blend_mode = DEFAULT_BLEND_MODE
    raw_exposure_ev = 0.0
    raw_noise_reduction = True

    if normalized_goal == "faint_stars_boost":
        if img_info["is_raw"] and mean_p99 < 160.0:
            raw_exposure_ev = 1.0
            rationale["raw_exposure_ev"] = (
                f"Set raw_exposure_ev=1.0 EV because source files are RAW and bright sky percentile is modest ({mean_p99:.1f}/255)."
            )
        blend_mode = "lighten"
        rationale["blend_mode"] = (
            "Selected 'lighten' blend mode so star trails accumulate peak star flux without blowing out the sky background."
        )
    else:
        if img_info["is_raw"] and mean_p99 < 90.0:
            raw_exposure_ev = 0.75
            rationale["raw_exposure_ev"] = (
                f"Applied a gentle +0.75 EV RAW exposure boost because frames are dark (p99.5={mean_p99:.1f}/255)."
            )
        rationale["blend_mode"] = (
            "Selected 'lighten' (maximum) blend mode, which is ideal for star trails because it records peak star positions "
            "without accumulating skyglow or thermal noise."
        )

    enable_video = bool(video_export or normalized_goal in ("trail_lapse_video", "video", "trail_lapse"))
    video_fps = 30
    # Keep the default video export responsive; callers can choose 2, 4, or 8
    # when they want more interpolated snapshots per exposure interval.
    video_slowdown = 1
    image_resolution = "source"
    video_resolution = "source"
    quality = "high"
    video_hyperlapse = bool(num_images >= 90 and extension_factor <= 1.0)
    if enable_video:
        rationale["video"] = (
            f"Enabled trail-lapse video at {video_fps} fps (quality='{quality}', video_hyperlapse={video_hyperlapse}) "
            f"with {video_slowdown} snapshot per exposure interval, tailored to {num_images} input exposures."
        )

    compute_backend = "auto"
    cpu_workers = int(compute["recommended_workers"])
    rationale["compute"] = (
        f"Using compute_backend='auto' with cpu_workers={cpu_workers} "
        f"({'OpenCL GPU detected: ' + compute['gpus'][0]['name'] if compute['gpu_available'] else 'CPU multi-threading'})."
    )

    recommended_settings: Dict[str, Any] = {
        "input_dir": inspection["input_dir"],
        "output_file": str(Path(inspection["input_dir"]) / "aligned_star_trails.tiff"),
        "sort_by_time": sort_by_time,
        "polaris_x": polaris_x,
        "polaris_y": polaris_y,
        "star2_x": star2_x,
        "star2_y": star2_y,
        "use_rotation": use_rotation,
        "use_kalman": use_kalman,
        "kalman_process_noise": kalman_process_noise,
        "kalman_measurement_noise": kalman_measurement_noise,
        "extension_factor": extension_factor,
        "ghost_frames_per_real": ghost_frames_per_real,
        "synthetic_fade_factor": synthetic_fade_factor,
        "use_foreground_mask": use_foreground_mask,
        "fill_gaps": fill_gaps,
        "blend_mode": blend_mode,
        "raw_noise_reduction": raw_noise_reduction,
        "raw_exposure_ev": raw_exposure_ev,
        "video_enabled": enable_video,
        "video_fps": video_fps,
        "video_slowdown": video_slowdown,
        "image_resolution": image_resolution,
        "video_resolution": video_resolution,
        "quality": quality,
        "video_hyperlapse": video_hyperlapse,
        "use_checkpoint": True,
        "resume": False,
        "compute_backend": compute_backend,
        "cpu_workers": cpu_workers,
    }

    presets = {
        "natural_faithful": {
            **recommended_settings,
            "extension_factor": 1.0,
            "fill_gaps": bool(timeline["gap_detected"]),
            "video_enabled": False,
        },
        "dramatic_extended_trails": {
            **recommended_settings,
            "extension_factor": max(1.8, extension_factor if extension_factor > 1.0 else 2.0),
            "ghost_frames_per_real": 12,
            "synthetic_fade_factor": 0.15,
            "use_foreground_mask": True,
        },
        "pure_no_synthesis": {
            **recommended_settings,
            "extension_factor": 1.0,
            "fill_gaps": False,
            "use_foreground_mask": False,
            "video_enabled": False,
        },
        "trail_lapse_export": {
            **recommended_settings,
            "video_enabled": True,
            "video_fps": 30,
            "video_slowdown": 1,
            "quality": "high",
            "video_hyperlapse": bool(num_images >= 90),
        },
    }

    return {
        "goal": normalized_goal,
        "recommended_settings": recommended_settings,
        "rationale": rationale,
        "pass1_probe": probe_report,
        "sequence_summary": {
            "num_images": num_images,
            "dimensions": f"{img_info['width']}x{img_info['height']}",
            "is_raw": img_info["is_raw"],
            "recommended_bit_depth": img_info["recommended_output_bit_depth"],
            "gap_detected": timeline["gap_detected"],
            "gap_count": timeline["gap_count"],
            "foreground_fraction": fg_info["foreground_fraction"],
            "recommended_alignment_mode": star_info["recommended_alignment_mode"],
            "pole_in_frame": star_info["auto_field_detection"]["pole_in_frame"],
        },
        "alternative_presets": presets,
    }


def evaluate_stack_image(
    stack_path: str | Path,
    reference_frame_path: Optional[str | Path] = None,
    preview_output_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """
    Analyze a rendered star trail stack image (TIFF/PNG/JPEG) and compute objective
    quality metrics (trail coverage, trail continuity vs beading, highlight clipping,
    dynamic range, foreground sharpness preservation) along with tuning suggestions.
    """
    path = Path(stack_path).expanduser().resolve()
    if not path.exists():
        raise ValueError(f"Stack file does not exist: {stack_path}")

    img = load_image(path, for_export=True)
    height, width = img.shape[:2]
    channels = img.shape[2] if img.ndim == 3 else 1
    dtype_str = str(img.dtype)
    bit_depth = 16 if img.dtype == np.uint16 else (32 if np.issubdtype(img.dtype, np.floating) else 8)
    max_possible = 65535.0 if img.dtype == np.uint16 else 255.0

    u8_bgr = _to_uint8_bgr(img)
    gray_u8 = cv2.cvtColor(u8_bgr, cv2.COLOR_BGR2GRAY)
    gray_norm = img.astype(np.float32) / max_possible
    if gray_norm.ndim == 3:
        gray_norm = np.mean(gray_norm, axis=2)

    min_val = float(np.min(gray_norm))
    max_val = float(np.max(gray_norm))
    mean_val = float(np.mean(gray_norm))
    std_val = float(np.std(gray_norm))
    p5, p50, p95, p99, p99_9 = [
        float(v) for v in np.percentile(gray_norm, [5.0, 50.0, 95.0, 99.0, 99.9])
    ]

    clipping_fraction = float(np.mean(gray_norm >= 0.995))
    noise_floor = max(1e-5, float(np.percentile(gray_norm, 10.0)))
    dynamic_range_db = float(20.0 * math.log10(max(max_val, 1e-5) / noise_floor))

    sky_mask = segment_sky_ground(u8_bgr, method="combined")
    if np.count_nonzero(sky_mask) < 0.1 * sky_mask.size:
        sky_mask = np.full_like(gray_u8, 255)

    sky_pixels = gray_u8[sky_mask > 0]
    sky_median = float(np.median(sky_pixels)) if sky_pixels.size else 0.0
    sky_std = float(np.std(sky_pixels)) if sky_pixels.size else 1.0
    trail_thresh = max(sky_median + 2.0 * sky_std, float(np.percentile(sky_pixels, 92.0)) if sky_pixels.size else 40.0)

    trail_binary = ((gray_u8.astype(np.float32) >= trail_thresh) & (sky_mask > 0)).astype(np.uint8) * 255
    trail_coverage_fraction = float(np.count_nonzero(trail_binary)) / max(1.0, float(np.count_nonzero(sky_mask)))

    num_raw_labels, _, raw_stats, _ = cv2.connectedComponentsWithStats(trail_binary, connectivity=8)
    significant_raw = 0
    elongated_raw = 0
    for i in range(1, num_raw_labels):
        area = int(raw_stats[i, cv2.CC_STAT_AREA])
        if area >= 4:
            significant_raw += 1
            bw = max(1, int(raw_stats[i, cv2.CC_STAT_WIDTH]))
            bh = max(1, int(raw_stats[i, cv2.CC_STAT_HEIGHT]))
            diag = math.hypot(bw, bh)
            if diag >= 8.0 and (diag * diag) / max(1.0, float(area)) >= 2.2:
                elongated_raw += 1

    close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    closed_binary = cv2.morphologyEx(trail_binary, cv2.MORPH_CLOSE, close_kernel)
    num_closed_labels, _, closed_stats, _ = cv2.connectedComponentsWithStats(closed_binary, connectivity=8)
    significant_closed = sum(
        1 for i in range(1, num_closed_labels) if int(closed_stats[i, cv2.CC_STAT_AREA]) >= 4
    )

    if significant_raw > 0:
        bridging_ratio = min(1.0, float(significant_closed) / float(significant_raw))
        elongation_ratio = float(elongated_raw) / float(significant_raw)
        trail_continuity_score = round(0.55 * bridging_ratio + 0.45 * min(1.0, elongation_ratio * 1.5), 4)
    else:
        trail_continuity_score = 0.0

    reference_comparison: Optional[Dict[str, Any]] = None
    if reference_frame_path is not None and Path(reference_frame_path).expanduser().exists():
        ref_img = load_image(Path(reference_frame_path).expanduser().resolve(), for_export=True)
        ref_u8 = _to_uint8_bgr(ref_img)
        if ref_u8.shape[:2] != u8_bgr.shape[:2]:
            ref_u8 = cv2.resize(ref_u8, (width, height), interpolation=cv2.INTER_AREA)
        ref_gray = cv2.cvtColor(ref_u8, cv2.COLOR_BGR2GRAY)
        ref_bright_frac = float(np.mean(ref_gray.astype(np.float32) >= trail_thresh))
        trail_expansion_ratio = round(trail_coverage_fraction / max(ref_bright_frac, 1e-5), 2)

        ground_mask = sky_mask == 0
        if np.count_nonzero(ground_mask) >= 100:
            stack_grad = np.hypot(
                cv2.Sobel(gray_u8, cv2.CV_32F, 1, 0, ksize=3),
                cv2.Sobel(gray_u8, cv2.CV_32F, 0, 1, ksize=3),
            )
            ref_grad = np.hypot(
                cv2.Sobel(ref_gray, cv2.CV_32F, 1, 0, ksize=3),
                cv2.Sobel(ref_gray, cv2.CV_32F, 0, 1, ksize=3),
            )
            fg_retention = float(np.mean(stack_grad[ground_mask])) / max(
                1e-4, float(np.mean(ref_grad[ground_mask]))
            )
            fg_sharpness_retention = round(min(1.2, fg_retention), 4)
        else:
            fg_sharpness_retention = None

        reference_comparison = {
            "reference_frame": str(Path(reference_frame_path).expanduser().resolve()),
            "trail_coverage_expansion_ratio": trail_expansion_ratio,
            "foreground_sharpness_retention": fg_sharpness_retention,
        }

    tuning_suggestions: List[str] = []

    if p99 < 0.08:
        score_signal = 10.0
        tuning_suggestions.append(
            "Stack appears very dim (p99 < 8% of full scale). For RAW files, increase raw_exposure_ev (e.g. 1.0–2.0 EV)."
        )
    else:
        score_signal = 30.0 * min(1.0, p99 / 0.35)

    if clipping_fraction > 0.05:
        score_clipping = max(0.0, 25.0 * (1.0 - (clipping_fraction - 0.05) / 0.25))
        tuning_suggestions.append(
            f"High highlight saturation detected ({clipping_fraction * 100:.1f}% clipped). "
            "Use blend_mode='lighten' instead of 'add', or reduce raw_exposure_ev / synthetic_fade_factor."
        )
    else:
        score_clipping = 25.0

    score_continuity = 30.0 * min(1.0, max(0.2, trail_continuity_score / 0.75))
    if trail_continuity_score < 0.45 and significant_raw >= 10:
        tuning_suggestions.append(
            f"Star trails show beading or gaps (continuity_score={trail_continuity_score:.2f}). "
            "Enable fill_gaps=True if exposures were dropped, or set extension_factor > 1.0 with ghost_frames_per_real=10–15."
        )

    contrast_span = max(0.0, p99 - p50)
    score_contrast = 15.0 * min(1.0, contrast_span / 0.20)

    overall_score = round(score_signal + score_clipping + score_continuity + score_contrast, 2)
    if overall_score >= 82.0:
        verdict = "excellent"
    elif overall_score >= 68.0:
        verdict = "good"
    elif overall_score >= 50.0:
        verdict = "needs_tuning"
    else:
        verdict = "poor"

    if not tuning_suggestions:
        tuning_suggestions.append(
            "Stack exhibits strong trail signal, minimal clipping, and good continuity. No further parameter changes required."
        )

    saved_preview: Optional[str] = None
    if preview_output_path:
        prev_path = Path(preview_output_path).expanduser().resolve()
        prev_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(prev_path), u8_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        saved_preview = str(prev_path)

    return {
        "stack_path": str(path),
        "file_size_bytes": int(path.stat().st_size),
        "dimensions": {"width": width, "height": height, "channels": channels},
        "dtype": dtype_str,
        "bit_depth": bit_depth,
        "brightness": {
            "min": round(min_val, 4),
            "max": round(max_val, 4),
            "mean": round(mean_val, 4),
            "std": round(std_val, 4),
            "p5": round(p5, 4),
            "p50": round(p50, 4),
            "p95": round(p95, 4),
            "p99": round(p99, 4),
            "p99_9": round(p99_9, 4),
            "dynamic_range_db": round(dynamic_range_db, 2),
        },
        "trail_metrics": {
            "clipping_fraction": round(clipping_fraction, 5),
            "trail_coverage_fraction": round(trail_coverage_fraction, 5),
            "trail_component_count": int(significant_raw),
            "elongated_trail_count": int(elongated_raw),
            "trail_continuity_score": trail_continuity_score,
        },
        "reference_comparison": reference_comparison,
        "overall_quality_score": overall_score,
        "verdict": verdict,
        "tuning_suggestions": tuning_suggestions,
        "preview_jpeg_path": saved_preview,
    }


def render_annotated_preview_image(
    image_path: str | Path,
    output_path: Optional[str | Path] = None,
    max_size: int = 1600,
    annotate_stars: bool = False,
    polaris: Optional[Tuple[float, float]] = None,
    second_star: Optional[Tuple[float, float]] = None,
    rotation_center: Optional[Tuple[float, float]] = None,
    crop: Optional[Dict[str, int]] = None,
    show_foreground_mask: bool = False,
    raw_noise_reduction: bool = True,
    raw_exposure_ev: float = 0.0,
) -> Dict[str, Any]:
    """
    Render any source exposure (including RAW/16-bit TIFF) or output stack into
    an 8-bit JPEG preview, with optional diagnostic overlays for stars, rotation
    center, crop region, and sky/foreground mask.
    """
    src = Path(image_path).expanduser().resolve()
    if not src.exists():
        raise ValueError(f"Image file does not exist: {image_path}")

    img = load_image(
        src,
        for_export=True,
        raw_noise_reduction=raw_noise_reduction,
        raw_exposure_ev=raw_exposure_ev,
    )
    orig_h, orig_w = img.shape[:2]
    canvas = _to_uint8_bgr(img).copy()

    if show_foreground_mask:
        mask = segment_sky_ground(canvas, method="combined")
        ground = mask == 0
        if np.any(ground):
            tint = np.full_like(canvas, (20, 90, 180))
            blended = cv2.addWeighted(canvas, 0.72, tint, 0.28, 0)
            canvas[ground] = blended[ground]
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(canvas, contours, -1, (0, 180, 255), 2)

    detected_count = 0
    if annotate_stars:
        coords = detect_sources(img, max_stars=60)
        detected_count = len(coords)
        for x, y in coords:
            cv2.circle(canvas, (int(round(x)), int(round(y))), 6, (255, 200, 0), 1, cv2.LINE_AA)

    if crop:
        x0 = int(crop.get("x_start", 0))
        y0 = int(crop.get("y_start", 0))
        x1 = int(crop.get("x_end", orig_w))
        y1 = int(crop.get("y_end", orig_h))
        cv2.rectangle(canvas, (x0, y0), (x1, y1), (0, 255, 128), 2)

    if polaris is not None:
        px, py = int(round(polaris[0])), int(round(polaris[1]))
        cv2.drawMarker(canvas, (px, py), (0, 255, 255), cv2.MARKER_CROSS, 18, 2)
        cv2.putText(
            canvas,
            "Polaris/Primary",
            (px + 10, max(20, py - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )

    if second_star is not None:
        sx, sy = int(round(second_star[0])), int(round(second_star[1]))
        cv2.drawMarker(canvas, (sx, sy), (255, 128, 0), cv2.MARKER_TILTED_CROSS, 16, 2)
        cv2.putText(
            canvas,
            "Star 2",
            (sx + 10, max(20, sy - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 128, 0),
            2,
            cv2.LINE_AA,
        )

    if rotation_center is not None:
        rx, ry = int(round(rotation_center[0])), int(round(rotation_center[1]))
        if 0 <= rx < orig_w and 0 <= ry < orig_h:
            cv2.circle(canvas, (rx, ry), 9, (180, 105, 255), 2, cv2.LINE_AA)
            cv2.putText(
                canvas,
                "Pole",
                (rx + 10, max(20, ry - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (180, 105, 255),
                2,
                cv2.LINE_AA,
            )

    scale = 1.0
    if max_size and max(orig_w, orig_h) > max_size:
        scale = float(max_size) / float(max(orig_w, orig_h))
        new_w = max(1, int(round(orig_w * scale)))
        new_h = max(1, int(round(orig_h * scale)))
        canvas = cv2.resize(canvas, (new_w, new_h), interpolation=cv2.INTER_AREA)

    if output_path is None:
        out_file = src.with_name(f"{src.stem}_preview.jpg")
    else:
        out_file = Path(output_path).expanduser().resolve()

    out_file.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_file), canvas, [int(cv2.IMWRITE_JPEG_QUALITY), 92])

    return {
        "source_path": str(src),
        "preview_path": str(out_file),
        "original_dimensions": {"width": orig_w, "height": orig_h},
        "preview_dimensions": {"width": int(canvas.shape[1]), "height": int(canvas.shape[0])},
        "scale_factor": round(scale, 4),
        "annotated_stars_count": detected_count,
    }


def execute_stack_pipeline(
    input_dir: str | Path,
    output_file: Optional[str | Path] = None,
    settings: Optional[Dict[str, Any]] = None,
    evaluate_output: bool = True,
    generate_preview_jpeg: bool = True,
) -> Dict[str, Any]:
    """
    Run the complete Pass 1 + Pass 2 `AlignmentEngine` synchronously and return
    the output file paths, alignment telemetry, and post-stack quality evaluation.
    """
    cfg = dict(settings or {})
    folder = Path(input_dir).expanduser().resolve()
    if output_file is not None:
        out_path = Path(output_file).expanduser().resolve()
    elif cfg.get("output_file"):
        out_path = Path(str(cfg["output_file"])).expanduser().resolve()
    else:
        out_path = folder / "aligned_star_trails.tiff"

    polaris = cfg.get("polaris")
    if polaris is None and cfg.get("polaris_x") is not None and cfg.get("polaris_y") is not None:
        polaris = (float(cfg["polaris_x"]), float(cfg["polaris_y"]))
    elif polaris is not None:
        polaris = (float(polaris[0]), float(polaris[1]))

    second_star = cfg.get("second_star")
    if second_star is None and cfg.get("star2_x") is not None and cfg.get("star2_y") is not None:
        second_star = (float(cfg["star2_x"]), float(cfg["star2_y"]))
    elif second_star is not None:
        second_star = (float(second_star[0]), float(second_star[1]))

    events: List[Dict[str, Any]] = []

    def progress_cb(data: Dict[str, Any]) -> None:
        if data.get("status") in ("ready", "calculating_transforms", "retrying_on_cpu", "complete"):
            events.append(dict(data))

    engine = AlignmentEngine(
        input_dir=folder,
        output_file=out_path,
        extension_factor=float(cfg.get("extension_factor", 1.0)),
        tail_taper_strength=float(cfg.get("tail_taper_strength", 0.0)),
        tail_angle_threshold=float(cfg.get("tail_angle_threshold", 0.0)),
        use_rotation=bool(cfg.get("use_rotation", False)),
        use_kalman=bool(cfg.get("use_kalman", True)),
        kalman_process_noise=float(cfg.get("kalman_process_noise", KALMAN_PROCESS_NOISE)),
        kalman_measurement_noise=float(cfg.get("kalman_measurement_noise", KALMAN_MEASUREMENT_NOISE)),
        blend_mode=str(cfg.get("blend_mode", DEFAULT_BLEND_MODE)),
        video_enabled=bool(cfg.get("video_enabled", False)),
        video_fps=int(cfg.get("video_fps", 30)),
        video_slowdown=int(cfg.get("video_slowdown", 1)),
        image_resolution=str(cfg.get("image_resolution", "source")),
        video_resolution=str(cfg.get("video_resolution", "source")),
        quality=str(cfg.get("quality", "high")),
        video_hyperlapse=bool(cfg.get("video_hyperlapse", False)),
        use_foreground_mask=bool(cfg.get("use_foreground_mask", True)),
        ghost_frames_per_real=int(cfg.get("ghost_frames_per_real", 10)),
        synthetic_fade_factor=float(cfg.get("synthetic_fade_factor", 0.2)),
        fill_gaps=bool(cfg.get("fill_gaps", False)),
        image_format=str(cfg.get("image_format", "tiff")),
        video_format=str(cfg.get("video_format", "auto")),
        save_frames=bool(cfg.get("save_frames", False)),
        no_stack=bool(cfg.get("no_stack", False)),
        use_checkpoint=bool(cfg.get("use_checkpoint", True)),
        resume=bool(cfg.get("resume", False)),
        sort_by_time=bool(cfg.get("sort_by_time", True)),
        progress_callback=progress_cb,
        compute_backend=str(cfg.get("compute_backend", "auto")),
        cpu_workers=cfg.get("cpu_workers"),
        raw_noise_reduction=bool(cfg.get("raw_noise_reduction", True)),
        raw_exposure_ev=float(cfg.get("raw_exposure_ev", 0.0)),
        conversion_format=str(cfg.get("conversion_format", "none")),
        conversion_output_dir=cfg.get("conversion_output_dir"),
        search_window_size=int(cfg.get("search_window_size", SEARCH_WINDOW_SIZE)),
        max_jump_threshold=float(cfg.get("max_jump_threshold", MAX_JUMP_THRESHOLD)),
        star_threshold_percentile=float(cfg.get("star_threshold_percentile", STAR_THRESHOLD_PERCENTILE)),
        min_blob_area=int(cfg.get("min_blob_area", MIN_BLOB_AREA)),
        max_blob_area=int(cfg.get("max_blob_area", MAX_BLOB_AREA)),
    )

    started = time.perf_counter()
    with engine:
        prep_info = engine.prepare()
        _, transforms = engine.run_pass1(polaris=polaris, second_star=second_star)
        crop = engine.calculate_crop(transforms)
        reference_frame_path = (engine.source_image_paths[0]
                                if engine.source_image_paths else None)
        result_path = engine.run_pass2(transforms, crop, polaris=polaris)
    elapsed_sec = time.perf_counter() - started

    t_stats = get_transform_statistics(transforms)
    skipped_frames = (
        list(engine.field_analysis.skipped_frames) if engine.field_analysis is not None else []
    )

    video_path: Optional[str] = None
    if engine.video_enabled:
        for ext in (".mp4", ".mov"):
            cand = Path(result_path).with_suffix(ext)
            if cand.exists():
                video_path = str(cand)
                break

    preview_path: Optional[str] = None
    if generate_preview_jpeg and not engine.no_stack and Path(result_path).exists():
        preview_path = str(Path(result_path).with_name(f"{Path(result_path).stem}_preview.jpg"))

    quality_report: Optional[Dict[str, Any]] = None
    if evaluate_output and not engine.no_stack and Path(result_path).exists():
        quality_report = evaluate_stack_image(
            result_path,
            reference_frame_path=reference_frame_path,
            preview_output_path=preview_path,
        )

    return {
        "result_path": str(result_path),
        "exports": dict(engine.export_results),
        "video_path": video_path,
        "preview_jpeg_path": preview_path,
        "elapsed_seconds": round(elapsed_sec, 3),
        "alignment_mode": "star_field" if polaris is None else "manual_tracking",
        "num_images_stacked": int(prep_info["num_images"]),
        "conversion_format": str(cfg.get("conversion_format", "none")),
        "converted_files_dir": engine.converted_files_dir,
        "skipped_frames": skipped_frames,
        "crop": {
            "x_start": int(crop.x_start),
            "x_end": int(crop.x_end),
            "y_start": int(crop.y_start),
            "y_end": int(crop.y_end),
            "width": int(crop.width),
            "height": int(crop.height),
        },
        "transform_stats": {
            "max_dx": round(float(t_stats["max_dx"]), 3),
            "max_dy": round(float(t_stats["max_dy"]), 3),
            "avg_dx": round(float(t_stats["avg_dx"]), 3),
            "avg_dy": round(float(t_stats["avg_dy"]), 3),
            "total_rotation_deg": round(float(t_stats["total_rotation_deg"]), 4),
        },
        "compute": dict(engine.compute_info),
        "warnings": prep_info.get("warnings", []),
        "quality_report": quality_report,
    }


def render_preview_stack_data(
    input_dir: str | Path,
    output_file: Optional[str | Path] = None,
    settings: Optional[Dict[str, Any]] = None,
    max_dimension: int = 960,
    max_frames: int = 24,
) -> Dict[str, Any]:
    """
    Create a fast downscaled preview stack from a subset of frames so an agent
    can rapidly test and visually/quantitatively verify candidate stacking
    parameters before running a full-resolution stack.
    """
    cfg = dict(settings or {})
    sort_by_time = bool(cfg.get("sort_by_time", True))
    raw_noise_reduction = bool(cfg.get("raw_noise_reduction", True))
    raw_exposure_ev = float(cfg.get("raw_exposure_ev", 0.0))

    image_paths, _ = filter_source_images(input_dir, sort_by_time=sort_by_time)
    total_available = len(image_paths)
    sample_count = max(2, min(int(max_frames), total_available))
    selected_indices = sorted(
        set(np.linspace(0, total_available - 1, num=sample_count, dtype=int).tolist())
    )
    selected_paths = [image_paths[i] for i in selected_indices]

    first_info = get_image_info(selected_paths[0])
    orig_w = int(first_info["width"])
    orig_h = int(first_info["height"])

    scale = 1.0
    if max_dimension and max(orig_w, orig_h) > int(max_dimension):
        scale = float(max_dimension) / float(max(orig_w, orig_h))

    scaled_w = max(32, int(round(orig_w * scale)))
    scaled_h = max(32, int(round(orig_h * scale)))

    scaled_cfg = dict(cfg)
    if scaled_cfg.get("polaris_x") is not None and scaled_cfg.get("polaris_y") is not None:
        scaled_cfg["polaris_x"] = float(scaled_cfg["polaris_x"]) * scale
        scaled_cfg["polaris_y"] = float(scaled_cfg["polaris_y"]) * scale
    if scaled_cfg.get("star2_x") is not None and scaled_cfg.get("star2_y") is not None:
        scaled_cfg["star2_x"] = float(scaled_cfg["star2_x"]) * scale
        scaled_cfg["star2_y"] = float(scaled_cfg["star2_y"]) * scale
    if scaled_cfg.get("polaris") is not None:
        p = scaled_cfg["polaris"]
        scaled_cfg["polaris"] = (float(p[0]) * scale, float(p[1]) * scale)
    if scaled_cfg.get("second_star") is not None:
        s = scaled_cfg["second_star"]
        scaled_cfg["second_star"] = (float(s[0]) * scale, float(s[1]) * scale)

    scaled_cfg["use_checkpoint"] = False
    scaled_cfg["resume"] = False
    scaled_cfg["raw_exposure_ev"] = 0.0

    folder = Path(input_dir).expanduser().resolve()
    if output_file is not None:
        final_out = Path(output_file).expanduser().resolve()
    else:
        final_out = folder / "mcp_preview_stack.tiff"

    with TemporaryDirectory(prefix=".mcp-preview-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        for idx, src_path in enumerate(selected_paths):
            img = load_image(
                src_path,
                for_export=True,
                raw_noise_reduction=raw_noise_reduction,
                raw_exposure_ev=raw_exposure_ev,
            )
            if scale < 1.0:
                img = cv2.resize(img, (scaled_w, scaled_h), interpolation=cv2.INTER_AREA)
            frame_out = tmp_path / f"frame_{idx:04d}.tiff"
            bit_depth = 16 if img.dtype == np.uint16 else 8
            save_tiff(img, frame_out, bit_depth=bit_depth)
            try:
                st = src_path.stat()
                os.utime(frame_out, (st.st_atime, st.st_mtime))
            except OSError:
                pass

        result = execute_stack_pipeline(
            input_dir=tmp_path,
            output_file=final_out,
            settings=scaled_cfg,
            evaluate_output=True,
            generate_preview_jpeg=True,
        )

    result["preview_mode"] = {
        "original_dimensions": {"width": orig_w, "height": orig_h},
        "preview_dimensions": {"width": scaled_w, "height": scaled_h},
        "scale_factor": round(scale, 4),
        "sampled_frames": len(selected_paths),
        "total_frames_in_dir": total_available,
    }
    return result
