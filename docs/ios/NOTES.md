# iOS Engineering Notes

## Implementation Sub-agent (Pass 2 Stacking, Frame Warping, Video Export)

### Owned Files & Responsibilities
- `Sources/PullStarKit/Engine/WarpFrameWarper.swift`: `FrameWarper`
- `Sources/PullStarKit/Engine/TrailStacker.swift`: `TrailStacker`, `TrailEffects`, `ForegroundMaskGenerator`, `StackCheckpointMetadata`
- `Sources/PullStarKit/Engine/StackLivePreview.swift`: `LivePreviewPublisher`
- `Sources/PullStarKit/Engine/StackPipeline.swift`: `StackPipeline`, `StackPipelineResult`
- `Sources/PullStarKit/Export/TrailVideoWriter.swift`: `TrailVideoWriter`
- `Sources/PullStarKit/Export/AlignedFrameExporter.swift`: `AlignedFrameExporter`, `FrameExportManifest`
- `Tests/PullStarKitTests/StackTests.swift`: Comprehensive unit tests for warper, stacker, video writer, live preview, checkpoints, and pipeline

### Architectural Details & Faithfulness to Reference
1. **FrameWarper**:
   - Lanczos-4 separable sampling grid with precomputed 32-phase lookup table (256 weights, 8 taps per dimension) exactly matching OpenCV / OpenCL reference `render_backend.py`.
   - Runtime-compiled Metal compute kernel (`MTLDevice.makeLibrary(source:)`) using threadgroups of 16x16 with memory-bounded reusable buffers (`sourceBuffer`, `outputBuffer`, `weightsBuffer`, `uniformsBuffer`).
   - Pure integer translation fast-path for fixed-tripod zero-rotation alignments (copies contiguous memory strips directly without convolution overhead).
   - Thread-safe CPU fallback using `DispatchQueue.concurrentPerform` over row strips with Sendable pointer wrappers.
   - Respects `computeBackend` (`.auto`, `.cpu`, `.gpu`).

2. **TrailStacker & TrailEffects**:
   - Supports `lighten` (running max) and `add` blend modes.
   - Foreground sky mask (`ForegroundMaskGenerator`): Computes brightness, Otsu thresholding, and saturation to isolate sky and smooths mask with a 5x5 feather filter; synthetic ghost frames only rotate the sky, keeping foreground structures tack sharp.
   - Synthetic ghost frames between consecutive exposures using `extensionFactor`, `ghostFramesPerReal`, `syntheticFadeFactor`, `tailTaperStrength`, and `tailAngleThreshold`.
   - Synthetic future extrapolation beyond the final exposure rotating around Polaris at Earth sidereal or median rotational rate.
   - Periodic atomic checkpoint save/resume to `.pullstar_checkpoints` containing raw float data and metadata.

3. **LivePreviewPublisher**:
   - Throttled downscaled tone-mapped JPEG publishing (250ms cadence, forced on first and last steps).
   - Area-preserving downsample (max dimension 512) computing 99.7th percentile tone scale, mapped to display range, and compressed via `ImageIO` with quality 0.88.
   - Yields JPEG `Data` and monotonically increasing `revision` counter.

4. **TrailVideoWriter**:
   - Hardware-accelerated `AVAssetWriter` with `AVAssetWriterInputPixelBufferAdaptor`.
   - Supports H.264, HEVC, ProRes 422 HQ, and visually lossless presets.
   - Enforces ProRes => `.mov` container rule (`AVFileType.mov`).
   - Resolution scaling conforming to `Resolution` preset with guaranteed even dimensions (`fitDimensions`).
   - Supports `videoHyperlapse`, `slowdown` (1...8), and presentation timestamps tied to `videoFPS`.

5. **AlignedFrameExporter**:
   - Exports aligned image sequences in TIFF, PNG, or JPEG format into `<outputBaseName>_frames`.
   - Generates and writes `sequence.json` manifest specifying frame paths, source files, dimensions, and skipped frames.

6. **StackPipeline**:
   - Top-level `StackPipeline.run(...)` coordinating frame loading, warping, stacking, trail extrapolation, video writing, frame exports, and progress emission.
   - Full cancellation support honoring Swift Concurrency `Task.isCancelled` / `try Task.checkCancellation()`.

## Implementation Sub-agent (App Shell, Theme, Services, Setup)

### Theme & Design System (`ios/PullStar/Theme/`)
- Exact dark color palette from web CSS (`frontend/src/index.css`):
  - `psWorkspaceBg`: `#050505`
  - `psSurfaceSolid`: `#161617`
  - `psTextPrimary`: `#f2f2f3`, `psTextSecondary`: `#bababe`, `psTextMuted`: `#929299`
  - `psAccent`: `#d8e5e7`, `psSuccess`: `#a4cbb9`, `psWarning`: `#ceb791`, `psDanger`: `#efa7a7`
  - Action cancel palette: `psCancelBg` (`#30241f`), `psCancelBorder` (`#a67c59`), `psCancelText` (`#ffe1c4`)
- Reusable components engineered with 44pt+ minimum hit targets, Dynamic Type, and accessible traits:
  - `Panel`: Glass surface container with Liquid Glass styling and gradient borders.
  - `PSButton`: Primary, secondary, cancel, pill, and quiet tactile button variants.
  - `PSToggle`: Custom physical switch (`36x21` track, `15x15` cap) with smooth sliding animation and optional `LEDIndicator`.
  - `PSSlider`: Tactile range slider with field-well readout badge (`1.0×`, `0°`, etc.), dynamic steps, helper text, and accessible value readout.
  - `AdvancedDisclosure`: Collapsible `<details>`/`<summary>` equivalent with rotating chevron and clean dividers.
  - `LEDIndicator`: Multi-state status dot (`cyan`, `amber`, `emerald`, `danger`, `off`) with glowing ambient shadow.

### State & Storage (`ios/PullStar/App/AppModel.swift`)
- `@Observable @MainActor AppModel`:
  - Holds `JobConfig` draft, sequence (`[SequenceInfo]`), selected reference index, current `JobState`, and `any PullStarEngine`.
  - Folder access via `.fileImporter` supporting directory selection and persisting security-scoped bookmarks in `UserDefaults`.
  - Settings persisted across launches with `Codable` serialization in `UserDefaults`.\
  - Exposes `selectedIndex` and `state` compatibility properties to interoperate seamlessly with `ViewfinderView`, `TelemetryPanel`, and `ResultsView`.

### Services (`ios/PullStar/Services/`)
- `MockEngine`: Implements `PullStarEngine` to simulate sequence listing (generates synthetic frames with dates and timeline gaps if empty), procedural night sky starfield previews via `UIGraphicsImageRenderer`, star detection, and a ~10-second progress run traversing preparation, conversion, pass 1, crop calculation, pass 2, and video rendering before writing a finished sample image to disk.
- `EngineFactory`: Provides `EngineFactory.make()` with a single swap line to link `PullStarEngineImpl` when ready.

### Shell & Setup (`ios/PullStar/Views/`)
- `SetupView` (`Views/Setup/`): Exactly mirrors `ParameterBays.tsx` sections ("01 Source frames", "02 Build your alignment", "03 Output") including all advanced disclosures, validation error display via `JobConfig.validationError()`, export mode selection, and video export settings.
- `StudioShellView` (`Views/Shell/`): Adaptive iPad layout using `NavigationSplitView` for regular widths (with 360pt ideal sidebar) and stacked navigation + sheet for compact Split View / Slide Over widths. Toolbar provides shortcuts for Open (⌘O), Start (⌘R), and Cancel (⌘.).
- `StudioHeaderView` (`Views/Shell/`): Displays brand logo, "PullStar." typography, workspace/results navigation pills, and dynamic job status badge.
- `Assets.xcassets`: Populated with `AppIcon.appiconset` and `BrandLogo.imageset` generated from `frontend/public/app-icon.png`.

## Implementation Sub-agent (IO Layer)

### Concurrency Fix in `TrailVideoWriter.swift`
- In `TrailVideoWriter.finish() async throws -> URL`, calling `lock.lock()` and `lock.unlock()` directly inside an `async` function triggered a Swift 6 compiler error (`instance method 'lock' is unavailable from asynchronous contexts; Use async-safe scoped locking instead`).
- Replaced with scoped `lock.withLock { ... }` to ensure synchronous atomic check-and-set of `isFinished` without crossing suspension points.

## Implementation Sub-agent (Views: Viewfinder, Telemetry, Results)

### Info.plist Keys & Permissions
For `ResultsView` (saving aligned images and star trail videos to the iOS Photos library via `PHPhotoLibrary`):
- **Key**: `NSPhotoLibraryAddUsageDescription`
- **Value**: `"PullStar saves finished trail images and videos to your library."`
- **Status**: Configured in `ios/project.yml` under `INFOPLIST_KEY_NSPhotoLibraryAddUsageDescription`. Verified working with `PHPhotoLibrary.requestAuthorization(for: .addOnly)`.

For file export and document handling:
- **Key**: `LSSupportsOpeningDocumentsInPlace` (`YES`)
- **Key**: `UIFileSharingEnabled` (`YES`)
- **Status**: Configured in `ios/project.yml`.

### Component APIs & Architecture
1. **Viewfinder (`ios/PullStar/Views/Viewfinder/`)**
   - `ViewfinderContent`: Plain-value SwiftUI component with zero dependencies on AppModel. Takes sequence, selectedIndex binding, previewLoader async closure, detected stars, polaris/secondStar bindings, and callbacks.
   - `ViewfinderView(model: AppModel)`: Thin wrapper adapting the observable `AppModel`.
   - `ViewfinderCanvas`: Interactive zoom/pan/double-tap-zoom canvas, grid, procedural starfield, emerald star markers, cyan Polaris & amber Second Star reticles with dashed vector connecting line and angle readout.
   - `MagnifierLoupe`: Apple Pencil and touch-friendly circular magnifying loupe displaying a 3x zoomed view, grid, reticle, and coordinate pill offset above the finger/stylus during reticle dragging.
   - `FilmstripView`: Lazy horizontal filmstrip with asynchronous thumbnail loading and cached memory backing via `ImageCache`.
   - `ImageCache`: Thread-safe actor with `NSCache` for high-performance thumbnail caching.

2. **Telemetry (`ios/PullStar/Views/Telemetry/`)**
   - `TelemetryPanel(state: JobState, isCollapsed: Bool, onToggleCollapse: (() -> Void)?, onCancel: (() -> Void)?)`: Mirrors `LiveTelemetry.tsx`. Shows stage LEDs, active stage progress, overall progress bar with animated gradient, frame counter, drift readout, FPS, ETA, processing hardware, and cancel callback.
   - `DriftChart`: Dynamic dual-line chart visualizing tracking precision along X and Y axes over time with dashed zero line and live numeric readouts.

3. **Results (`ios/PullStar/Views/Results/`)**
   - `ResultsView(state: JobState)`: Showcases the finished star trail stack or image sequence. Includes an interactive before/after split comparison slider, double-tap and pinch-to-zoom, AVKit video player for trail videos, aligned frame count, file paths, and tactile action buttons: Share (`ShareLink`), Save to Photos (`PhotoSaver`), Copy Path, and document export.
   - `PhotoSaver`: `PHPhotoLibrary` add-only photo and video saver with status reporting and error handling.
