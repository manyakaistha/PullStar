# PullStar for iPad — architecture & work split

Native Swift 6 / SwiftUI app (iPadOS 26, Liquid Glass design, iPad-only). Feature parity with the desktop app (React UI in `frontend/src`, Python engine in `backend/engine`). No Python/ffmpeg/OpenCV: everything is Core Image, Accelerate, Metal, AVFoundation, ImageIO.

## Layout
- `ios/PullStarKit` — SwiftPM library (engine + models). Builds & tests on macOS: `cd ios/PullStarKit && swift build && swift test`.
- `ios/PullStar` — SwiftUI app sources. `ios/project.yml` is XcodeGen: `cd ios && xcodegen generate`. Build: `xcodebuild -project PullStar.xcodeproj -scheme PullStar -destination 'generic/platform=iOS' -derivedDataPath /tmp/<yourname>-dd CODE_SIGNING_ALLOWED=NO build` (**use your own derivedDataPath**; several agents build concurrently).
- Contract (already written, do not break signatures; additive changes OK): `Models/JobConfig.swift`, `Models/JobState.swift`, `Models/Geometry.swift`, `Engine/PullStarEngine.swift`.

## Rules
- Only edit files you own (listed in your task). If you need a change elsewhere, add a note to `docs/ios/NOTES.md` under your name and work around it.
- Swift 6 strict concurrency; no force-unwraps on I/O; no third-party packages.
- Port behaviour from the Python source faithfully (read it; constants, thresholds, formulas).
- Don't commit. The orchestrator commits.
- Write unit tests (swift-testing) for engine code using synthetic data. Keep `swift test` green.
- Finish with a short report: files created, what works, what is stubbed.

## Engine modules (PullStarKit)
| Module | Python source | Owner files |
|---|---|---|
| IO: sequence listing, decoding (JPEG/PNG/TIFF/HEIC/RAW via CIRAWFilter), preview, image writers (16-bit TIFF/PNG, JPEG) | `backend/api/images_router.py`, `alignment_engine.py` (_convert_inputs, _resize_inputs) | `Sources/PullStarKit/IO/*` |
| Detection + alignment + Kalman + crop (pass 1) | `alignment_engine.py` run_pass1, `field_alignment.py`, `pipeline.py` pass1_analysis | `Sources/PullStarKit/Engine/Detection*.swift, Alignment*.swift, Kalman*.swift, Crop*.swift` |
| Stacking + trails + video (pass 2) | `pipeline.py` pass2_stacking, `render_backend.py`, `live_preview.py`, `field_alignment.py` stack_field | `Sources/PullStarKit/Engine/Stack*.swift, Trail*.swift, Warp*.swift`, `Sources/PullStarKit/Export/*` |
| Orchestrator `PullStarEngineImpl` (job lifecycle, cancel, checkpoints, progress) | `services/job_manager.py`, `alignment_engine.py` | `Sources/PullStarKit/Engine/PullStarEngineImpl.swift` |

## UI (PullStar app)
Mirrors `frontend/src/components/*`: WorkspaceNav, MainStage, CelestialViewfinder (zoomable viewer, reference star selection, filmstrip), ParameterBays (Source frames / Build your alignment / Output sections, advanced disclosures), LiveTelemetry (progress, drift, fps, compute), Controls (start/cancel). Use iPad idioms: `NavigationSplitView`, inspector, toolbars, pointer hover + Pencil/touch gestures, keyboard shortcuts, Stage Manager friendly resizable layouts, Liquid Glass materials (`.glassEffect`), Dynamic Type, accessibility labels, dark theme matching the web app's palette (see `frontend/src/index.css`, `App.css`).

App state: `@Observable AppModel` (owned by UI shell agent) holds `JobConfig` draft, sequence, selection, `JobState`, and an `any PullStarEngine`. `MockEngine` (in app target) simulates progress for UI development.
