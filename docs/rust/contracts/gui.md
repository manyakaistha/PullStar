# Graphical User Interface (GUI) Contract (P0-02)

This document freezes the interactive controls, states, defaults, interdependencies, and visual workflows of the PullStar desktop studio. It captures the behavior implemented in React/TypeScript and Electron to guide the native Rust GUI implementation (`pullstar-desktop`).

## 1. Top-Level Workspace Navigation

Defined in `frontend/src/components/WorkspaceNav.tsx:1-55` and `frontend/src/App.tsx:10-50`:

- **Active Views**:
  - `"workspace"`: Primary studio showing the setup bays, celestial viewfinder, and live telemetry.
  - `"results"`: Post-processing showcase view featuring the interactive before/after split comparison and output download actions. Automatically activated upon job completion (`App.tsx:219`).
- **Telemetry Drawer**:
  - `isTelemetryCollapsed` (`bool`, default `True`): Collapsed to single summary line by default; automatically expands (`isTelemetryCollapsed = False`) when a job starts (`App.tsx:165`).

---

## 2. Section 01: Source Frames Bay

Defined in `frontend/src/components/ParameterBays.tsx:150-250`:

| Control | Type | Default | Constraints / Options | Defining Source | Description & Interdependencies |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Image folder** | Text Input | `""` | Valid directory path | `ParameterBays.tsx:158` | Path to exposure sequence. Pressing `Enter` triggers scan. |
| **Browse Folder** | Icon Button | *(action)* | Invokes OS folder dialog | `ParameterBays.tsx:167`, `App.tsx:127` | Calls `window.starAligner.pickDirectory("source")` in Electron. |
| **Load frames** | Button | *(action)* | Disabled if empty or scanning | `ParameterBays.tsx:171` | Calls `POST /api/images/list` and `POST /api/images/metadata`. |
| **Sequence Order** | Segmented Control | `Time` | `Time` (`sortByTime=True`), `Name` (`sortByTime=False`) | `ParameterBays.tsx:197-220` | Determines exposure ordering for alignment and timeline gap calculation. |
| **Processing Device** | Dropdown | `"auto"` | `"auto"`, `"cpu"` | `ParameterBays.tsx:223-228` | `"auto"` selects OpenCL GPU if available with CPU fallback; `"cpu"` forces CPU only. |
| **High-noise RAW Recovery** | Disclosure / Toggle | `True` | `True` / `False` | `ParameterBays.tsx:233-238` | Only visible when loaded sequence contains RAW files (`.dng`, `.nef`, `.cr2`, `.cr3`, `.arw`). |
| **RAW Exposure Boost** | Dropdown | `0` | `0` (original), `1` (+1 EV), `2` (+2 EV), `3` (+3 EV) | `ParameterBays.tsx:239-246` | Boosts exposure during RAW development. Only visible when RAW files are present. |

---

## 3. Celestial Viewfinder & Filmstrip

Defined in `frontend/src/components/CelestialViewfinder.tsx:1-710`:

### 3.1 Viewfinder Toolbar & Reticle Mode
- **Reticle Mode Selector** (`CelestialViewfinder.tsx:432-463`):
  - `Polaris` (Cyan `#38bdf8`): Mode for placing the primary tracking star or celestial pole.
  - `Ref Star` (Amber `#f59e0b`): Mode for placing the secondary star (for field rotation correction).
- **Navigation Controls** (`CelestialViewfinder.tsx:465-495`):
  - `Reset`: Fits image within viewfinder canvas preserving aspect ratio (`scale = fitScale * 0.92`, centered).
  - `Zoom In` (`+` / `=`): Multiplies scale by `1.2` centered on viewport (`scale <= 50.0`).
  - `Zoom Out` (`-`): Divides scale by `1.2` centered on viewport (`scale >= 0.01`).
  - `Scale Pill`: Displays current zoom percentage (e.g. `100%`).
- **Interactive Gestures** (`CelestialViewfinder.tsx:370-425`):
  - **Pan**: Middle-click drag, right-click drag, Shift + Left-click drag, or keyboard arrow keys (24 px step).
  - **Zoom**: Mouse wheel scroll.
  - **Place Star**: Left click on canvas. Clamped to image pixel boundaries. Disallowed if active frame is not frame 0 (`currentImage !== imageSrc`).
  - **Vector Line**: When both Polaris and Ref Star are placed, draws a dashed white line connecting them and displays the vector angle in degrees (`angle.toFixed(2)°`).

### 3.2 Reference Star Detection
- **`Detect references` / `Cancel detection` Button** (`CelestialViewfinder.tsx:498-535`):
  - When idle: invokes `POST /api/stars/detect/start`.
  - While running: button transforms into `Cancel detection` with spinning loader; clicking calls `JobAction.cancel()`.
  - On completion: renders green circles (`#34d399`, radius 7 px) around all matched reference stars and labels the top 3 (`STAR 1`, `STAR 2`, `STAR 3`). Sets `Ref Star 2` coordinates and displays match confidence percentage badge (`detectConfidence * 100%`).

### 3.3 Filmstrip Reel
- Located at bottom of viewfinder (`CelestialViewfinder.tsx:645-705`).
- Displays thumbnail previews of all images via `GET /api/images/preview?path=<file>&max_size=256`.
- Clicking a thumbnail selects it as the active viewfinder frame.
- Displays header telemetry: `<N> FRAMES · <K> GAPS` and active frame position (`Frame M / N`).

---

## 4. Section 02: Alignment Configuration Bay

Defined in `frontend/src/components/ParameterBays.tsx:251-335`:

| Control | Type | Default | Constraints / Options | Defining Source | Description & Interdependencies |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Smooth Star Tracking** | Toggle | `True` | `True` / `False` | `ParameterBays.tsx:260` | Enables Kalman centroid filtering to dampen tracking jitter. |
| **Correct Field Rotation** | Toggle | `False` | `True` / `False` | `ParameterBays.tsx:266` | Requires a second reference star when manual Polaris is picked. |
| **What would you like to create?** | Dropdown | `"trails"` | `"trails"`, `"images"` | `ParameterBays.tsx:273` | `"trails"`: Star trails image + optional video (min 10 frames). `"images"`: Aligned real images only with common crop (min 3 frames; skips stacking, synthesis, and video). |
| **Trail Extension** | Slider | `1.0` | $1.0 \le x \le 5.0$, step 0.1 | `ParameterBays.tsx:285-294` | Multiplies synthetic trail length along sky motion trajectory. Only visible when export mode is `"trails"`. |
| **Preserve Foreground** | Toggle | `True` | `True` / `False` | `ParameterBays.tsx:295` | Uses sky/ground segmentation mask so ground stays sharp during synthetic rotation. |
| **Fill Timeline Gaps** | Toggle | `False` | `True` / `False` | `ParameterBays.tsx:299` | Synthesizes missing exposures across detected EXIF timeline gaps. |
| **Tail Taper** | Slider | `0.0` | $0.0 \le x \le 1.0$, step 0.05 | `ParameterBays.tsx:307-315` | Fades synthetic trail brightness toward end. Advanced drawer. |
| **Tail Angle Cutoff** | Slider | `0.0` | $0.0 \le x \le 360.0$, step 1° | `ParameterBays.tsx:316-325` | Maximum angular growth ($0^\circ = \text{no limit}$). Advanced drawer. |
| **Synthetic Frames / Exp** | Slider | `10` | $1 \le x \le 20$, step 1 | `ParameterBays.tsx:326-332` | Number of intermediate modeled samples generated between exposures. |
| **Synthetic Fade** | Slider | `0.2` | $0.0 \le x \le 1.0$, step 0.05 | `ParameterBays.tsx:333-340` | Alpha fade factor for synthetic ghost frames. |

---

## 5. Section 03: Output Configuration Bay

Defined in `frontend/src/components/ParameterBays.tsx:345-515`:

| Control | Type | Default | Constraints / Options | Defining Source | Description & Interdependencies |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Stacking Input Format** | Dropdown | `"none"` | `"none"`, `"jpg"`, `"tiff"` | `ParameterBays.tsx:355-364` | Converts frames once before alignment. Advanced drawer. |
| **Converted Frame Location**| Text + Browse | `""` | Valid directory path | `ParameterBays.tsx:376-390` | Custom directory to persist converted inputs. Empty = temporary folder. |
| **Image Export Format** | Dropdown | `"tiff"` | `"tiff"`, `"png"`, `"jpg"` | `ParameterBays.tsx:397-404` | Format for output stack and aligned images. |
| **Output Name / Path** | Text Input | `"aligned_star_trails.tiff"` | Filename or absolute path | `ParameterBays.tsx:408-417` | Default placeholder switches to `"aligned_images"` when mode is `"images"`. |
| **Image Export Resolution**| Dropdown | `"source"` | `"source"`, `"4k"`, `"2k"`, `"1080p"`, `"720p"` | `ParameterBays.tsx:422-432` | Max working resolution; lower presets speed up stacking. |
| **Also Export Aligned Images**| Toggle | `False` | `True` / `False` | `ParameterBays.tsx:438` | When mode is `"trails"`, saves aligned frames to `<output>_frames`. |
| **Also Create Trail Video** | Toggle | `False` | `True` / `False` | `ParameterBays.tsx:441` | Enables video generation. Incompatible with `"images"` mode. |
| **Video File Format** | Dropdown | `"mp4"` | `"mp4"`, `"mov"` | `ParameterBays.tsx:446-452` | Container format. Forced to `"mov"` if ProRes quality is selected. |
| **Video Quality** | Dropdown | `"high"` | `"high"`, `"prores"`, `"lossless"`, `"medium"` | `ParameterBays.tsx:457-467` | Codec selection. `"prores"` produces Apple ProRes 422 HQ. |
| **Video Resolution** | Dropdown | `"1080p"` | `"source"`, `"4k"`, `"2k"`, `"1080p"`, `"720p"` | `ParameterBays.tsx:472-482` | Output video long-edge resolution. |
| **Video Mode** | Segmented Control | `Slow motion` | `Slow motion` (`slowmo`), `Hyperlapse` | `ParameterBays.tsx:489-509` | Hyperlapse encodes exactly 1 frame per real exposure. |
| **Slow-Motion Pace** | Dropdown | `1` | `1` (1× Fast), `2` (2×), `4` (4×), `8` (8× Very slow) | `ParameterBays.tsx:514-526` | Snapshots sampled per exposure interval. |
| **Save Checkpoints** | Toggle | `True` | `True` / `False` | `ParameterBays.tsx:534` | Enables `.field-checkpoint.npz` saving. |
| **Resume from Checkpoint** | Toggle | `False` | `True` / `False` | `ParameterBays.tsx:539` | Resumes interrupted job from checkpoint. |

---

## 6. Footer Action Button & Cancellation States

Defined in `frontend/src/components/ParameterBays.tsx:545-595`:

### Button States and Transitions
1. **Disabled**:
   - Condition: `!loadedDir` OR `files.length < minimumFrames` OR `!outputName.trim()` OR `isScanning` OR `isDetecting`.
   - `minimumFrames`: `3` if mode is `"images"`, `10` if mode is `"trails"`.
2. **Ready (Idle)**:
   - Text: `"Create star trails"` (trails mode) or `"Align & export images"` (images mode).
   - Clicking invokes `startJob()` (`App.tsx:156`).
3. **Active (Processing)**:
   - Button class adds `.action-cancel`.
   - Text dynamically reflects stage:
     - Stage `conversion`: `"Cancel conversion"`
     - Stage `pass2` (mode `images`): `"Cancel image export"`
     - Stage `pass2` (mode `trails`): `"Cancel trail creation"`
     - Stage `video_render`: `"Cancel video render"`
     - Default: `"Cancel alignment"`
   - Clicking invokes `cancelJob()` (`App.tsx:232`), calling `POST /api/jobs/{id}/cancel`.
4. **Cancelling**:
   - Disabled with spinning loader icon.
   - Text: `"Cancelling…"`.

---

## 7. Live Telemetry & Results Showcase

Defined in `frontend/src/components/LiveTelemetry.tsx:1-350`:

### 7.1 Pipeline Stages Progress
Visual stage stepper tracks:
1. `preparation`: "Prepare"
2. `conversion`: "Convert frames" (only displayed when `conversion_format !== "none"`)
3. `pass1`: "Track stars"
4. `crop_calc`: "Calculate crop"
5. `pass2`: "Stack frames" (or "Export images" if `no_stack=True`)
6. `video_render`: "Render video" (only displayed if `video_enabled=True`)

Displays overall progress percentage (`overall_progress * 100%`) with monotonic progress bar and stage step counter (`current / total steps`, `fps`).

### 7.2 Measured Drift Graph
- SVG chart plotting horizontal drift (`drift_x`, cyan `#8ec9d1`) and vertical drift (`drift_y`, amber `#ceb791`) across the last 60 exposures.

### 7.3 Results View (`showcaseOnly=True`)
- **Interactive Split Comparison Slider**:
  - Left side shows source frame (`first_frame_path`); right side shows aligned result (`result_path`).
  - Draggable handle with keyboard accessibility (`ArrowLeft`/`ArrowRight` 1% step, `PageUp`/`PageDown` 10% step, `Home` 0%, `End` 100%).
- **Export Action Links**:
  - Download trail image / Download aligned images ZIP (`/api/images/download` or `/api/images/download-sequence`).
  - Download trail video (`/api/images/download?path=<video_path>`).
