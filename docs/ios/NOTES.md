# iOS Engineering Notes

## Implementation Sub-agent (Pass 1 Detection, Alignment, Kalman, Crop)

### Owned Files & Responsibilities
- `Sources/PullStarKit/Engine/Detection.swift`: `StarDetector`, `DetectedStar`
- `Sources/PullStarKit/Engine/AlignmentMatching.swift`: `StarFieldMatcher`, `StarMatch`
- `Sources/PullStarKit/Engine/AlignmentModel.swift`: `FieldAnalysisModel`
- `Sources/PullStarKit/Engine/AlignmentAnalyzer.swift`: `AlignmentAnalyzer`, `AlignmentError`
- `Sources/PullStarKit/Engine/KalmanSmoother.swift`: `KalmanSmoother`
- `Sources/PullStarKit/Engine/CropCalculator.swift`: `CropCalculator`
- `Tests/PullStarKitTests/AlignmentTests.swift`: Comprehensive unit tests for detection, matching, trajectory model, Kalman filter/smoother, common crop, and end-to-end `analyze(...)` pipeline.

### Architectural Details & Faithfulness to Reference
1. **StarDetector** (`Detection.swift`):
   - Accelerate/vDSP background estimation & subtraction:
     - Multi-channel luma conversion (`0.299*R + 0.587*G + 0.114*B`).
     - Bounded analysis downscaling (max dimension 2048) preserving original coordinate mapping.
     - Subsampled percentile linear stretch using `vDSP_vsadd` and `vDSP_vsmul`.
     - 2D grid background estimation with MAD noise floor whitening (`(working - bkg) / max(noise, noiseFloor)`).
     - 3x3 binomial/Gaussian smoothing on whitened image.
   - Multiscale local-peak detection with strict 8-connected local maxima check.
   - Hot-pixel and cosmic ray spike rejection: tests core flux concentration against maximum core ratio (`<= 0.65` in standard, `<= 0.75` in noisy RAW recovery).
   - Diffuse structure rejection: requires core sum `>= 0.20` of total patch flux.
   - Intensity-weighted moment centroiding on 7x7 patch yielding sub-pixel accuracy (`< 0.1` px).
   - Spatial quota dispersion over an 8x6 grid with minimum 4-pixel separation to prevent control point clustering.
   - Supports 'noisy RAW recovery' mode with relaxed SNR and elongated streak PSF acceptance.
   - High-precision ROI star tracker for manual Polaris & second star tracking.

2. **StarFieldMatcher & Asterism Matching** (`AlignmentMatching.swift`):
   - Fast invariant triangle (asterism) pattern matching based on normalized side ratios `(r1, r2)` sorted for fast binary search.
   - Scale consistency check (`0.97 <= scale <= 1.03`).
   - Consensus inlier voting across star candidates.
   - Two iterations of unit-scale 2D rigid least-squares fit (`atan2(Sxy - Syx, Sxx + Syy)` closed-form optimal rotation).
   - Strict correspondence validation: minimum 6 matches, consensus threshold `max(6, min(20, ceil(0.3 * pool)))`, RMS error `<= 1.5`, and spatial spread `>= 20.0`.\n   - Multi-tier candidate budget matching (100, 60, 40) for noisy exposures.

3. **Sky-Rotation-Preserving Trajectory Model** (`AlignmentModel.swift`):
   - Faithful port of `field_alignment.py`.
   - Continuous angle unwrapping across observations.
   - Robust IRLS (Iteratively Reweighted Least Squares) with soft-L1 loss (`noise = 0.002` for angle, `noise = 2.0` for translation) matching SciPy.
   - Linear or normalized circular translation basis `[1, sin(w*t)/w, (1 - cos(w*t))/w^2]`.
   - Computes smooth sky motion at each timestamp and framewise wobble correction matrix `M_smooth(t) @ inv(M_observed)`.
   - Corrects camera vibration while preserving continuous star trail arcs.

4. **KalmanSmoother** (`KalmanSmoother.swift`):
   - 4-state constant velocity model `[x, y, vx, vy]`.
   - Joseph-form covariance updates for numerical stability.
   - Mahalanobis distance outlier detection (`d^2 > 15.0`).
   - Zero-phase bidirectional smoothing for residual wobble tracks.

5. **CropCalculator** (`CropCalculator.swift`):
   - Ports `field_crop` from `backend/engine/field_alignment.py`.
   - Bounding displacement of all 4 image corners under each frame's affine transform.
   - Conservative 2-pixel margin.
   - Guaranteed even width and height for video encoder YUV 4:2:0 compatibility.

6. **AlignmentAnalyzer** (`AlignmentAnalyzer.swift`):
   - Public API: `analyze(frameCount: Int, loadLuma: @escaping @Sendable (Int) async throws -> PixelImage, times: [Double], config: JobConfig, progress: @Sendable (Int, Int, Double, Double) -> Void) async throws -> (transforms: [FrameTransform], crop: CropRegion, referenceStars: [CGPoint], confidence: Double)`.
   - Bounded concurrency with worker pool (`max(1, cpuWorkers ?? processorCount)`).
   - Structured concurrency with cooperative `Task.checkCancellation()`.
   - Handles cloudy/blank frames with automatic skipping and reacquisition.
   - Full support for manual tracking (Polaris + optional second star for rotation correction).

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
  - Settings persisted across launches with `Codable` serialization in `UserDefaults`.
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

## Implementation Sub-agent (Engine Orchestration & Lifecycle: PullStarEngineImpl)

### Owned Files & Responsibilities
- `Sources/PullStarKit/Engine/PullStarEngineImpl.swift`: Production implementation of `PullStarEngine`.
- `Tests/PullStarKitTests/EngineImplTests.swift`: Comprehensive suite of end-to-end unit tests.

### Architectural Details & Faithfulness to Reference
1. **Full Protocol Implementation**:
   - `listSequence(in:sortByTime:)`: Integrates with `SequenceLister`, with security-scoped directory access.
   - `preview(of:maxDimension:)`: Integrates with `PreviewRenderer`, decoding Core Image / RAW and rendering display-ready JPEG data with security-scoped URL access.
   - `detectStars(in:config:)`: Decodes luma via `ImageDecoder.decodeLuma`, executes `StarDetector`, maps star coordinates in original source pixel coordinates, determines the optimal second star candidate (maximum Euclidean separation from primary matching Python `auto_selector.py`), and computes confidence score `[0, 1]` based on star count quota and mean SNR.
   - `computeInfo()`: Returns human-readable hardware string matching UI telemetry format e.g. `"Apple M4 GPU · 10 CPU cores"`.
   - `run(_:)`: Returns `AsyncStream<JobState>` managing the complete job lifecycle through thread-safe `JobExecutionContext`.

2. **Job Stages & Lifecycle**:
   - `preparation`: Ensures output directory exists, enumerates sequence, validates required exposure count (minimum 3 for auto mode, 1 for Polaris/noStack).
   - `conversion`: Active only when `conversionFormat != .none`; batches conversions via `ImageWriter.convertInputs` and manages temporary converted files.
   - `pass1`: Executes `AlignmentAnalyzer.analyze(...)`, yielding smoothed FPS, frame counters, and real-time drift telemetry `(driftX, driftY)`. Sets reference stars in job detection state.
   - `cropCalc`: Validates and yields common bounding crop region from the trajectory analysis.
   - `pass2`: Coordinates `StackPipeline.run(...)`, decodes frames on demand (bounded memory footprint), atomically writes display-ready live previews to system caches, increments `livePreviewRevision`, and emits progress.
   - `videoRender`: Emitted during hardware-accelerated video compilation when `videoEnabled` is true.
   - `done`: Writes final output image (guaranteeing extension matching `imageFormat` without duplicate extensions), sets `resultURL`, `videoURL`, `framesDirectory`, and `frameCount`, and emits status `.completed`.

3. **Stage Weights & Progress**:
   - Matches Python `job_manager.py` weighting logic with monotonic non-decreasing guarantees for `overallProgress`.

4. **Cancellation & Error Handling**:
   - Responsive cancellation through `AsyncStream.onTermination` and `Task.checkCancellation()`. Emits `.cancelling` followed by `.cancelled`.
   - Cleans up partial outputs: temporary live preview files, incomplete videos, and temporary conversion directories.
   - Structured error handling catching all failures, yielding status `.failed` with human-readable error descriptions, and ensuring stream termination. Never crashes.
