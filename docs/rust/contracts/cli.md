# CLI Compatibility Contract (P0-02)

This document freezes the command-line interface specification for PullStar. It specifies all executable entry points, argument definitions, defaults, constraints, destination rules, error paths, and legacy aliases across the application.

## 1. Executable Entry Points and Legacy Aliases

| Executable / Invocation | Defining Source | Description / Notes |
| :--- | :--- | :--- |
| `python main.py` / `pullstar` | `main.py:8` (`prog="Star Trail Aligner"`) | Primary batch CLI for alignment, stacking, and video export. |
| `pullstar-backend` | `backend/desktop_entry.py:13` (`prog="pullstar-backend"`) | Electron desktop backend entry point; starts FastAPI Uvicorn service or routes to MCP server. |
| `pullstar-mcp` | `pyproject.toml:29` (`project.scripts`) | Modern MCP entry point invoking `mcp_server.server:main`. |
| `star-aligner-mcp` | `pyproject.toml:30`, `mcp_server/server.py:865` | Legacy MCP console script alias invoking `mcp_server.server:main`. |

---

## 2. Main CLI (`main.py`) Options and Flag Inventory

Defined in `main.py:7-70` (`parse_arguments`):

### 2.1 Inputs and Mode
| Flag / Option | Type | Default | Accepted Values / Range | Defining Line | Covering Test / Procedure | Description / Contract |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `-i`, `--input` | `str` | *(required)* | Valid directory path | `main.py:9` | `tests/test_pipeline_and_api.py:15` | Input folder containing exposure sequence (RAW, JPEG, PNG, TIFF). Must exist and contain at least minimum required images. |
| `-o`, `--output` | `str` | `None` | File or directory path | `main.py:10` | `tests/test_exports.py:18` | Destination path. If omitted, defaults to `<input_dir>/aligned_images` (if `--no-stack`) or `<input_dir>/aligned_output.tiff` (if stacking). |
| `--auto` | `flag` | `False` | Present / Absent | `main.py:25` | `tests/test_field_alignment.py:44` | Automatic stellar field alignment using multi-star triangle matching and trajectory wobble correction. Does not require Polaris. |
| `--polaris-x` | `float` | `None` | $\ge 0.0$ | `main.py:67` | `tests/test_pipeline_and_api.py:35` | Reference X coordinate of Polaris for manual single-star tracking. |
| `--polaris-y` | `float` | `None` | $\ge 0.0$ | `main.py:68` | `tests/test_pipeline_and_api.py:35` | Reference Y coordinate of Polaris for manual single-star tracking. |

### 2.2 Trail Synthesis Parameters
| Flag / Option | Type | Default | Accepted Values / Range | Defining Line | Covering Test / Procedure | Description / Contract |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `--extension` | `float` | `1.0` | $1.0 \le x \le 5.0$ (API bound; warning $>10.0$) | `main.py:11` | `tests/test_trail_effects.py:8` | Trail extension multiplier along the celestial rotation trajectory. $1.0 = \text{preserve actual exposure duration}$. |
| `--tail-taper` | `float` | `0.0` | $0.0 \le x \le 1.0$ | `main.py:12-17` | `tests/test_trail_effects.py:19` | Linear fade strength toward the synthetic tail end. $0.0 = \text{uniform brightness}$. |
| `--tail-angle-threshold` | `float` | `0.0` | $0.0 \le x \le 360.0$ | `main.py:18-24` | `tests/test_trail_effects.py:19` | Maximum angular displacement (degrees) for synthetic tail growth. $0.0 = \text{disabled (no cutoff)}$. |

### 2.3 RAW Development & Pre-Conversion
| Flag / Option | Type | Default | Accepted Values / Range | Defining Line | Covering Test / Procedure | Description / Contract |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `--no-raw-recovery` | `flag` | `False` | Present / Absent | `main.py:26` | `tests/test_raw_processing.py:55` | When set, disables sensor-domain star detection and raw chroma denoising (`raw_noise_reduction=False`). |
| `--raw-exposure` | `float` | `0.0` | $0.0 \le x \le 3.0$ | `main.py:27` | `tests/test_raw_recovery.py:40` | Exposure boost applied during RAW decode ($0$ to $+3\text{ EV}$). Does not alter source files. |
| `--convert` | `choice` | `"none"` | `"none"`, `"jpg"`, `"tiff"` | `main.py:28-29` | `tests/test_conversion.py:12` | Batch-converts RAW/source frames once before alignment and stacking. |
| `--conversion-dir` | `str` | `None` | Directory path | `main.py:30` | `tests/test_conversion.py:28` | Custom directory to persist converted frames. If omitted, uses temporary folder inside source folder that is purged on completion. |

### 2.4 Export Modes & Formats
| Flag / Option | Type | Default | Accepted Values / Range | Defining Line | Covering Test / Procedure | Description / Contract |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `--save-frames` | `flag` | `False` | Present / Absent | `main.py:31` | `tests/test_exports.py:18` | Exports aligned real exposures with common crop. Sibling folder `<output_stem>_frames` if stacking, or target folder if `--no-stack`. |
| `--no-stack` | `flag` | `False` | Present / Absent | `main.py:32` | `tests/test_exports.py:18` | Images-only export mode: skips star trail accumulation, trail synthesis, and video. Requires `--save-frames`. |
| `--image-format` | `choice` | `"tiff"` | `"tiff"`, `"png"`, `"jpg"` | `main.py:33` | `tests/test_exports.py:42` | Output image format. `tiff` & `png` retain source bit depth (8/16-bit); `jpg` is 8-bit quality 95. |
| `--image-resolution` | `choice` | `"source"` | `"source"`, `"4k"`, `"2k"`, `"1080p"`, `"720p"` | `main.py:37-42` | `tests/test_resolution.py:15` | Downsamples working image sequence to preset bounding box before alignment/stacking; never upscales. |

### 2.5 Video Export Parameters
| Flag / Option | Type | Default | Accepted Values / Range | Defining Line | Covering Test / Procedure | Description / Contract |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `--video` | `flag` | `False` | Present / Absent | `main.py:35` | `tests/test_exports.py:68` | Generates a trail-lapse video from the stacking sequence. Incompatible with `--no-stack`. |
| `--video-format` | `choice` | `"auto"` | `"auto"`, `"mp4"`, `"mov"` | `main.py:34` | `tests/test_exports.py:68` | Video container format. `"auto"` selects MP4 (or MOV if ProRes quality). |
| `--video-fps` | `int` | `30` | $1 \le x \le 120$ | `main.py:36` | `tests/test_pipeline_and_api.py:48` | Output video frame rate (fps). |
| `--video-resolution` | `choice` | `"source"` | `"source"`, `"4k"`, `"2k"`, `"1080p"`, `"720p"` | `main.py:43-48` | `tests/test_resolution.py:39` | Maximum long-edge resolution of encoded video. Never upscales smaller source frames. |
| `--video-slowdown` | `choice` | `1` | `1`, `2`, `4`, `8` | `main.py:49-55` | `tests/test_video_schedule.py:6` | Slow-motion factor: snapshots per exposure interval sampled into the encoder. |
| `--video-hyperlapse` | `flag` | `False` | Present / Absent | `main.py:56-60` | `tests/test_video_schedule.py:23` | Samples exactly one video frame per real exposure, skipping all synthetic intermediate states. |
| `--quality` | `choice` | `"high"` | `"high"`, `"medium"`, `"lossless"`, `"prores"`, `"hevc"` | `main.py:61-66` | `tests/test_exports.py:68` | Video codec and bitrate preset. Note: `prores` requires `mov` container (`backend/api/router.py:44`). |

---

## 3. Desktop Entry Point (`backend/desktop_entry.py`)

Defined in `backend/desktop_entry.py:10-35`:

| Flag | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--mcp` | `flag` | `False` | Forwards execution to `mcp_server.server.main(remaining_args)`. Redirects image progress to stderr. |
| `--port` | `int` | `0` | TCP port for FastAPI Uvicorn listener. `0` binds to an OS-assigned ephemeral port and prints `PULLSTAR_BACKEND=http://127.0.0.1:<port>`. |

---

## 4. MCP Server CLI (`mcp_server/server.py`)

Defined in `mcp_server/server.py:864-884` (`main`):

| Flag | Type | Default | Accepted Values | Description |
| :--- | :--- | :--- | :--- | :--- |
| `--transport` | `choice` | `"stdio"` | `"stdio"`, `"sse"`, `"streamable-http"` | MCP transport protocol. In stdio mode, stdout is reconfigured with line buffering and write-through; application logging must stay off stdout. |
| `--host` | `str` | `"127.0.0.1"` | Valid IP / hostname | Bind host for HTTP / SSE transports. |
| `--port` | `int` | `8765` | $1 \le x \le 65535$ | Bind port for HTTP / SSE transports. |

---

## 5. Output Destination and Staging Rules

1. **Default Output Paths** (`main.py:74`):
   - Stacking mode (`no_stack=False`): `<input_dir>/aligned_output.tiff`
   - Images-only mode (`no_stack=True`): `<input_dir>/aligned_images`
2. **Sibling Frames Folder** (`backend/engine/alignment_engine.py:536`):
   - When `save_frames=True` and `no_stack=False`: aligned frames are saved in a sibling directory named `<output_stem>_frames` beside the output image.
   - When `save_frames=True` and `no_stack=True`: aligned frames are saved directly into `output_file` (which must be a directory path).
3. **Existing Folder Protection** (`backend/engine/alignment_engine.py:537-538`, `tests/test_exports.py:88-103`):
   - If the target frames directory already exists, processing aborts immediately before any files are modified with error: `ValueError: Export folder already exists: <path>. Choose a new output name to preserve existing files.`
4. **Atomic Staging Directory** (`backend/engine/alignment_engine.py:540-575`):
   - All intermediate renders and final files are written to a temporary folder prefixed `.staraligner-` inside `output_file.parent`.
   - On cancellation or failure, the staging directory is cleaned up and deleted; no corrupt, partial, or unaligned files are published.
   - Publication occurs atomically via filesystem rename only after successful verification and cancellation check.

---

## 6. Error Paths and Exit Codes

| Error Condition | Defining Source | Exit Code / Exception | Error Message Contract |
| :--- | :--- | :--- | :--- |
| Missing `--input` | `main.py:9` | Exit 2 (argparse) | `usage: Star Trail Aligner [-h] -i INPUT ... error: the following arguments are required: -i/--input` |
| Neither `--auto` nor Polaris coordinates provided | `main.py:117-118` | Exit 1 | `Please provide --polaris-x and --polaris-y or use --auto` |
| One Polaris coordinate provided without the other | `main.py:111-112` | Exit 1 | `ValueError: Provide both --polaris-x and --polaris-y, or use --auto` |
| `--no-stack` without `--save-frames` | `backend/engine/alignment_engine.py:404` | Exit 1 | `ValueError: Images-only export requires save_frames` |
| `--video` with `--no-stack` | `backend/engine/alignment_engine.py:406` | Exit 1 | `ValueError: Trail video requires trail creation` |
| `--quality prores` with `--video-format mp4` | `backend/api/router.py:44` | Exit 1 | `ValueError: ProRes requires a MOV container` |
| Fewer than 10 frames for stacking | `backend/engine/alignment_engine.py:403` | Exit 1 | `ValueError: Validation failed: ['Need at least 10 images for meaningful trail alignment, found <N>']` |
| Fewer than 3 frames for `--no-stack` | `backend/engine/alignment_engine.py:403` | Exit 1 | `ValueError: Validation failed: ['Need at least 3 images for meaningful trail alignment, found <N>']` |
| Unrecognized argument in `pullstar-backend` | `backend/desktop_entry.py:25` | Exit 2 | `error: unrecognized arguments: <args>` |
