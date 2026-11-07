#!/usr/bin/env python3
"""
PullStar Deterministic Fixture Generator (P0-03)

Uses the actual PullStar Python implementation as the oracle to generate
deterministic, small (<5MB total) synthetic images and portable JSON ground-truth
fixtures with schema version 1.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np
import tifffile
from PIL import Image

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.video_schedule import video_step_repeats
from backend.engine.field_alignment import analyze_field, field_crop
from mcp_server.diagnostics import evaluate_stack_image
from modules.astronomy import detect_sources, match_images
from modules.image_preview import load_raw_preview
from modules.io_utils import get_image_info, load_image
from modules.tracker import FrameTracking, TrackingResult, TrackingStatus
from modules.transform import (
    calculate_common_crop,
    calculate_transforms_from_tracking,
)

FIXTURES_DIR = Path(__file__).resolve().parent
IMAGES_DIR = FIXTURES_DIR / "images"
STD_DIR = IMAGES_DIR / "standard"
RAW_DIR = IMAGES_DIR / "raw"
NEG_DIR = IMAGES_DIR / "negative"


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def make_synthetic_sky(
    seed: int = 42,
    shape: Tuple[int, int] = (240, 320),
    num_stars: int = 28,
) -> Tuple[np.ndarray, np.ndarray]:
    """Generate a clean synthetic starfield with Gaussian PSF."""
    rng = np.random.default_rng(seed)
    height, width = shape
    stars = rng.uniform((30, 30), (width - 30, height - 30), (num_stars, 2))
    yy, xx = np.indices(shape)
    image = rng.normal(15.0, 1.0, shape)
    peaks = rng.uniform(80.0, 220.0, len(stars))
    for (x, y), peak in zip(stars, peaks):
        image += peak * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.5 ** 2))
    return np.clip(image, 0, 255).astype(np.float32), stars


def write_standard_sequence() -> Tuple[List[Path], np.ndarray]:
    STD_DIR.mkdir(parents=True, exist_ok=True)
    base_image, stars = make_synthetic_sky(seed=42, shape=(240, 320), num_stars=28)
    height, width = base_image.shape
    paths = []

    for index in range(5):
        angle_deg = index * 0.25
        motion = cv2.getRotationMatrix2D((-150, -100), angle_deg, 1.0)
        sign = 1 if index % 2 else -1
        motion[:2, 2] += sign * np.array([1.2, -0.8])

        frame = cv2.warpAffine(base_image, motion, (width, height), borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        u8_frame = np.clip(frame, 0, 255).astype(np.uint8)

        if index == 0:
            jpg_path = STD_DIR / "frame_00.jpg"
            cv2.imwrite(str(jpg_path), u8_frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
            tiff8_path = STD_DIR / "frame_00_8bit.tiff"
            tifffile.imwrite(str(tiff8_path), u8_frame)
            tiff16_path = STD_DIR / "frame_00_16bit.tiff"
            u16_frame = (u8_frame.astype(np.uint16) * 257)
            tifffile.imwrite(str(tiff16_path), u16_frame)

        png_path = STD_DIR / f"frame_{index:02d}.png"
        cv2.imwrite(str(png_path), u8_frame)
        paths.append(png_path)

    return paths, stars


def write_dark_cfa_dng(path: Path, shift=(0, 0), seed: int = 28) -> np.ndarray:
    """Generate a deterministic 10-bit CFA raw image saved as DNG with 35 stars."""
    rng = np.random.default_rng(seed)
    height, width = 384, 512
    stars = rng.uniform((30, 30), (width - 45, height - 45), (35, 2)) + shift
    yy, xx = np.indices((height, width))
    signal = np.full((height, width), 4.0)
    for x, y in stars:
        signal += 90 * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.6 ** 2))

    sensor = np.round(64 + signal + rng.normal(0, 0.7, signal.shape)).astype(np.uint16)
    sensor[-12:] = 950
    identity = (1, 1, 0, 1, 0, 1, 0, 1, 1, 1, 0, 1, 0, 1, 0, 1, 1, 1)
    tags = [
        (271, "s", 0, "PullStar-Test", False),
        (272, "s", 0, "Dark CFA", False),
        (274, "H", 1, 1, False),
        (33421, "H", 2, (2, 2), False),
        (33422, "B", 4, (1, 2, 0, 1), False),
        (50706, "B", 4, (1, 4, 0, 0), False),
        (50707, "B", 4, (1, 1, 0, 0), False),
        (50708, "s", 0, "Dark CFA", False),
        (50713, "H", 2, (2, 2), False),
        (50714, "2I", 4, (64, 1) * 4, False),
        (50717, "I", 1, 1023, False),
        (50721, "2i", 9, identity, False),
        (50728, "2I", 3, (3, 5, 1, 1, 3, 5), False),
        (50778, "H", 1, 21, False),
    ]
    tifffile.imwrite(str(path), sensor, photometric=32803, metadata=None, extratags=tags)
    return stars


def write_raw_fixtures() -> List[Path]:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    shifts = [(0.0, 0.0), (2.0, -1.0), (4.0, -2.0)]
    for i, shift in enumerate(shifts):
        dng_path = RAW_DIR / f"dark_cfa_{i:02d}.dng"
        write_dark_cfa_dng(dng_path, shift=shift, seed=28)
        paths.append(dng_path)

    # Embedded preview only DNG
    emb_path = RAW_DIR / "embedded_preview_only.dng"
    rgb = np.full((96, 128, 3), 40, dtype=np.uint8)
    rgb[10:30, 10:30] = (240, 30, 30)
    rgb[60:80, 90:110] = (30, 240, 30)
    orientation = 6  # Rotate 90 CW

    preview = Image.fromarray(rgb)
    exif = Image.Exif()
    exif[274] = orientation
    buf = BytesIO()
    preview.save(buf, format="JPEG", quality=95, exif=exif)
    jpeg_bytes = buf.getvalue()

    tags = [
        (271, "s", 0, "TestPreview", False),
        (272, "s", 0, "Preview camera", False),
        (274, "H", 1, orientation, False),
        (50706, "B", 4, (1, 4, 0, 0), False),
        (50707, "B", 4, (1, 1, 0, 0), False),
        (50708, "s", 0, "Preview camera", False),
        (50714, "H", 1, 0, False),
        (50717, "I", 1, 65535, False),
        (50721, "2i", 9, (1, 1, 0, 1, 0, 1, 0, 1, 1, 1, 0, 1, 0, 1, 0, 1, 1, 1), False),
        (50728, "2I", 3, (1, 1, 1, 1, 1, 1), False),
        (50778, "H", 1, 21, False),
    ]

    with tifffile.TiffWriter(str(emb_path)) as writer:
        writer.write(rgb.astype(np.uint16) * 257, photometric=34892, metadata=None, extratags=tags, subifds=1)
        writer.write(np.asarray(preview), photometric="rgb", subfiletype=1, metadata=None)

    offset = emb_path.stat().st_size
    with emb_path.open("ab") as f:
        f.write(jpeg_bytes)

    with tifffile.TiffFile(str(emb_path), mode="r+") as tiff:
        tiff.pages[0].tags[259].overwrite(52546)  # Undecodable raw strip
        page = tiff.pages[0].pages[0]
        page.tags[259].overwrite(7)  # JPEG
        page.tags[273].overwrite(offset)
        page.tags[279].overwrite(len(jpeg_bytes))

    paths.append(emb_path)
    return paths


def write_negative_fixtures() -> List[Path]:
    NEG_DIR.mkdir(parents=True, exist_ok=True)
    paths = []

    # 1. Blank zeros
    blank = np.zeros((240, 320), dtype=np.uint8)
    p_blank = NEG_DIR / "blank_zeros.png"
    cv2.imwrite(str(p_blank), blank)
    paths.append(p_blank)

    # 2. Pure noise
    rng = np.random.default_rng(999)
    noise = np.clip(rng.normal(25, 4, (240, 320)), 0, 255).astype(np.uint8)
    p_noise = NEG_DIR / "pure_noise.png"
    cv2.imwrite(str(p_noise), noise)
    paths.append(p_noise)

    # 3. Unrelated field
    unrelated, _ = make_synthetic_sky(seed=7777, shape=(240, 320), num_stars=30)
    p_unrel = NEG_DIR / "unrelated_field.png"
    cv2.imwrite(str(p_unrel), unrelated.astype(np.uint8))
    paths.append(p_unrel)

    # 4. Hot pixels only (single pixel spikes, not Gaussian PSF)
    hot = np.zeros((240, 320), dtype=np.uint8)
    hot[30, 40] = 255
    hot[180, 260] = 255
    hot[120, 150] = 255
    p_hot = NEG_DIR / "hot_pixels_only.png"
    cv2.imwrite(str(p_hot), hot)
    paths.append(p_hot)

    # 5. Dim streaked sources
    dim = np.full((240, 320), 10, dtype=np.uint8)
    cv2.line(dim, (50, 50), (90, 55), 35, 1)
    cv2.line(dim, (180, 120), (220, 125), 35, 1)
    p_dim = NEG_DIR / "dim_streaked_sources.png"
    cv2.imwrite(str(p_dim), dim)
    paths.append(p_dim)

    return paths


def extract_frame_metadata(path: Path, index: int) -> Dict[str, Any]:
    info = get_image_info(path)
    rel_path = str(path.relative_to(FIXTURES_DIR))
    sha = compute_sha256(path)

    encoding = "unsigned-16" if info["dtype"] == "uint16" else "unsigned-8"
    if info["is_raw"]:
        encoding = "unsigned-16"
    color = "bgr" if info["channels"] == 3 else "gray"

    orientation_map = {
        1: "normal",
        2: "flip-horizontal",
        3: "rotate-180",
        4: "flip-vertical",
        5: "transpose",
        6: "rotate-90",
        7: "transverse",
        8: "rotate-270",
    }
    orientation_str = orientation_map.get(info.get("orientation", 1), "normal")

    return {
        "index": index,
        "name": path.name,
        "relative_path": rel_path,
        "size": {"width": info["width"], "height": info["height"]},
        "encoding": encoding,
        "color": color,
        "orientation": orientation_str,
        "timestamp_seconds": None,
        "sha256": sha,
    }


def generate_manifest() -> Dict[str, Any]:
    print("Generating standard sequence...")
    std_paths, std_stars = write_standard_sequence()

    print("Generating raw fixtures...")
    raw_paths = write_raw_fixtures()

    print("Generating negative fixtures...")
    neg_paths = write_negative_fixtures()

    # --- Oracle evaluations for standard sequence ---
    std_frames_meta = [extract_frame_metadata(p, i) for i, p in enumerate(std_paths)]

    # Detections per frame
    detected_sources = {}
    for p in std_paths:
        img = load_image(p)
        pts = detect_sources(img)
        detected_sources[p.name] = [{"x": float(pt[0]), "y": float(pt[1])} for pt in pts]

    # Field alignment analysis
    print("Running analyze_field oracle...")
    analysis = analyze_field(std_paths)
    crop = field_crop(analysis.transforms, std_frames_meta[0]["size"]["width"], std_frames_meta[0]["size"]["height"])

    field_transforms = []
    for t in analysis.transforms:
        m = t.matrix.flatten().tolist()
        field_transforms.append({
            "frame_index": t.frame_index,
            "dx": float(t.dx),
            "dy": float(t.dy),
            "rotation": float(t.rotation),
            "matrix": [float(v) for v in m],
            "is_valid": bool(t.is_valid),
        })

    field_alignment_data = {
        "transforms": field_transforms,
        "crop": {
            "x_start": int(crop.x_start),
            "x_end": int(crop.x_end),
            "y_start": int(crop.y_start),
            "y_end": int(crop.y_end),
            "width": int(crop.width),
            "height": int(crop.height),
        },
        "skipped_frames": [int(idx) for idx in analysis.skipped_frames],
    }

    # Manual tracking oracle (using known first two star centroids)
    ref_polaris = (float(std_stars[0][0]), float(std_stars[0][1]))
    ref_star2 = (float(std_stars[1][0]), float(std_stars[1][1]))

    manual_trackings = []
    for i, t in enumerate(analysis.transforms):
        pt1 = (ref_polaris[0] + t.dx, ref_polaris[1] + t.dy)
        pt2 = (ref_star2[0] + t.dx, ref_star2[1] + t.dy)
        manual_trackings.append(
            FrameTracking(
                frame_index=i,
                polaris=TrackingResult(status=TrackingStatus.SUCCESS, centroid=pt1, confidence=1.0, blob_area=15, max_brightness=150.0),
                second_star=TrackingResult(status=TrackingStatus.SUCCESS, centroid=pt2, confidence=1.0, blob_area=14, max_brightness=140.0),
            )
        )

    manual_transforms_raw = calculate_transforms_from_tracking(manual_trackings, use_rotation=True)
    manual_crop_raw = calculate_common_crop(
        manual_transforms_raw,
        std_frames_meta[0]["size"]["width"],
        std_frames_meta[0]["size"]["height"],
    )

    manual_transforms = []
    for t in manual_transforms_raw:
        m = t.matrix.flatten().tolist()
        manual_transforms.append({
            "frame_index": t.frame_index,
            "dx": float(t.dx),
            "dy": float(t.dy),
            "rotation": float(t.rotation),
            "matrix": [float(v) for v in m],
            "is_valid": bool(t.is_valid),
        })

    manual_tracking_data = {
        "polaris": {"x": ref_polaris[0], "y": ref_polaris[1]},
        "second_star": {"x": ref_star2[0], "y": ref_star2[1]},
        "transforms": manual_transforms,
        "crop": {
            "x_start": int(manual_crop_raw.x_start),
            "x_end": int(manual_crop_raw.x_end),
            "y_start": int(manual_crop_raw.y_start),
            "y_end": int(manual_crop_raw.y_end),
            "width": int(manual_crop_raw.width),
            "height": int(manual_crop_raw.height),
        },
    }

    # Negative cases evaluation
    neg_evals = {}
    for p in neg_paths:
        frame_meta = extract_frame_metadata(p, 0)
        img = load_image(p)
        detected = detect_sources(img)
        std_img = load_image(std_paths[0])
        match = match_images(std_img, img)

        neg_evals[p.stem] = {
            "description": f"Negative test case: {p.stem}",
            "frame": frame_meta,
            "expected_sources_detected": len(detected),
            "expected_match_valid": match is not None,
            "rejection_reason": "No stellar consensus possible on non-star input" if match is None else "",
        }

    # Schedules oracle
    synthetic_schedule = [
        (0, 0.0, False),
        (0, 0.5, True),
        (1, 1.0, False),
        (1, 1.5, True),
        (2, 2.0, False),
    ]
    schedule_data = {
        "standard_synthetic_schedule": {
            "schedule": [
                {"source_index": s[0], "step_time": float(s[1]), "is_synthetic": s[2]}
                for s in synthetic_schedule
            ],
            "slowdowns": {
                "slowdown_1": {str(k): v for k, v in video_step_repeats(synthetic_schedule, slowdown=1).items()},
                "slowdown_2": {str(k): v for k, v in video_step_repeats(synthetic_schedule, slowdown=2).items()},
                "slowdown_4": {str(k): v for k, v in video_step_repeats(synthetic_schedule, slowdown=4).items()},
                "hyperlapse": {str(k): v for k, v in video_step_repeats(synthetic_schedule, slowdown=4, hyperlapse=True).items()},
            },
        }
    }

    # Quality evaluation oracle on stacked standard sequence
    print("Evaluating stack quality oracle...")
    stack = np.zeros_like(load_image(std_paths[0]))
    for p in std_paths:
        stack = np.maximum(stack, load_image(p))
    stack_path = STD_DIR / "synthetic_stack_preview.tiff"
    tifffile.imwrite(str(stack_path), stack)

    eval_result = evaluate_stack_image(stack_path, reference_frame_path=std_paths[0])
    tm = eval_result.get("trail_metrics", {})
    br = eval_result.get("brightness", {})
    quality_evaluations = {
        "standard_lighten_stack": {
            "overall_quality_score": float(eval_result["overall_quality_score"]),
            "verdict": str(eval_result["verdict"]),
            "clipping_fraction": float(tm.get("clipping_fraction", 0.0)),
            "dynamic_range_db": float(br.get("dynamic_range_db", 0.0)),
            "trail_coverage_fraction": float(tm.get("trail_coverage_fraction", 0.0)),
            "trail_continuity_score": float(tm.get("trail_continuity_score", 1.0)),
            "tuning_suggestions": [str(s) for s in eval_result.get("tuning_suggestions", [])],
        }
    }

    manifest = {
        "schema_version": 1,
        "generator": "tests/rust-fixtures/generate.py (oracle)",
        "created_at": "2026-11-07T12:00:00Z",
        "sequences": {
            "standard_5frame": {
                "description": "5-frame synthetic 240x320 PNG sequence with slight wobble and rotation",
                "frames": std_frames_meta,
                "detected_sources": detected_sources,
                "field_alignment": field_alignment_data,
                "manual_tracking": manual_tracking_data,
            }
        },
        "negative_cases": neg_evals,
        "schedules": schedule_data,
        "quality_evaluations": quality_evaluations,
    }

    return manifest


def main():
    print("Starting PullStar fixture generation...")
    manifest = generate_manifest()

    manifest_path = FIXTURES_DIR / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
    print(f"Manifest written to {manifest_path}")

    # Generate hashes.json for all files under tests/rust-fixtures
    hashes = {}
    for root, _, files in os.walk(FIXTURES_DIR):
        for f in sorted(files):
            if f in ("hashes.json", ".DS_Store"):
                continue
            fpath = Path(root) / f
            rel = str(fpath.relative_to(FIXTURES_DIR))
            hashes[rel] = compute_sha256(fpath)

    hashes_path = FIXTURES_DIR / "hashes.json"
    with open(hashes_path, "w") as f:
        json.dump(hashes, f, indent=2, sort_keys=True)
    print(f"Hashes written to {hashes_path} ({len(hashes)} files hashed)")

    # Print total directory size
    total_bytes = sum(p.stat().st_size for p in FIXTURES_DIR.rglob("*") if p.is_file())
    print(f"Total fixtures size: {total_bytes / (1024*1024):.2f} MB")
    print("Generation complete!")


if __name__ == "__main__":
    main()
