"""
FastAPI Router exposing MCP Server diagnostics, settings recommendation,
alignment candidate comparison, and stack quality evaluation over REST.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from mcp_server.diagnostics import (
    compare_alignment_candidates_data,
    evaluate_alignment_config,
    evaluate_stack_image,
    inspect_sequence_data,
    recommend_stack_settings,
)
from mcp_server.server import mcp

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


class InspectRequest(BaseModel):
    input_dir: str
    sort_by_time: bool = True
    sample_frames: int = Field(default=5, ge=1, le=50)
    raw_noise_reduction: bool = True


class RecommendRequest(BaseModel):
    input_dir: str
    goal: Literal[
        "balanced",
        "natural",
        "dramatic_extended",
        "gap_repair",
        "maximum_sharpness",
        "trail_lapse_video",
        "faint_stars_boost",
    ] = "balanced"
    include_pass1_probe: bool = True
    video_export: bool = False


class EvaluateAlignmentRequest(BaseModel):
    input_dir: str
    settings: Dict[str, Any] = Field(default_factory=dict)
    max_frames: Optional[int] = Field(default=None, ge=2, le=5000)


class CompareCandidatesRequest(BaseModel):
    input_dir: str
    candidates: Optional[List[Dict[str, Any]]] = None
    max_frames: Optional[int] = Field(default=None, ge=2, le=5000)


class EvaluateStackRequest(BaseModel):
    stack_path: str
    reference_frame_path: Optional[str] = None
    preview_output_path: Optional[str] = None


@router.get("/info")
async def get_mcp_info() -> Dict[str, Any]:
    """Return metadata about the PullStar MCP server, its tools, resources, and prompts."""
    tools = await mcp.list_tools()
    resources = await mcp.list_resources()
    prompts = await mcp.list_prompts()
    return {
        "name": "pullstar",
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": getattr(t, "input_schema", getattr(t, "inputSchema", None)),
            }
            for t in tools
        ],
        "resources": [
            {
                "uri": str(r.uri),
                "name": r.name,
                "description": r.description,
            }
            for r in resources
        ],
        "prompts": [
            {
                "name": p.name,
                "description": p.description,
            }
            for p in prompts
        ],
    }


@router.post("/inspect")
def inspect_sequence_endpoint(request: InspectRequest) -> Dict[str, Any]:
    try:
        return inspect_sequence_data(
            input_dir=request.input_dir,
            sort_by_time=request.sort_by_time,
            sample_frames=request.sample_frames,
            raw_noise_reduction=request.raw_noise_reduction,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/recommend")
def recommend_settings_endpoint(request: RecommendRequest) -> Dict[str, Any]:
    try:
        return recommend_stack_settings(
            input_dir=request.input_dir,
            goal=request.goal,
            include_pass1_probe=request.include_pass1_probe,
            video_export=request.video_export,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/evaluate-alignment")
def evaluate_alignment_endpoint(request: EvaluateAlignmentRequest) -> Dict[str, Any]:
    try:
        return evaluate_alignment_config(
            input_dir=request.input_dir,
            settings=request.settings,
            max_frames=request.max_frames,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/compare-candidates")
def compare_candidates_endpoint(request: CompareCandidatesRequest) -> Dict[str, Any]:
    try:
        return compare_alignment_candidates_data(
            input_dir=request.input_dir,
            candidates=request.candidates,
            max_frames=request.max_frames,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/evaluate-stack")
def evaluate_stack_endpoint(request: EvaluateStackRequest) -> Dict[str, Any]:
    try:
        return evaluate_stack_image(
            stack_path=request.stack_path,
            reference_frame_path=request.reference_frame_path,
            preview_output_path=request.preview_output_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
