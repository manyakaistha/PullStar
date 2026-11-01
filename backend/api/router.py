import os
import asyncio
from typing import Dict, Any, Optional, Literal
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel, Field, model_validator
from backend.services.job_manager import job_manager

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

class JobCreateRequest(BaseModel):
    input_dir: str
    output_file: Optional[str] = None
    extension_factor: float = Field(default=1.0, ge=1, le=5)
    tail_taper_strength: float = Field(default=0.0, ge=0, le=1)
    tail_angle_threshold: float = Field(default=0.0, ge=0, le=360)
    use_rotation: bool = False
    use_kalman: bool = True
    kalman_process_noise: float = 0.01
    kalman_measurement_noise: float = 2.0
    ghost_frames_per_real: int = 10
    synthetic_fade_factor: float = 0.2
    use_foreground_mask: bool = True
    fill_gaps: bool = False
    video_enabled: bool = False
    video_fps: int = Field(default=30, ge=1, le=120)
    video_slowdown: int = Field(default=1, ge=1, le=8)
    image_resolution: Literal["source", "4k", "2k", "1080p", "720p"] = "source"
    video_resolution: Literal["source", "4k", "2k", "1080p", "720p"] = "source"
    quality: Literal["high", "medium", "lossless", "prores", "hevc"] = "high"
    video_format: Literal["auto", "mp4", "mov"] = "auto"
    image_format: Literal["tiff", "png", "jpg"] = "tiff"
    video_hyperlapse: bool = False
    save_frames: bool = False
    no_stack: bool = False
    use_checkpoint: bool = True
    resume: bool = False
    sort_by_time: bool = True
    blend_mode: str = "lighten"
    polaris_x: Optional[float] = None
    polaris_y: Optional[float] = None
    star2_x: Optional[float] = None
    star2_y: Optional[float] = None
    compute_backend: Literal["auto", "cpu", "opencl"] = "auto"
    cpu_workers: Optional[int] = Field(default=None, ge=1, le=64)
    raw_noise_reduction: bool = True
    raw_exposure_ev: float = Field(default=0.0, ge=0, le=3)
    conversion_format: Literal["none", "jpg", "tiff"] = "none"
    conversion_output_dir: Optional[str] = None

    @model_validator(mode="after")
    def validate_export(self):
        if self.no_stack and not self.save_frames:
            raise ValueError("Images-only export requires save_frames")
        if self.no_stack and self.video_enabled:
            raise ValueError("Trail video requires trail creation")
        if self.video_enabled and self.quality == "prores" and self.video_format == "mp4":
            raise ValueError("ProRes requires a MOV container")
        if (self.polaris_x is None) != (self.polaris_y is None):
            raise ValueError("Both reference coordinates are required")
        if self.use_rotation and self.polaris_x is not None and (self.star2_x is None or self.star2_y is None):
            raise ValueError("Manual rotation correction requires a second reference star")
        return self

@router.post("")
def create_job(request: JobCreateRequest):
    if not os.path.isdir(request.input_dir):
        raise HTTPException(status_code=400, detail="Input directory does not exist")

    config = request.model_dump()

    # Format polaris and second star
    if request.polaris_x is not None and request.polaris_y is not None:
        config["polaris"] = (request.polaris_x, request.polaris_y)
    if request.star2_x is not None and request.star2_y is not None:
        config["second_star"] = (request.star2_x, request.star2_y)

    if not request.output_file:
        config["output_file"] = os.path.join(request.input_dir, "aligned_output.tiff")

    job_id = job_manager.create_job(config)
    job_manager.start_job(job_id)
    return {"job_id": job_id}

@router.get("/{job_id}")
def get_job(job_id: str):
    try:
        return job_manager.get_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str):
    try:
        return job_manager.cancel_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")

@router.websocket("/{job_id}/ws")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    await websocket.accept()
    if job_id not in job_manager.jobs:
        await websocket.close(code=1008)
        return

    # Send current state
    await websocket.send_json(job_manager.jobs[job_id])

    # Get main event loop
    loop = asyncio.get_running_loop()

    # Callback to push updates - this will be called from background thread
    def update_client(job_data):
        # Schedule the async send on the main event loop
        async def send():
            try:
                await websocket.send_json(job_data)
            except Exception:
                pass
        asyncio.run_coroutine_threadsafe(send(), loop)

    job_manager.subscribe(job_id, update_client)

    try:
        while True:
            # Keep connection open
            await websocket.receive_text()
    except WebSocketDisconnect:
        # Prevent memory leaks by removing the listener
        if job_id in job_manager.listeners:
            if update_client in job_manager.listeners[job_id]:
                job_manager.listeners[job_id].remove(update_client)

stars_router = APIRouter(prefix="/api/stars", tags=["stars"])

class DetectRequest(BaseModel):
    path: str
    frame_step: int = Field(default=10, ge=1, le=10000)
    sort_by_time: bool = True
    cpu_workers: Optional[int] = Field(default=None, ge=1, le=64)
    raw_noise_reduction: bool = True


@stars_router.post("/detect/start")
def start_detection(request: DetectRequest):
    if not os.path.isdir(request.path):
        raise HTTPException(status_code=400, detail="Directory not found")
    job_id = job_manager.create_job(request.model_dump(), kind="detection")
    job_manager.start_job(job_id)
    return {"job_id": job_id}

@stars_router.post("/detect")
def detect_stars(request: DetectRequest):
    if not os.path.isdir(request.path):
        raise HTTPException(status_code=400, detail="Directory not found")

    from modules.io_utils import get_image_list
    from pathlib import Path
    image_paths = get_image_list(Path(request.path), sort_by_time=request.sort_by_time)
    if not image_paths:
        raise HTTPException(status_code=400, detail="No images found")

    from modules.auto_selector import auto_detect_stars
    try:
        result = auto_detect_stars(image_paths, frame_step=request.frame_step,
                                   raw_noise_reduction=request.raw_noise_reduction)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=400, detail="Could not match at least six stars across exposures. Check focus, clouds, and sequence overlap.")

    return {
        "polaris": result.polaris,
        "second_star": result.second_star,
        "confidence": result.confidence,
        "num_inliers": result.num_inliers,
        "rotation_angle": result.rotation_angle,
        "reference_stars": result.reference_stars,
        "rotation_center": result.rotation_center,
        "method": result.method,
        "selection_mode": result.selection_mode,
        "reference_image": str(image_paths[0]),
    }
