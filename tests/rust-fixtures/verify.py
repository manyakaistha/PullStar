#!/usr/bin/env python3
"""
PullStar Fixture Verification and Idempotence Harness (P0-03)

Validates all committed fixture files, verifies SHA-256 hashes against hashes.json,
checks schema conformance against schema/fixture_v1.schema.json, and verifies
numerical parity against Python oracles. Fails if committed hashes or content change.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

import cv2
import jsonschema
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.video_schedule import video_step_repeats
from backend.engine.field_alignment import analyze_field, field_crop
from mcp_server.diagnostics import evaluate_stack_image
from modules.astronomy import detect_sources, match_images
from modules.image_preview import load_raw_preview
from modules.io_utils import get_image_info, load_image

FIXTURES_DIR = Path(__file__).resolve().parent


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def verify_file_hashes() -> Dict[str, str]:
    hashes_file = FIXTURES_DIR / "hashes.json"
    if not hashes_file.exists():
        raise FileNotFoundError(f"Missing hashes.json at {hashes_file}")

    with open(hashes_file, "r") as f:
        expected_hashes: Dict[str, str] = json.load(f)

    print(f"Verifying {len(expected_hashes)} committed file hashes...")
    mismatches = []
    missing = []

    for rel_path, expected_hash in expected_hashes.items():
        full_path = FIXTURES_DIR / rel_path
        if not full_path.exists():
            missing.append(rel_path)
            continue
        actual_hash = compute_sha256(full_path)
        if actual_hash != expected_hash:
            mismatches.append((rel_path, expected_hash, actual_hash))

    if missing:
        raise AssertionError(f"Missing fixture files: {missing}")
    if mismatches:
        details = "\n".join(f"  {r}: expected {e[:8]}..., got {a[:8]}..." for r, e, a in mismatches)
        raise AssertionError(f"SHA-256 hash mismatches detected:\n{details}")

    print("All file hashes match hashes.json successfully.")
    return expected_hashes


def verify_schema_conformance(manifest: Dict[str, Any]):
    schema_file = FIXTURES_DIR / "schema" / "fixture_v1.schema.json"
    if not schema_file.exists():
        raise FileNotFoundError(f"Missing schema at {schema_file}")

    with open(schema_file, "r") as f:
        schema = json.load(f)

    print("Validating manifest.json against JSON schema version 1...")
    jsonschema.validate(instance=manifest, schema=schema)
    print("Schema validation passed.")


def verify_oracle_parity(manifest: Dict[str, Any]):
    print("Verifying oracle numerical parity against Python algorithms...")

    # 1. Standard sequence detection and field alignment
    seq_data = manifest["sequences"]["standard_5frame"]
    std_dir = FIXTURES_DIR / "images" / "standard"
    std_paths = [std_dir / f["name"] for f in seq_data["frames"]]

    for frame_meta in seq_data["frames"]:
        fpath = FIXTURES_DIR / frame_meta["relative_path"]
        img = load_image(fpath)
        pts = detect_sources(img)
        expected_pts = seq_data["detected_sources"][frame_meta["name"]]
        assert len(pts) == len(expected_pts), f"Detection count mismatch on {frame_meta['name']}"
        for p, exp in zip(pts, expected_pts):
            assert abs(p[0] - exp["x"]) < 1e-4 and abs(p[1] - exp["y"]) < 1e-4, "Centroid coordinate drift"

    # Field alignment transforms
    analysis = analyze_field(std_paths)
    crop = field_crop(analysis.transforms, seq_data["frames"][0]["size"]["width"], seq_data["frames"][0]["size"]["height"])
    exp_field = seq_data["field_alignment"]

    assert exp_field["crop"]["x_start"] == crop.x_start
    assert exp_field["crop"]["x_end"] == crop.x_end
    assert exp_field["crop"]["y_start"] == crop.y_start
    assert exp_field["crop"]["y_end"] == crop.y_end

    for t, exp_t in zip(analysis.transforms, exp_field["transforms"]):
        assert t.frame_index == exp_t["frame_index"]
        assert abs(t.dx - exp_t["dx"]) < 1e-4
        assert abs(t.dy - exp_t["dy"]) < 1e-4
        assert abs(t.rotation - exp_t["rotation"]) < 1e-4
        m_actual = t.matrix.flatten().tolist()
        for v_act, v_exp in zip(m_actual, exp_t["matrix"]):
            assert abs(v_act - v_exp) < 1e-4, "Transform matrix drift"

    # 2. Raw fixtures
    raw_dir = FIXTURES_DIR / "images" / "raw"
    emb_path = raw_dir / "embedded_preview_only.dng"
    info = get_image_info(emb_path)
    assert info["is_raw"] is True
    preview = load_raw_preview(emb_path, max_size=256)
    assert preview.shape == (128, 96, 3), f"Unexpected embedded preview shape {preview.shape}"

    # 3. Negative cases
    neg_cases = manifest["negative_cases"]
    for case_id, case in neg_cases.items():
        fpath = FIXTURES_DIR / case["frame"]["relative_path"]
        img = load_image(fpath)
        pts = detect_sources(img)
        assert len(pts) == case["expected_sources_detected"], f"Negative detection failed for {case_id}"

    # 4. Schedules
    sched_data = manifest["schedules"]["standard_synthetic_schedule"]
    sched_tuples = [(s["source_index"], s["step_time"], s["is_synthetic"]) for s in sched_data["schedule"]]
    for k, slowdown in [("slowdown_1", 1), ("slowdown_2", 2), ("slowdown_4", 4)]:
        actual_repeats = video_step_repeats(sched_tuples, slowdown=slowdown)
        expected_repeats = {int(step): count for step, count in sched_data["slowdowns"][k].items()}
        assert actual_repeats == expected_repeats, f"Schedule repeats mismatch for {k}"

    # 5. Quality evaluation
    q_data = manifest["quality_evaluations"]["standard_lighten_stack"]
    stack_path = std_dir / "synthetic_stack_preview.tiff"
    q_eval = evaluate_stack_image(stack_path, reference_frame_path=std_paths[0])
    assert abs(q_eval["overall_quality_score"] - q_data["overall_quality_score"]) < 1e-4
    assert q_eval["verdict"] == q_data["verdict"]

    print("Oracle parity verified successfully.")


def check_idempotence():
    print("Testing fixture generation idempotence...")
    from generate import generate_manifest

    # Re-run generate_manifest and check if it yields identical JSON
    manifest_path = FIXTURES_DIR / "manifest.json"
    with open(manifest_path, "r") as f:
        committed = json.load(f)

    regenerated = generate_manifest()
    # Normalize created_at for deterministic comparison
    regenerated["created_at"] = committed["created_at"]

    committed_str = json.dumps(committed, sort_keys=True, indent=2)
    regenerated_str = json.dumps(regenerated, sort_keys=True, indent=2)

    if committed_str != regenerated_str:
        raise AssertionError("Idempotence failure: re-generated manifest differs from committed manifest!")

    print("Idempotence confirmed: second generation produces byte-identical manifest.")


def main():
    parser = argparse.ArgumentParser(description="PullStar Fixture Verifier")
    parser.add_argument("--idempotence", action="store_true", default=True, help="Run idempotence test")
    args = parser.parse_args()

    manifest_file = FIXTURES_DIR / "manifest.json"
    if not manifest_file.exists():
        print(f"Error: manifest.json not found at {manifest_file}", file=sys.stderr)
        sys.exit(1)

    with open(manifest_file, "r") as f:
        manifest = json.load(f)

    try:
        verify_file_hashes()
        verify_schema_conformance(manifest)
        verify_oracle_parity(manifest)
        if args.idempotence:
            check_idempotence()
        print("\nAll PullStar P0-03 fixture verification checks passed successfully!")
    except Exception as e:
        print(f"\nVerification FAILED: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
