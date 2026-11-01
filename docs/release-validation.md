# PullStar 1.0.0 validation

Validated on Apple Silicon, macOS 27.0.1, on 2026-11-01.

- Python application suite: **146 passed**, plus **4 subtests passed**. Test discovery is restricted to `tests/`, so packaging directories cannot accidentally add third-party test suites.
- Frontend: **12 tests passed**, TypeScript/Vite production build passed, ESLint passed.
- `npm audit --omit=dev`: **0 vulnerabilities**. The full development-tool audit reports 26 moderate findings associated with the minimatch dependency chain; no high or critical findings remain in the resolved lockfile. These build tools and npm dependencies are excluded from the shipped ASAR.
- Standalone backend: exercised through its real stdio MCP transport from a temporary directory, with `PATH=/usr/bin:/bin`. Discovered all 15 tools and inspected a 12-frame synthetic sequence. Exported aligned TIFF/PNG/JPEG sequences with correct 16-bit/8-bit output and no stack. Created PNG trail images with H.264 MP4 and ProRes MOV videos through the bundled FFmpeg. No malformed MCP protocol messages were emitted.
- Installed desktop: copied the `.app` outside the checkout, launched it, confirmed the PullStar UI and bundled API health response, captured the workspace screenshot, and verified the app and backend exited. No source `.venv` is used by the installed app.
- Signature: `codesign --verify --deep --strict` passed for the copied app and the app mounted from the DMG. This is an **ad-hoc** signature, not an Apple Developer ID signature or notarization.
- Installer: `hdiutil verify` passed. The DMG mounts successfully, contains the Applications shortcut, and its main executable, backend, and ASAR hashes match the tested copy. Metadata identifies `io.github.manyakaistha.pullstar`, version `1.0.0`, and minimum macOS `14.0`.

The binary is Apple Silicon only. A fresh-machine installation, Intel build, and Apple notarization have not been verified. The workflow and automated tests do not establish that every camera-specific RAW encoding is supported or that every photo sequence will align successfully. Real-data algorithm validation from earlier development is documented separately in the astronomy and RAW guides.
