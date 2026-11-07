#!/usr/bin/env python3
"""Generate deterministic test fixtures and record Python oracle outputs for the Rust spike."""

import hashlib
import json
import os
import sys
from pathlib import Path

# Add project root and tests to sys.path
root_dir = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "tests"))

import cv2
import numpy as np
import rawpy
import tifffile
from scipy.spatial import cKDTree

from tests.test_raw_processing import write_dark_dng
from tests.test_raw_preview import write_dng
from tests.test_astronomy import make_sky
from tests.test_field_alignment import write_sequence, observed_motion
from modules.astronomy import detect_sources, match_images, match_sources
from modules.image_preview import load_raw_preview
from modules.io_utils import load_image
from modules.raw_recovery import sensor_plane, measure_field, match_fields
from backend.engine.field_alignment import analyze_field


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main():
    fixtures_dir = Path(__file__).parent / "fixtures"
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    oracle = {}

    print(f"Generating fixtures in {fixtures_dir}...")

    # 1. Dark DNG (orientation 1)
    dark_path = fixtures_dir / "dark.dng"
    truth_stars = write_dark_dng(dark_path, orientation=1)
    oracle["dark_dng_truth_stars"] = truth_stars.tolist()
    dark_hash = sha256_file(dark_path)
    oracle["dark_dng_sha256"] = dark_hash

    # Python rawpy analysis of dark.dng
    with rawpy.imread(str(dark_path)) as raw:
        oracle["dark_dng_sizes"] = {
            "raw_height": raw.sizes.raw_height,
            "raw_width": raw.sizes.raw_width,
            "height": raw.sizes.height,
            "width": raw.sizes.width,
            "flip": raw.sizes.flip,
        }
        oracle["dark_dng_black_level_per_channel"] = list(raw.black_level_per_channel)
        oracle["dark_dng_raw_pattern"] = raw.raw_pattern.tolist()
        raw_vis = raw.raw_image_visible
        oracle["dark_dng_raw_image_visible"] = {
            "shape": list(raw_vis.shape),
            "min": int(raw_vis.min()),
            "max": int(raw_vis.max()),
        }
        s_plane = sensor_plane(raw)
        oracle["dark_dng_sensor_plane"] = {
            "shape": list(s_plane.shape),
            "min": float(s_plane.min()),
            "max": float(s_plane.max()),
            "median": float(np.median(s_plane)),
            "mean": float(np.mean(s_plane)),
        }

        # Tracking postprocess (linear, AHD, 16-bit, no auto bright)
        rgb_tracking = raw.postprocess(
            use_camera_wb=True,
            no_auto_bright=True,
            output_bps=16,
            gamma=(1, 1),
            demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD,
        )
        oracle["dark_dng_developed_tracking"] = {
            "shape": list(rgb_tracking.shape),
            "dtype": str(rgb_tracking.dtype),
            "median": float(np.median(rgb_tracking)),
            "max": int(rgb_tracking.max()),
            "min": int(rgb_tracking.min()),
        }

        # Export postprocess (sRGB gamma, AHD, 16-bit, no auto bright)
        rgb_export = raw.postprocess(
            use_camera_wb=True,
            no_auto_bright=True,
            output_bps=16,
            gamma=(2.222, 4.5),
            demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD,
        )
        oracle["dark_dng_developed_export"] = {
            "shape": list(rgb_export.shape),
            "dtype": str(rgb_export.dtype),
            "median": float(np.median(rgb_export)),
            "max": int(rgb_export.max()),
            "min": int(rgb_export.min()),
        }

    # Also detect sources on developed dark image
    developed_dark_bgr = load_image(dark_path)
    dark_detected = detect_sources(developed_dark_bgr)
    oracle["dark_detected_sources_count"] = len(dark_detected)
    oracle["dark_detected_sources"] = dark_detected.tolist()

    # 2. Dark DNG shifted (orientation 1, shift (9, -6))
    dark_shift_path = fixtures_dir / "dark_shift.dng"
    truth_stars_shift = write_dark_dng(dark_shift_path, shift=(9, -6), orientation=1)
    oracle["dark_shift_truth_stars"] = truth_stars_shift.tolist()
    dark_shift_detected = detect_sources(load_image(dark_shift_path))
    match_dark = match_sources(dark_detected, dark_shift_detected)
    assert match_dark is not None
    oracle["dark_match"] = {
        "matrix": match_dark.matrix.tolist(),
        "source_count": len(match_dark.source),
        "confidence": match_dark.confidence,
        "rms_error": match_dark.rms_error,
        "rotation_angle": match_dark.rotation_angle,
    }

    # 3. Dark DNG orientation 6
    dark_rot6_path = fixtures_dir / "dark_rot6.dng"
    write_dark_dng(dark_rot6_path, orientation=6)
    with rawpy.imread(str(dark_rot6_path)) as raw:
        s_plane_rot6 = sensor_plane(raw)
        oracle["dark_rot6_sensor_plane"] = {
            "shape": list(s_plane_rot6.shape),
            "min": float(s_plane_rot6.min()),
            "max": float(s_plane_rot6.max()),
        }

    # 4. Preview / Undecodable RAW fixtures
    for rot in (3, 6, 8):
        undec_path = fixtures_dir / f"undecodable_rot{rot}.dng"
        write_dng(undec_path, orientation=rot, embedded=True)
        with rawpy.imread(str(undec_path)) as raw:
            thumb = raw.extract_thumb()
            oracle[f"undecodable_rot{rot}_thumb"] = {
                "format": str(thumb.format),
                "len": len(thumb.data),
                "sha256": hashlib.sha256(thumb.data).hexdigest(),
            }
            # Verify LibRaw postprocess fails
            try:
                raw.postprocess()
                failed = False
            except rawpy.LibRawError as e:
                failed = True
                oracle[f"undecodable_rot{rot}_unpack_error"] = str(e)
            assert failed, f"Undecodable DNG rot{rot} unexpectedly decoded!"

        preview_bgr = load_raw_preview(undec_path)
        oracle[f"undecodable_rot{rot}_preview"] = {
            "shape": list(preview_bgr.shape),
            "mean": float(preview_bgr.mean()),
            "std": float(preview_bgr.std()),
        }

    # 5. CFA preview fixtures (embedded=False)
    for rot in (3, 6):
        cfa_path = fixtures_dir / f"cfa_rot{rot}.dng"
        write_dng(cfa_path, orientation=rot, embedded=False)
        cfa_preview = load_raw_preview(cfa_path)
        oracle[f"cfa_rot{rot}_preview"] = {
            "shape": list(cfa_preview.shape),
            "mean": float(cfa_preview.mean()),
            "std": float(cfa_preview.std()),
        }

    # 6. Astronomy synthetic fixtures
    sky_img, sky_stars = make_sky(seed=24, shape=(320, 420))
    sky_path = fixtures_dir / "sky_ref.png"
    cv2.imwrite(str(sky_path), np.clip(sky_img, 0, 255).astype(np.uint8))
    oracle["sky_ref_stars"] = sky_stars.tolist()

    # Detect sources on reference sky
    sky_sources = detect_sources(sky_img)
    oracle["sky_ref_detected"] = sky_sources.tolist()

    # Off-screen pole rotation: center (-280, -150), angle 3.0 deg
    rot_matrix = cv2.getRotationMatrix2D((-280, -150), 3.0, 1.0)
    sky_rot = cv2.warpAffine(sky_img, rot_matrix, (420, 320))
    sky_rot_path = fixtures_dir / "sky_rot.png"
    cv2.imwrite(str(sky_rot_path), np.clip(sky_rot, 0, 255).astype(np.uint8))
    match_rot = match_images(sky_img, sky_rot)
    assert match_rot is not None
    oracle["sky_rot_match"] = {
        "matrix": match_rot.matrix.tolist(),
        "source_count": len(match_rot.source),
        "confidence": match_rot.confidence,
        "rms_error": match_rot.rms_error,
        "rotation_angle": match_rot.rotation_angle,
        "rotation_center": list(match_rot.rotation_center),
    }

    # Pure translation: dx=16, dy=-9
    trans_matrix = np.float32([[1, 0, 16], [0, 1, -9]])
    sky_trans = cv2.warpAffine(sky_img, trans_matrix, (420, 320))
    match_trans = match_images(sky_img, sky_trans)
    assert match_trans is not None
    oracle["sky_trans_match"] = {
        "matrix": match_trans.matrix.tolist(),
        "source_count": len(match_trans.source),
        "confidence": match_trans.confidence,
        "rms_error": match_trans.rms_error,
        "rotation_center": match_trans.rotation_center,
    }

    # 7. Sequence of 12 frames with shake and sky rotation
    seq_dir = fixtures_dir / "sequence_12"
    seq_dir.mkdir(parents=True, exist_ok=True)
    seq_paths, expected_motion, seq_stars = write_sequence(seq_dir)
    oracle["sequence_stars"] = seq_stars.tolist()
    oracle["sequence_expected_motion"] = expected_motion.tolist()

    analysis = analyze_field(seq_paths)
    oracle["sequence_analysis"] = {
        "is_valid": [f.is_valid for f in analysis.frames],
        "angle_coefficients": analysis.angle_coefficients.tolist(),
        "curved": bool(analysis.curved),
        "transforms": [t.matrix.tolist() for t in analysis.transforms],
    }

    # 8. Negative set
    blank = np.zeros((320, 420), dtype=np.float32)
    blank_detected = detect_sources(blank)
    assert len(blank_detected) == 0
    oracle["negative_blank_detected_count"] = 0

    rng = np.random.default_rng(8)
    noise = rng.normal(20, 1, (100, 100)).astype(np.float32)
    noise_detected = detect_sources(noise)
    assert len(noise_detected) == 0
    oracle["negative_noise_detected_count"] = 0

    unrelated_img, _ = make_sky(seed=123, shape=(320, 420))
    unrelated_match = match_images(sky_img, unrelated_img)
    assert unrelated_match is None
    oracle["negative_unrelated_match_is_none"] = True

    # Save oracle data
    oracle_path = fixtures_dir / "oracle_data.json"
    with open(oracle_path, "w") as f:
        json.dump(oracle, f, indent=2)

    print(f"Generated all fixtures and saved oracle data to {oracle_path}!")


if __name__ == "__main__":
    main()
