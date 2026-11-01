"""
End-to-end tests for the PullStar Model Context Protocol (MCP) server,
diagnostics engine, settings optimizer, and FastAPI MCP bridge endpoints.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Tuple

import cv2
import mcp
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from mcp_server.server import create_mcp_server, mcp as default_mcp_server
from test_astronomy import make_sky
from tests.test_field_alignment import observed_motion, write_sequence


def _call_mcp_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Invoke a tool on the MCP server via `mcp.Client` and parse its JSON response."""

    async def _run():
        async with mcp.Client(default_mcp_server) as client:
            result = await client.call_tool(tool_name, arguments)
            assert not result.is_error, f"MCP tool {tool_name} failed: {result}"
            assert len(result.content) > 0
            text = result.content[0].text
            return json.loads(text)

    return asyncio.run(_run())


def _create_sequence_with_gap_and_foreground(tmp_path: Path) -> Tuple[Path, np.ndarray]:
    """
    Create a realistic 12-frame synthetic star sequence with:
    - Rotating star field with camera wobble
    - A deliberate 120-second timestamp gap between frames 4 and 5 (vs 20s median interval)
    """
    image, stars = make_sky()
    seq_dir = tmp_path / "seq"
    seq_dir.mkdir(parents=True, exist_ok=True)

    base_time = 1_700_000_000.0
    # 12 frames (required by analyze_field >= 10 frames) with a 120s gap between index 4 and 5
    frame_times = [
        0.0,
        20.0,
        40.0,
        60.0,
        80.0,
        200.0,
        220.0,
        240.0,
        260.0,
        280.0,
        300.0,
        320.0,
    ]

    for index, dt in enumerate(frame_times):
        motion = cv2.getRotationMatrix2D((-280, -150), (dt / 20.0) * 0.3, 1.0)
        observed = observed_motion(motion, index)
        frame = cv2.warpAffine(image, observed, (420, 320))
        if frame.ndim == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        out_path = seq_dir / f"frame_{index:03d}.png"
        cv2.imwrite(str(out_path), frame)
        ts = base_time + dt
        os.utime(out_path, (ts, ts))

    return seq_dir, stars


def test_mcp_protocol_discovery():
    """Verify MCP server exposes all expected tools, resources, and prompts via MCP Client."""

    async def _check():
        server = create_mcp_server()
        async with mcp.Client(server) as client:
            tools_res = await client.list_tools()
            tool_names = {t.name for t in tools_res.tools}
            expected_tools = {
                "inspect_sequence",
                "detect_and_analyze_stars",
                "get_hardware_capabilities",
                "recommend_settings",
                "evaluate_alignment_settings",
                "compare_alignment_candidates",
                "render_preview_stack",
                "create_stack",
                "auto_tune_and_stack",
                "evaluate_stack_quality",
                "render_annotated_preview",
                "start_stack_job",
                "get_job_status",
                "cancel_job",
                "list_jobs",
            }
            assert expected_tools.issubset(tool_names)

            resources_res = await client.list_resources()
            resource_uris = {str(r.uri) for r in resources_res.resources}
            assert "staraligner://system/capabilities" in resource_uris
            assert "staraligner://config/defaults" in resource_uris
            assert "staraligner://guide/parameter-tuning" in resource_uris
            assert "staraligner://jobs/active" in resource_uris

            defaults_read = await client.read_resource("staraligner://config/defaults")
            defaults_payload = json.loads(defaults_read.contents[0].text)
            assert "tracking" in defaults_payload
            assert "stacking" in defaults_payload

            guide_read = await client.read_resource("staraligner://guide/parameter-tuning")
            assert "Parameter Tuning Playbook" in guide_read.contents[0].text

            prompts_res = await client.list_prompts()
            prompt_names = {p.name for p in prompts_res.prompts}
            assert "find_optimal_stack_settings" in prompt_names
            assert "create_verified_stack_workflow" in prompt_names

            prompt_msg = await client.get_prompt(
                "find_optimal_stack_settings",
                {"input_dir": "/tmp/stars", "goal": "dramatic_extended"},
            )
            assert len(prompt_msg.messages) > 0
            assert "recommend_settings" in prompt_msg.messages[0].content.text

    asyncio.run(_check())


def test_mcp_inspect_detect_and_recommend_settings(tmp_path):
    """Verify sequence inspection, gap detection, star detection, and settings recommendation."""
    seq_dir, _ = _create_sequence_with_gap_and_foreground(tmp_path)

    # Also drop a dummy previous output file in seq_dir to ensure filter_source_images ignores it
    dummy_out = seq_dir / "aligned_star_trails.tiff"
    cv2.imwrite(str(dummy_out), np.zeros((100, 100, 3), dtype=np.uint8))

    inspection = _call_mcp_tool("inspect_sequence", {"input_dir": str(seq_dir)})
    assert inspection["num_images"] == 12
    assert "aligned_star_trails.tiff" in inspection["skipped_non_source_files"]
    assert inspection["image_info"]["width"] == 420
    assert inspection["image_info"]["height"] == 320
    assert inspection["timeline"]["gap_detected"] is True
    assert inspection["timeline"]["gap_count"] == 1
    assert inspection["timeline"]["gaps"][0]["frame_index"] == 5
    assert inspection["scene_analysis"]["star_count_summary"]["max"] >= 15

    star_analysis = _call_mcp_tool(
        "detect_and_analyze_stars",
        {"input_dir": str(seq_dir), "frame_step": 3},
    )
    assert star_analysis["auto_field_detection"]["succeeded"] is True
    assert star_analysis["auto_field_detection"]["num_inliers"] >= 10
    assert star_analysis["auto_field_detection"]["pole_in_frame"] is False
    assert star_analysis["recommended_alignment_mode"] == "star_field"
    assert len(star_analysis["manual_tracking_candidates"]["candidates"]) >= 3

    rec_balanced = _call_mcp_tool(
        "recommend_settings",
        {"input_dir": str(seq_dir), "goal": "balanced", "include_pass1_probe": True},
    )
    settings = rec_balanced["recommended_settings"]
    assert settings["polaris_x"] is None
    assert settings["polaris_y"] is None
    assert settings["fill_gaps"] is True
    assert settings["use_foreground_mask"] is True
    assert settings["blend_mode"] == "lighten"
    assert rec_balanced["pass1_probe"]["alignment_score"] >= 75.0

    rec_extended = _call_mcp_tool(
        "recommend_settings",
        {"input_dir": str(seq_dir), "goal": "dramatic_extended", "include_pass1_probe": False},
    )
    assert rec_extended["recommended_settings"]["extension_factor"] >= 1.5
    assert rec_extended["recommended_settings"]["use_foreground_mask"] is True


def test_mcp_compare_candidates_and_manual_kalman_tuning(tmp_path):
    """Verify Pass 1 dry-run evaluation and side-by-side comparison of auto vs manual strategies."""
    seq_dir = tmp_path / "wobble_seq"
    seq_dir.mkdir(parents=True, exist_ok=True)
    write_sequence(seq_dir)

    comp = _call_mcp_tool("compare_alignment_candidates", {"input_dir": str(seq_dir)})
    assert comp["candidate_count"] >= 2
    assert comp["best_candidate"] is not None
    assert comp["best_alignment_score"] >= 75.0

    # Test manual tracking with custom Kalman noise & search window parameters via evaluate_alignment_settings
    cands = comp["ranked_candidates"]
    manual_cand = next(c for c in cands if c["name"].startswith("manual_"))
    px = manual_cand["settings"]["polaris_x"]
    py = manual_cand["settings"]["polaris_y"]

    manual_eval = _call_mcp_tool(
        "evaluate_alignment_settings",
        {
            "input_dir": str(seq_dir),
            "polaris_x": px,
            "polaris_y": py,
            "use_kalman": True,
            "kalman_process_noise": 0.05,
            "kalman_measurement_noise": 3.5,
            "search_window_size": 120,
            "max_jump_threshold": 65.0,
        },
    )
    assert manual_eval["mode"] == "manual_tracking"
    assert manual_eval["mode_details"]["kalman_process_noise"] == 0.05
    assert manual_eval["mode_details"]["kalman_measurement_noise"] == 3.5
    assert manual_eval["mode_details"]["search_window_size"] == 120
    assert manual_eval["valid_frame_ratio"] > 0.5


def test_mcp_preview_create_stack_and_auto_tune(tmp_path):
    """Verify preview stack rendering, full stack creation, quality evaluation, and auto_tune_and_stack."""
    seq_dir, _ = _create_sequence_with_gap_and_foreground(tmp_path)

    # 1. Render a fast downscaled preview stack (keep max_frames >= 10 for star_field mode)
    preview_out = tmp_path / "preview_stack.tiff"
    preview_res = _call_mcp_tool(
        "render_preview_stack",
        {
            "input_dir": str(seq_dir),
            "output_file": str(preview_out),
            "fill_gaps": True,
            "extension_factor": 1.3,
            "max_dimension": 320,
            "max_frames": 12,
        },
    )
    assert Path(preview_res["result_path"]).exists()
    assert Path(preview_res["preview_jpeg_path"]).exists()
    assert preview_res["preview_mode"]["scale_factor"] < 1.0
    assert preview_res["quality_report"]["overall_quality_score"] > 40.0

    # 2. Run auto_tune_and_stack end-to-end
    final_out = tmp_path / "auto_tuned_stack.tiff"
    auto_res = _call_mcp_tool(
        "auto_tune_and_stack",
        {
            "input_dir": str(seq_dir),
            "output_file": str(final_out),
            "goal": "balanced",
            "verify_and_refine": True,
        },
    )
    stack_result = auto_res["stack_result"]
    assert Path(stack_result["result_path"]).exists()
    assert Path(stack_result["preview_jpeg_path"]).exists()
    assert stack_result["num_images_stacked"] == 12
    assert stack_result["quality_report"]["overall_quality_score"] >= 50.0

    # 3. Render an annotated preview of the first frame
    first_frame = seq_dir / "frame_000.png"
    annotated_out = tmp_path / "annotated_first.jpg"
    ann_res = _call_mcp_tool(
        "render_annotated_preview",
        {
            "image_path": str(first_frame),
            "output_path": str(annotated_out),
            "annotate_stars": True,
            "show_foreground_mask": True,
        },
    )
    assert Path(ann_res["preview_path"]).exists()
    assert ann_res["annotated_stars_count"] >= 10


def test_mcp_async_job_lifecycle(tmp_path):
    """Verify background job creation, polling, and listing through MCP tools."""
    seq_dir = tmp_path / "async_seq"
    seq_dir.mkdir(parents=True, exist_ok=True)
    write_sequence(seq_dir)
    out_file = tmp_path / "async_out.tiff"

    started = _call_mcp_tool(
        "start_stack_job",
        {
            "input_dir": str(seq_dir),
            "output_file": str(out_file),
        },
    )
    job_id = started["job_id"]
    assert job_id

    jobs_list = _call_mcp_tool("list_jobs", {})
    assert any(j["id"] == job_id for j in jobs_list["jobs"])

    deadline = time.time() + 25.0
    status_data = None
    while time.time() < deadline:
        status_data = _call_mcp_tool("get_job_status", {"job_id": job_id})
        if status_data["status"] in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.1)

    assert status_data is not None
    assert status_data["status"] == "completed", f"Job failed: {status_data}"
    assert Path(status_data["result_path"]).exists()


def test_fastapi_mcp_bridge_endpoints(tmp_path):
    """Verify the FastAPI /api/mcp/* endpoints work cleanly alongside the MCP server."""
    seq_dir, _ = _create_sequence_with_gap_and_foreground(tmp_path)
    client = TestClient(app)

    info_res = client.get("/api/mcp/info")
    assert info_res.status_code == 200
    info_json = info_res.json()
    assert info_json["name"] == "pullstar"
    assert any(t["name"] == "recommend_settings" for t in info_json["tools"])

    rec_res = client.post(
        "/api/mcp/recommend",
        json={"input_dir": str(seq_dir), "goal": "balanced", "include_pass1_probe": True},
    )
    assert rec_res.status_code == 200
    rec_json = rec_res.json()
    assert rec_json["recommended_settings"]["fill_gaps"] is True
    assert rec_json["pass1_probe"]["alignment_score"] >= 75.0


def test_mcp_images_only_export_uses_selected_format(tmp_path):
    seq_dir = tmp_path / "frames"
    seq_dir.mkdir()
    write_sequence(seq_dir)
    destination = tmp_path / "aligned-png"
    result = _call_mcp_tool("create_stack", {
        "input_dir": str(seq_dir), "output_file": str(destination),
        "save_frames": True, "no_stack": True, "image_format": "png",
        "use_checkpoint": False,
    })
    assert len(list(destination.glob("*.png"))) == 12
    assert result["exports"]["frame_count"] == 12
    assert result["exports"]["no_stack"] is True
    assert result["quality_report"] is None


def test_mcp_async_rejects_invalid_export_combination(tmp_path):
    async def check():
        async with mcp.Client(default_mcp_server) as client:
            result = await client.call_tool("start_stack_job", {
                "input_dir": str(tmp_path), "no_stack": True,
                "save_frames": True, "video_enabled": True,
            })
            assert result.is_error
            assert "Trail video requires trail creation" in result.content[0].text
    asyncio.run(check())
