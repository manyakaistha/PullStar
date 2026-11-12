# PullStar — MCP Server (`pullstar-mcp`)

The PullStar **Model Context Protocol (MCP) Server** enables AI agents (Claude Code, Claude Desktop, Cursor, T3 Code, custom MCP clients) to autonomously inspect astrophotography sequences, discover the right alignment and synthesis settings, benchmark candidate configurations, render fast preview stacks, and produce verified full-resolution star trail stacks.

---

## 1. Running the MCP Server

The installed desktop app provides the server without Python or uv. On macOS:

```bash
/Applications/PullStar.app/Contents/Resources/backend/pullstar-backend --mcp
```

On Linux, run `resources/backend/pullstar-backend --mcp` from the PullStar install directory.

Use the client configuration in the repository root’s `mcp.json.example`. Paths containing spaces must be supplied as a single command value, without shell quoting inside JSON. MCP starts independently from the desktop UI; each process has its own job list. `create_stack` and `start_stack_job` accept `image_format` (`tiff`, `png`, `jpg`) and `video_format` (`auto`, `mp4`, `mov`). Set `save_frames=true` and `no_stack=true` for aligned-image export without trails; disable video for that workflow.


### Stdio Transport (Default for Desktop/CLI Agents)
```bash
uv run pullstar-mcp
# or
uv run python -m mcp_server
```

### SSE or Streamable HTTP Transport
```bash
uv run pullstar-mcp --transport streamable-http --host 127.0.0.1 --port 8765
# or
uv run pullstar-mcp --transport sse --host 127.0.0.1 --port 8765
```

### Example MCP Client Configuration (`mcp.json` / `claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "star-trail-aligner": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/PullStar",
        "run",
        "pullstar-mcp"
      ]
    }
  }
}
```

---

## 2. Agent Workflow: Finding the Right Settings & Creating a Good Stack

1. **Sequence Discovery (`inspect_sequence`)**
   - Scans the exposure folder (automatically filtering out prior stack outputs like `aligned_star_trails.tiff` or `.mp4` videos).
   - Reports resolution, bit-depth/RAW status, EXIF timestamp spacing, dropped-frame timeline gaps, sky vs. foreground landscape coverage, and sampled star counts.
2. **Star Field & Pole Analysis (`detect_and_analyze_stars`)**
   - Runs `photutils.DAOStarFinder` + `astroalign` rigid motion matching across the sequence.
   - Determines whether the celestial pole (`rotation_center`) is inside or outside the frame and recommends either:
     - **Automatic `star_field` alignment (`polaris_x=None, polaris_y=None`)**: Removes camera wobble while preserving natural sky trail rotation and framing.
     - **Manual reference tracking (`polaris_x, polaris_y`, optional `star2_x, star2_y`)**: Tracks bright isolated stars with `KalmanCentroidTracker`.
3. **Settings Synthesis (`recommend_settings`)**
   - Synthesizes a complete `recommended_settings` configuration for a creative goal (`"balanced"`, `"dramatic_extended"`, `"gap_repair"`, `"maximum_sharpness"`, `"trail_lapse_video"`, or `"faint_stars_boost"`).
   - Runs a fast Pass 1 alignment dry-run probe and returns per-parameter rationale plus ready-to-use alternative presets.
4. **Candidate Benchmarking (`evaluate_alignment_settings` & `compare_alignment_candidates`)**
   - Runs Pass 1 alignment dry-runs without expensive Pass 2 image stacking.
   - Scores each candidate (0–100) across valid frame retention, common crop area retention, star-matching confidence, and frame-to-frame RMS trajectory jitter.
5. **Fast Preview Iteration (`render_preview_stack`)**
   - Renders a downscaled stack from a subsample of frames in seconds so agents can test `extension_factor`, `tail_taper_strength`, `tail_angle_threshold`, `ghost_frames_per_real`, `synthetic_fade_factor`, `fill_gaps`, `use_foreground_mask`, `blend_mode`, and `raw_exposure_ev`.
6. **Full Stack & Closed-Loop Verification (`create_stack`, `auto_tune_and_stack`, `evaluate_stack_quality`)**
   - Renders the full 8-bit/16-bit TIFF stack (and optional trail-lapse video), generates a JPEG preview, and computes objective quality metrics (`overall_quality_score`, `trail_continuity_score`, `clipping_fraction`, `foreground_sharpness_retention`, and `tuning_suggestions`).

---

## 3. Available MCP Tools

| Tool Name | Purpose |
| :--- | :--- |
| `inspect_sequence` | Inspect frame count, dimensions, RAW/bit-depth, EXIF timestamp gaps, foreground ratio, and sampled star counts. |
| `detect_and_analyze_stars` | Run multi-frame star matching and extract ranked manual reference star candidates (`polaris`, `second_star`). |
| `recommend_settings` | Recommend optimal alignment & stacking parameters for a sequence and creative goal, with rationale and Pass 1 probe. |
| `evaluate_alignment_settings` | Run a fast Pass 1 alignment dry-run and return `alignment_score` (0–100), crop retention, and transform jitter. |
| `compare_alignment_candidates` | Benchmark multiple alignment configurations side-by-side and return the ranked winner. |
| `render_preview_stack` | Render a fast downscaled preview stack to test synthesis/blend settings and evaluate stack quality. |
| `create_stack` | Run full Pass 1 + Pass 2 alignment & stacking and return output paths + `quality_report`. |
| `auto_tune_and_stack` | Closed-loop autonomous workflow: recommend settings, benchmark alignment, render stack, verify quality, and auto-refine if needed. |
| `evaluate_stack_quality` | Evaluate an output stack for trail continuity (smooth arcs vs beaded dots), highlight clipping, contrast, and foreground sharpness. |
| `render_annotated_preview` | Render an 8-bit JPEG preview of any frame or stack with optional star, pole, crop, and foreground mask overlays. |
| `get_hardware_capabilities` | Query CPU count, RAM, OpenCL GPUs, and recommended worker count. |
| `start_stack_job` / `get_job_status` / `cancel_job` / `list_jobs` | Manage asynchronous background stacking jobs via `JobManager`. |

---

## 4. Available MCP Resources & Prompts

### Resources
- `staraligner://system/capabilities` — Live CPU, memory, and OpenCL GPU hardware report.
- `staraligner://config/defaults` — Default tracking, Kalman, synthesis, and video constants.
- `staraligner://guide/parameter-tuning` — Parameter tuning playbook for AI agents.
- `staraligner://jobs/active` — Active and completed jobs in `JobManager`.

### Prompts
- `find_optimal_stack_settings(input_dir, goal)` — Guided workflow to discover and benchmark the best settings for a sequence.
- `create_verified_stack_workflow(input_dir, output_file, goal)` — Guided workflow to create, verify, and refine a full star trail stack.
