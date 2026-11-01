# Release engineering

Build on an Apple Silicon Mac using Python 3.11 and Node.js 24 LTS. Dependencies are pinned in `uv.lock` and `frontend/package-lock.json`.

```bash
uv sync --locked
npm --prefix frontend ci
uv run python scripts/build_backend.py
npm --prefix frontend run package:mac
```

The Python builder collects the backend, MCP implementation, astronomy libraries, RAW decoder, OpenCL bindings, and the imageio-ffmpeg portable executable. Electron Builder packages the backend outside the ASAR archive. The app uses its user-data directory for logs and caches, and never writes inside the installed bundle. The backend binds to loopback port 0 and reports its actual address to Electron before the UI is loaded.

Before publishing, run the full test suite and `scripts/smoke_release.py` against the bundled backend. Open the packaged app from a copied location, verify the frontend and backend connection, inspect the DMG with `hdiutil verify`, and generate SHA-256 sums. Upload the DMG, notices, checksums, and dependency inventory as versioned GitHub release assets. Photo libraries, checkpoints, environments, and build outputs must not enter Git history.

The current configuration makes an ad-hoc-signed arm64 DMG. For Apple distribution, replace `mac.identity: '-'` with the appropriate Developer ID configuration, enable hardened runtime with tested entitlements for Electron and the Python runtime, configure notarization credentials using CI secrets, and notarize and staple the final app/DMG. Do not label an ad-hoc build as notarized. Intel and Windows/Linux binaries require their own native builds and smoke tests.

To test the complete installed UI without a source checkout, set `PULLSTAR_SMOKE_OUTPUT=/tmp/pullstar-installed` when launching `PullStar.app/Contents/MacOS/PullStar`. This writes a JSON health report and screenshot, then quits the app and its service. It does not load photo data or start a render.
