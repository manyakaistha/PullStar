# PullStar Compatibility Contracts and Invariants (P0-02)

This directory contains the frozen, source-accurate specifications of all public contracts, interfaces, and invariants across PullStar. These contracts govern the Rust rewrite across Phase 1 through Phase 8.

## 1. Inventory Index

- **[`cli.md`](file:///Volumes/1700%20APFS/PERSONAL_PROGRAMMING_PROJECTS/StarAligner/PullStar/docs/rust/contracts/cli.md)**: Every CLI flag, alias, default value, destination rule, error path, and legacy executable alias across `main.py`, `backend/desktop_entry.py`, and `mcp_server/server.py`.
- **[`api.md`](file:///Volumes/1700%20APFS/PERSONAL_PROGRAMMING_PROJECTS/StarAligner/PullStar/docs/rust/contracts/api.md)**: Every HTTP route/method, Pydantic request/response model, status code, WebSocket live telemetry schema, ETag preview caching, sequence archive streaming, and cancel semantics across `backend/main.py` and `backend/api/*.py`.
- **[`mcp.md`](file:///Volumes/1700%20APFS/PERSONAL_PROGRAMMING_PROJECTS/StarAligner/PullStar/docs/rust/contracts/mcp.md)**: All 15 MCP tools, 4 resource URIs (including legacy `staraligner://` scheme), 2 prompts, stdio/SSE/Streamable HTTP transport contracts, and stdout discipline.
- **[`gui.md`](file:///Volumes/1700%20APFS/PERSONAL_PROGRAMMING_PROJECTS/StarAligner/PullStar/docs/rust/contracts/gui.md)**: Every interactive control, parameter range, default, disabled state, reticle gesture, filmstrip reel, and telemetry widget in the React/Electron desktop studio.
- **[`jobs.md`](file:///Volumes/1700%20APFS/PERSONAL_PROGRAMMING_PROJECTS/StarAligner/PullStar/docs/rust/contracts/jobs.md)**: Job state machine (`created -> running -> cancelling -> completed|failed|cancelled`), terminal transitions, stage progress weights, cancellation two-phase commit, atomic publication staging, and recovery checkpoint signatures.

---

## 2. Coverage and Explicit Gaps

### 2.1 Coverage
- **100% Public Entry Points**: Covers all options in `main.py`, `pullstar-backend`, `pullstar-mcp`, `star-aligner-mcp`, all 19 HTTP/WebSocket routes, all 15 MCP tools, all 4 MCP resources, all 2 MCP prompts, and all desktop GUI controls.
- **Source-Cited**: Every entry is cross-referenced with exact source file lines and existing test files.
- **Automated Verification**: Every contract concept is tied to deterministic fixtures under [`tests/rust-fixtures/`](file:///Volumes/1700%20APFS/PERSONAL_PROGRAMMING_PROJECTS/StarAligner/PullStar/tests/rust-fixtures/).

### 2.2 Explicit Gaps
1. **Third-Party Codec Native Dependencies**: Camera RAW decoding (`LibRaw`) and video container muxing (`FFmpeg`) remain native dependencies wrapped by Rust. Pure Rust implementations of all proprietary camera RAW formats (e.g. CR3, compressed ARW) are outside project scope.
2. **Private Real-World Benchmark Sequences**: The 255-frame 4096×3072 DNG dataset referenced in `docs/noisy-raw-recovery.md` (~5 GB) lives on local private storage and is intentionally not committed to Git. Small portable synthetic fixtures (`tests/rust-fixtures/`) provide reproducible CI verification.
3. **GPU Backend Migration**: The existing Python engine uses OpenCL on macOS Apple Silicon. Apple has deprecated OpenCL in favor of Metal. Phase 4 will evaluate `wgpu`/Metal compute as the long-term replacement while maintaining identical numerical outputs.

---

## 3. Discrepancies Found and Proposed Decisions

During the source-level audit for P0-02, the following behavioral and textual discrepancies were uncovered across documentation, backend code, and frontend interfaces:

### Discrepancy 1: Minimum Image Frame Counts
- **Observed Behavior**:
  - `docs/automatic-star-alignment.md`: States *"Requires at least ten exposures"*.
  - `backend/engine/field_alignment.py:105`: `analyze_field` raises error only if `len(paths) < 3`.
  - `modules/auto_selector.py:61`: `auto_detect_stars` requires `len(image_paths) >= 2`.
  - `backend/engine/alignment_engine.py:403`: Sets `min_images = 3 if self.no_stack else 10`.
  - `frontend/src/App.tsx:160` & `ParameterBays.tsx:140`: Enforces `minimumFrames = p.exportMode === "images" ? 3 : 10`.
  - `core/validator.py:47`: `validate_inputs` default parameter is `min_images=10`.
- **Analysis**: Stacking star trails requires at least 10 frames to produce continuous celestial arcs rather than disjoint dots. However, exporting aligned images for another editor (`--no-stack`) or computing astronomical field wobble (`analyze_field`) is mathematically sound with as few as 3 frames.
- **Proposed Decision**: Formalize this distinction as a validated domain rule in `pullstar-domain`:
  - `AlignmentGoal::Trails`: minimum 10 exposures.
  - `AlignmentGoal::ImagesOnly`: minimum 3 exposures.
  - Standalone `analyze_field`: minimum 3 exposures.
  - Update `docs/automatic-star-alignment.md` to clarify the 3-frame images-only exception.

### Discrepancy 2: Video Quality Preset Names
- **Observed Behavior**:
  - CLI `main.py:61` & API `router.py:28`: Accept `Literal["high", "medium", "lossless", "prores", "hevc"]`.
  - GUI `ParameterBays.tsx:462`: Exposes `high`, `prores`, `lossless`, `medium` (omits `hevc`).
  - Config defaults in `mcp_server/server.py:761`: Reports `SUPPORTED_QUALITIES = ["high", "prores", "lossless", "medium", "web"]` (`"web"` instead of `"hevc"`).
- **Analysis**: `"hevc"` was added to backend codecs for efficient 10-bit exports, while the legacy config had `"web"` as an H.264 profile alias.
- **Proposed Decision**: Standardize `VideoQuality` enum in `pullstar-domain` with canonical variants `High`, `Medium`, `Lossless`, `ProRes`, `Hevc`, while accepting `"web"` as a backward-compatible deserialization alias for `Medium`.

### Discrepancy 3: Default Output Path in Images-Only Mode
- **Observed Behavior**:
  - CLI `main.py:74`: Defaults to `<input_dir>/aligned_images` (folder) when `--no-stack`, and `<input_dir>/aligned_output.tiff` (file) when stacking.
  - API `POST /api/jobs` (`router.py:59`): If `output_file` is omitted, defaults to `os.path.join(request.input_dir, "aligned_output.tiff")` regardless of `no_stack`.
- **Analysis**: In `AlignmentEngine.run_pass2` (`alignment_engine.py:536`), `frames_target = self.output_file if self.no_stack else self.output_file.with_name(self.output_file.stem + "_frames")`. If the API leaves `output_file` as `"aligned_output.tiff"`, images are exported into a folder literally named `"aligned_output.tiff"`.
- **Proposed Decision**: In `pullstar-engine`, resolve default destinations cleanly: if `no_stack=True` and no destination is provided, default to directory `<input_dir>/aligned_images/`.

### Discrepancy 4: Legacy Identifiers and URI Scheme
- **Observed Behavior**:
  - MCP resource URIs use `staraligner://` (`mcp_server/server.py:699-792`).
  - Electron preload exposes `window.starAligner` (`frontend/electron/preload.cjs:8`).
  - Package console scripts provide both `pullstar-mcp` and `star-aligner-mcp` (`pyproject.toml:29-30`).
- **Analysis**: The repository was renamed from StarAligner to PullStar, but existing agent configurations and browser preloads rely on legacy names.
- **Proposed Decision**: Maintain `staraligner://` URI routing as a compatibility alias in `pullstar-mcp` alongside `pullstar://`. Support both `pullstar-mcp` and `star-aligner-mcp` binary symlinks/aliases in `pullstar-cli`.

### Discrepancy 5: Checkpoint Serialization Formats
- **Observed Behavior**:
  - Automatic field alignment saves `.field-checkpoint.npz` (`backend/engine/field_alignment.py:230-245`) using safe array storage (`allow_pickle=False`).
  - Manual star tracking saves `checkpoint_pass*_frame*.pkl` (`core/checkpoint.py:10-80`) using Python `pickle`.
- **Analysis**: Python pickle is non-portable across languages and poses security risks if loaded from untrusted directories.
- **Proposed Decision**: Treat legacy Python pickle checkpoints as strictly **read-only-by-old-app**. All Rust rewrite checkpoints will use Schema Version 1 serialized JSON metadata and raw IEEE 754 float32 pixel buffers.

---

## 4. Fixture Linkage Table

Every deterministic fixture in [`tests/rust-fixtures/`](file:///Volumes/1700%20APFS/PERSONAL_PROGRAMMING_PROJECTS/StarAligner/PullStar/tests/rust-fixtures/) directly covers and verifies specific contract rules:

| Fixture File / Group | Contract Covered | Verification Invariant |
| :--- | :--- | :--- |
| `images/standard/frame_*.png` | `cli.md:2.1`, `api.md:2.1`, `jobs.md:3` | 5-frame sequence for field alignment, wobble estimation, and common crop. |
| `images/standard/frame_00.jpg` | `cli.md:2.4`, `api.md:4.1` | 8-bit JPEG decode, ETag preview caching, and display rendering. |
| `images/standard/frame_00_8bit.tiff` | `cli.md:2.4`, `api.md:4.1` | Uncompressed 8-bit TIFF input and export parity. |
| `images/standard/frame_00_16bit.tiff` | `cli.md:2.4`, `api.md:4.1` | 16-bit uncompressed TIFF input and dynamic range preservation. |
| `images/standard/synthetic_stack_preview.tiff`| `mcp.md:2.3`, `api.md:2.4` | Lighten-blend accumulation and `evaluate_stack_image` metrics. |
| `images/raw/dark_cfa_*.dng` | `cli.md:2.3`, `api.md:2.1`, `mcp.md:2.1` | 10-bit CFA raw metadata (black level 64, white level 1023) and centroid tracking. |
| `images/raw/embedded_preview_only.dng` | `api.md:4.1`, `gui.md:3.1` | Embedded JPEG SubIFD extraction without full RAW codec invocation; orientation 6. |
| `images/negative/blank_zeros.png` | `mcp.md:2.2`, `cli.md:6` | Zero-signal input; must detect 0 sources and reject alignment. |
| `images/negative/pure_noise.png` | `mcp.md:2.2`, `cli.md:6` | Gaussian noise floor; must reject false stellar consensus. |
| `images/negative/unrelated_field.png` | `mcp.md:2.2`, `jobs.md:1` | Non-overlapping stellar field; must fail triangle consensus matching. |
| `images/negative/hot_pixels_only.png` | `mcp.md:2.2`, `gui.md:3.2` | Single-pixel impulses; must be rejected by PSF area and aspect ratio filters. |
| `images/negative/dim_streaked_sources.png` | `mcp.md:2.2`, `gui.md:3.2` | Linear non-Gaussian streaks; must be rejected by circular aperture filters. |
| `manifest.json` (`schedules`) | `cli.md:2.5`, `jobs.md:3` | `video_step_repeats` mapping for slowdown factors 1, 2, 4, 8 and hyperlapse. |
