# HTTP and WebSocket API Contract (P0-02)

This document freezes the REST and WebSocket API specifications for PullStar. It documents all routes, HTTP methods, Pydantic request/response models, status codes, WebSocket update payloads, and error conditions.

## 1. Route Summary Table

| Method | Path | Defining Source | Covering Test | Summary |
| :--- | :--- | :--- | :--- | :--- |
| `GET` | `/` | `backend/main.py:19` | `tests/test_backend_api.py:10` | Service health probe. Returns `{"status": "PullStar API is running"}`. |
| `POST` | `/api/jobs` | `backend/api/router.py:49` | `tests/test_pipeline_and_api.py:22` | Create and launch an asynchronous alignment/stacking job. |
| `GET` | `/api/jobs/{job_id}` | `backend/api/router.py:68` | `tests/test_pipeline_and_api.py:32` | Poll current job status, stage, progress, and telemetry. |
| `POST` | `/api/jobs/{job_id}/cancel`| `backend/api/router.py:75` | `tests/test_cancellation.py:16` | Request job cancellation. Idempotent on terminal jobs. |
| `WS` | `/api/jobs/{job_id}/ws` | `backend/api/router.py:82` | `tests/test_job_progress.py:12` | Live telemetry WebSocket stream pushing state snapshots. |
| `POST` | `/api/stars/detect/start` | `backend/api/router.py:144`| `tests/test_cancellation.py:105` | Start background cancellable star detection job. |
| `POST` | `/api/stars/detect` | `backend/api/router.py:152`| `tests/test_field_alignment.py:101`| Legacy synchronous star detection endpoint. |
| `POST` | `/api/images/list` | `backend/api/images_router.py:18`| `tests/test_image_delivery.py:14` | List supported image files in a directory; filters out `.live.jpg`. |
| `GET` | `/api/images/preview` | `backend/api/images_router.py:38`| `tests/test_raw_preview.py:78` | Dynamic JPEG preview thumbnail; supports ETag / 304, RAW and 16-bit. |
| `GET` | `/api/images/download` | `backend/api/images_router.py:87`| `tests/test_image_delivery.py:35` | Stream / download output files (TIFF, PNG, JPEG, MP4, MOV). |
| `GET` | `/api/images/download-sequence`| `backend/api/images_router.py:96`| `tests/test_exports.py:68` | On-the-fly uncompressed ZIP archive of exported sequence folder. |
| `POST` | `/api/images/metadata` | `backend/api/images_router.py:120`| `tests/test_image_consistency.py:18`| Read image dimensions, EXIF timestamps, and detect sequence gaps. |
| `GET` | `/api/system/compute` | `backend/api/compute_router.py:8` | `tests/test_parallel_compute.py:12` | Inspect CPU cores, memory size, and OpenCL GPU devices. |
| `GET` | `/api/mcp/info` | `backend/api/mcp_router.py:59` | `tests/test_mcp_server.py:312` | Discover MCP tools, resources, and prompts over REST. |
| `POST` | `/api/mcp/inspect` | `backend/api/mcp_router.py:89` | `tests/test_mcp_server.py:315` | REST bridge to `inspect_sequence` diagnostic analysis. |
| `POST` | `/api/mcp/recommend` | `backend/api/mcp_router.py:101` | `tests/test_mcp_server.py:318` | REST bridge to `recommend_settings` engine. |
| `POST` | `/api/mcp/evaluate-alignment`| `backend/api/mcp_router.py:113`| `tests/test_mcp_server.py:321` | REST bridge to Pass 1 alignment dry-run evaluation. |
| `POST` | `/api/mcp/compare-candidates`| `backend/api/mcp_router.py:125`| `tests/test_mcp_server.py:324` | REST bridge to candidate strategy benchmarking. |
| `POST` | `/api/mcp/evaluate-stack` | `backend/api/mcp_router.py:137` | `tests/test_mcp_server.py:327` | REST bridge to output stack quality evaluation. |

---

## 2. Request Models and Schemas

### 2.1 `JobCreateRequest` (`backend/api/router.py:10-48`)
Used in `POST /api/jobs`:
```python
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
```
**Model Invariants (`validate_export` in `router.py:38-48`):**
- `no_stack and not save_frames`: raises `ValueError("Images-only export requires save_frames")`.
- `no_stack and video_enabled`: raises `ValueError("Trail video requires trail creation")`.
- `video_enabled and quality == "prores" and video_format == "mp4"`: raises `ValueError("ProRes requires a MOV container")`.
- `(polaris_x is None) != (polaris_y is None)`: raises `ValueError("Both reference coordinates are required")`.
- `use_rotation and polaris_x is not None and (star2_x is None or star2_y is None)`: raises `ValueError("Manual rotation correction requires a second reference star")`.

### 2.2 `DetectRequest` (`backend/api/router.py:136-142`)
Used in `POST /api/stars/detect/start` and `POST /api/stars/detect`:
```python
class DetectRequest(BaseModel):
    path: str
    frame_step: int = Field(default=10, ge=1, le=10000)
    sort_by_time: bool = True
    cpu_workers: Optional[int] = Field(default=None, ge=1, le=64)
    raw_noise_reduction: bool = True
```

### 2.3 `DirectoryRequest` (`backend/api/images_router.py:13-16`)
Used in `POST /api/images/list` and `POST /api/images/metadata`:
```python
class DirectoryRequest(BaseModel):
    path: str
    sort_by_time: bool = True
```

### 2.4 Diagnostic Request Models (`backend/api/mcp_router.py:27-63`)
- `InspectRequest`: `input_dir: str`, `sort_by_time: bool = True`, `sample_frames: int = 5 (1..50)`, `raw_noise_reduction: bool = True`.
- `RecommendRequest`: `input_dir: str`, `goal: Literal["balanced", "natural", "dramatic_extended", "gap_repair", "maximum_sharpness", "trail_lapse_video", "faint_stars_boost"] = "balanced"`, `include_pass1_probe: bool = True`, `video_export: bool = False`.
- `EvaluateAlignmentRequest`: `input_dir: str`, `settings: Dict[str, Any] = {}`, `max_frames: Optional[int] = None (2..5000)`.
- `CompareCandidatesRequest`: `input_dir: str`, `candidates: Optional[List[Dict[str, Any]]] = None`, `max_frames: Optional[int] = None (2..5000)`.
- `EvaluateStackRequest`: `stack_path: str`, `reference_frame_path: Optional[str] = None`, `preview_output_path: Optional[str] = None`.

---

## 3. WebSocket and Event Payloads

Subscribed clients at `WS /api/jobs/{job_id}/ws` receive JSON dictionaries on state changes.

### Initial & Subsequent State Payload Schema
```json
{
  "id": "e2920202-...",
  "kind": "alignment",
  "config": { "...": "..." },
  "status": "running",
  "stage": "pass2",
  "progress": 0.45,
  "overall_progress": 0.65,
  "activity": "processing_frame",
  "current": 45,
  "total": 100,
  "fps": 24.5,
  "drift_x": 0.32,
  "drift_y": -0.15,
  "compute": {
    "backend": "cpu",
    "device": "CPU",
    "workers": 4,
    "fallback_reason": null
  },
  "result_path": null,
  "error": null
}
```

### Terminal Success Payload Keys (`_complete` in `backend/services/job_manager.py:92-97, 219-224`)
When `status == "completed"`:
- `overall_progress`: `1.0`
- `progress`: `1.0`
- `result_path`: `str` (path to output image or directory)
- `frames_dir`: `Optional[str]`
- `frame_count`: `Optional[int]`
- `preview_path`: `str`
- `video_path`: `Optional[str]`
- `conversion_format`: `"none" | "jpg" | "tiff"`
- `converted_files_dir`: `Optional[str]`

---

## 4. Image Preview, Download, and Archive Endpoints

### 4.1 Preview (`GET /api/images/preview`)
- **Query parameters**:
  - `path: str` (validated for extensions: `.jpg`, `.jpeg`, `.png`, `.tif`, `.tiff`, `.nef`, `.cr2`, `.cr3`, `.arw`, `.dng`)
  - `max_size: Optional[int]` (range $64 \le x \le 4096$)
- **Caching**:
  - Computes ETag: `"{abs_path}:{mtime_ns}:{size}:{max_size}"`. Returns `304 Not Modified` if `If-None-Match` header matches.
  - In-memory LRU cache: max 32 JPEG byte buffers (`_PREVIEW_CACHE_MAX = 32`).
- **Media Types**:
  - `image/jpeg` with quality 95. Unscaled source JPEG/PNG served directly via `FileResponse`.
- **Status Codes**:
  - `200`: preview generated/retrieved.
  - `304`: not modified.
  - `400`: bad request.
  - `403`: invalid file type.
  - `404`: file not found.
  - `422`: decode failure (`Unable to decode image preview`).

### 4.2 Download (`GET /api/images/download`)
- Streams file as `FileResponse` with `media_type="application/octet-stream"` and `Content-Disposition: attachment; filename="<basename>"`.
- Allows images and `.mp4` / `.mov` files.

### 4.3 Sequence Archive (`GET /api/images/download-sequence`)
- Reads `<path>/sequence.json`.
- Builds an uncompressed ZIP (`compression=zipfile.ZIP_STORED`, `allowZip64=True`) in a temporary file beside the folder.
- Background task unlinks the temporary archive immediately after HTTP delivery finishes.
- Returns `404` if `sequence.json` is missing or invalid.
