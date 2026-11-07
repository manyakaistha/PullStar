# Model Context Protocol (MCP) Contract (P0-02)

This document freezes the specification for PullStar's Model Context Protocol (MCP) server. It inventories all 15 tools, 4 resources (including legacy `staraligner://` URI scheme), 2 prompts, transport requirements, and stdout discipline.

## 1. Protocol Metadata & Transports

- **Server Identifier**: `"pullstar"` (`mcp_server/server.py:53`)
- **CLI Command / Entry Point**:
  - Modern: `pullstar-mcp` (`pyproject.toml:29`)
  - Legacy console script: `star-aligner-mcp` (`pyproject.toml:30`, `mcp_server/server.py:865`)
  - Desktop bundled invocation: `pullstar-backend --mcp` (`backend/desktop_entry.py:14`)
- **Supported Transports** (`mcp_server/server.py:868-904`):
  1. `stdio` (default): Standard input/output communication.
  2. `sse`: Server-Sent Events over HTTP.
  3. `streamable-http`: Streamable HTTP chunked transport.
- **Stdout Discipline**:
  - In `stdio` transport mode, Python enforces `sys.stdout.reconfigure(line_buffering=True, write_through=True)` (`mcp_server/server.py:892`).
  - Only valid JSON-RPC 2.0 frames may be emitted on stdout.
  - All application diagnostics, OpenCV progress, LibRaw warnings, and trace logs **must** be emitted to stderr.
- **Covering Tests**: `tests/test_mcp_server.py:82-135` (`test_mcp_protocol_discovery`).

---

## 2. Tools Inventory (15 Tools)

### 2.1 Discovery & Sequence Diagnostics
1. **`inspect_sequence`** (`mcp_server/server.py:69-90`):
   - Arguments:
     - `input_dir` (`str`, required): Directory path.
     - `sort_by_time` (`bool`, default `True`): Sort order.
     - `sample_frames` (`int`, default `5`): Frames to sample for SNR/stars.
     - `raw_noise_reduction` (`bool`, default `True`): Raw denoising flag.
   - Result: Sequence metrics, dimensions, bit depth, EXIF gap list, foreground ratio, candidate reference stars, recommended workers.
   - Test: `tests/test_mcp_server.py:139`.

2. **`detect_and_analyze_stars`** (`mcp_server/server.py:92-115`):
   - Arguments:
     - `input_dir` (`str`, required)
     - `frame_step` (`int`, default `10`)
     - `sort_by_time` (`bool`, default `True`)
     - `raw_noise_reduction` (`bool`, default `True`)
     - `max_candidates` (`int`, default `8`)
   - Result: Multi-frame geometric matching metrics, pole inside/outside frame determination, candidate Polaris & second star coordinates, recommended strategy (`"star_field"` vs `"manual_tracking"`).
   - Test: `tests/test_mcp_server.py:155`.

3. **`get_hardware_capabilities`** (`mcp_server/server.py:117-140`):
   - Arguments:
     - `width` (`int`, default `4000`)
     - `height` (`int`, default `3000`)
     - `is_raw` (`bool`, default `False`)
     - `requested_workers` (`Optional[int]`, default `None`)
   - Result: System CPU count, RAM bytes, OpenCL GPUs, recommended workers for image shape, and `recommended_compute_backend: "auto"`.
   - Test: `tests/test_mcp_server.py:115`.

### 2.2 Settings Optimization & Pass 1 Dry-Run
4. **`recommend_settings`** (`mcp_server/server.py:142-178`):
   - Arguments:
     - `input_dir` (`str`, required)
     - `goal` (`Literal["balanced", "natural", "dramatic_extended", "gap_repair", "maximum_sharpness", "trail_lapse_video", "faint_stars_boost"]`, default `"balanced"`)
     - `include_pass1_probe` (`bool`, default `True`)
     - `video_export` (`bool`, default `False`)
   - Result: `recommended_settings` dict ready for `create_stack`, `rationale`, `pass1_probe` scores, and `alternative_presets`.
   - Test: `tests/test_mcp_server.py:168`.

5. **`evaluate_alignment_settings`** (`mcp_server/server.py:180-226`):
   - Arguments: `input_dir`, `polaris_x`, `polaris_y`, `star2_x`, `star2_y`, `use_rotation`, `use_kalman`, `kalman_process_noise`, `kalman_measurement_noise`, `search_window_size`, `max_jump_threshold`, `star_threshold_percentile`, `sort_by_time`, `raw_noise_reduction`, `max_frames`.
   - Result: Pass 1 dry-run metrics (`alignment_score` $0\text{--}100$, `valid_frame_ratio`, `crop`, `transform_stats`, RMS step jitter).
   - Test: `tests/test_mcp_server.py:202`.

6. **`compare_alignment_candidates`** (`mcp_server/server.py:228-252`):
   - Arguments: `input_dir`, `candidates` (`Optional[List[Dict]]`), `max_frames` (`Optional[int]`).
   - Result: Side-by-side benchmark ranking candidate alignment strategies by `alignment_score`. Defaults to testing: `auto_star_field`, `manual_1star_kalman`, and `manual_2star_kalman_rotation`.
   - Test: `tests/test_mcp_server.py:187`.

### 2.3 Stacking, Previews & Quality Verification
7. **`render_preview_stack`** (`mcp_server/server.py:254-299`):
   - Arguments: `input_dir`, `output_file`, `polaris_x`, `polaris_y`, `star2_x`, `star2_y`, `use_rotation`, `use_kalman`, `extension_factor`, `tail_taper_strength`, `tail_angle_threshold`, `ghost_frames_per_real`, `synthetic_fade_factor`, `use_foreground_mask`, `fill_gaps`, `blend_mode`, `sort_by_time`, `raw_noise_reduction`, `raw_exposure_ev`, `max_dimension` (default `960`), `max_frames` (default `24`).
   - Result: Fast downscaled preview stack and objective quality report.
   - Test: `tests/test_mcp_server.py:224`.

8. **`create_stack`** (`mcp_server/server.py:301-393`):
   - Arguments: End-to-end parameters for Pass 1 + Pass 2, including `image_format`, `image_resolution`, `save_frames`, `no_stack`, `video_enabled`, `video_fps`, `video_slowdown`, `video_resolution`, `quality`, `evaluate_output`, `generate_preview_jpeg`.
   - Result: Saved output path (`result_path`), optional `video_path`, `preview_jpeg_path`, and `quality_report`.
   - Test: `tests/test_mcp_server.py:238`.

9. **`auto_tune_and_stack`** (`mcp_server/server.py:395-502`):
   - Arguments: `input_dir`, `output_file`, `goal`, `video_export`, `verify_and_refine` (default `True`), `conversion_format`, `conversion_output_dir`.
   - Result: Autonomous closed-loop inspection, tuning, rendering, and refinement (e.g. enabling `fill_gaps` and switching blend mode if clipping occurs).
   - Test: `tests/test_mcp_server.py:260`.

10. **`evaluate_stack_quality`** (`mcp_server/server.py:504-522`):
    - Arguments: `stack_path`, `reference_frame_path`, `preview_output_path`.
    - Result: `overall_quality_score` ($0\text{--}100$), `verdict`, dynamic range (dB), clipping fraction, trail coverage, trail continuity score, and actionable `tuning_suggestions`.
    - Test: `tests/test_mcp_server.py:245`.

11. **`render_annotated_preview`** (`mcp_server/server.py:524-558`):
    - Arguments: `image_path`, `output_path`, `max_size` (default `1600`), `annotate_stars`, `polaris_x`, `polaris_y`, `star2_x`, `star2_y`, `rotation_center_x`, `rotation_center_y`, `show_foreground_mask`, `raw_noise_reduction`, `raw_exposure_ev`.
    - Result: 8-bit JPEG preview with visual reticle overlays for reference stars, celestial pole, and foreground mask boundary.
    - Test: `tests/test_mcp_server.py:230`.

### 2.4 Asynchronous Background Job Management
12. **`start_stack_job`** (`mcp_server/server.py:560-664`):
    - Arguments: Full stacking parameters matching `JobCreateRequest`.
    - Result: Immediate return of `{"job_id": str, "status": "running", "output_file": str}`.
    - Test: `tests/test_mcp_server.py:279`.

13. **`get_job_status`** (`mcp_server/server.py:666-675`):
    - Arguments: `job_id: str`.
    - Result: Live job status dictionary or error if not found.
    - Test: `tests/test_mcp_server.py:290`.

14. **`cancel_job`** (`mcp_server/server.py:677-685`):
    - Arguments: `job_id: str`.
    - Result: Updated status dictionary (`cancelling` or `cancelled`).
    - Test: `tests/test_mcp_server.py:300`.

15. **`list_jobs`** (`mcp_server/server.py:687-695`):
    - Arguments: *(none)*
    - Result: `{"count": int, "jobs": List[Dict]}`.
    - Test: `tests/test_mcp_server.py:305`.

---

## 3. Resources Inventory (4 Resources)

Defined with URI scheme `staraligner://`:

| Resource URI | Defining Source | MIME Type | Description / Contract |
| :--- | :--- | :--- | :--- |
| `staraligner://system/capabilities` | `mcp_server/server.py:699-702` | `application/json` | Hardware capabilities (CPU cores, RAM bytes, OpenCL GPUs). |
| `staraligner://config/defaults` | `mcp_server/server.py:704-724` | `application/json` | Default tracking, stacking, video parameter constants and supported file extensions. |
| `staraligner://guide/parameter-tuning`| `mcp_server/server.py:726-783` | `text/markdown` | Parameter tuning playbook for AI agents (automatic vs manual, gap repair, foreground preservation, RAW controls). |
| `staraligner://jobs/active` | `mcp_server/server.py:785-792` | `application/json` | Live snapshot of background jobs tracked by `JobManager`. |

Covering Test: `tests/test_mcp_server.py:102-120`.

---

## 4. Prompts Inventory (2 Prompts)

| Prompt Name | Defining Source | Arguments | Output Contract |
| :--- | :--- | :--- | :--- |
| `find_optimal_stack_settings` | `mcp_server/server.py:796-820` | `input_dir: str`, `goal: str = "balanced"` | Step-by-step agent instructions to inspect, probe Pass 1 alignment, compare candidates, and select optimal configuration. |
| `create_verified_stack_workflow`| `mcp_server/server.py:822-845` | `input_dir: str`, `output_file: str = ""`, `goal: str = "balanced"` | End-to-end agent instructions to inspect sequence, execute stack, verify output quality, and re-run refinement if needed. |

Covering Test: `tests/test_mcp_server.py:122-135`.
