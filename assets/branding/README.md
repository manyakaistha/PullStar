# PullStar icon — constructed geometry

The editable source is `star-aligner.svg`. All artwork is built from formulas in `scripts/generate_app_icons.py`; no image generation service or generated bitmap is involved.

## Geometry

The canvas is 1024 × 1024 units. The tile is a superellipse centered at (512, 500), with half-width 428 and exponent 4.5:

    |(x − 512)/428|^4.5 + |(y − 500)/428|^4.5 = 1

Its parametric form is sampled at 512 points. Five circular trails share that exact center. Their radii are 112, 179, 246, 313, and 380 units. Their respective start/sweep angles are −155°/240°, −109°/268°, −160°/250°, −111°/264°, and −149°/236°. Each trail is a filled outline with width `w(t) = 0.5 + (W − 0.5)t^0.85`, progressing from a fine tail to a semicircular head. A neutral white gradient keeps the trails bright against the near-black tile. A four-point pole star marks their center.

The glass treatment consists of a midnight gradient, a faint upper reflection, a two-unit rim, and small stroke shadows. There are no photographic textures.

## Regeneration

After `npm ci` in `frontend`, run from the repository root:

    uv run python scripts/generate_app_icons.py

The script writes the SVG, rasterizes it with the project's Electron/Chromium at 2×, downsamples with Lanczos, and creates:

- `frontend/resources/icons/icon.png`: 1024px PNG for Linux and Electron runtime.
- `frontend/resources/icons/icon.icns`: multi-resolution macOS bundle icon.
- `frontend/resources/icons/icon.ico`: multi-resolution Windows application/installer icon.
- `frontend/public/app-icon.svg`: crisp in-app logo and browser favicon.
- `frontend/public/app-icon.png` and `favicon.ico`: raster previews/fallbacks.

Electron sets the Dock icon on macOS and the window icon on Windows/Linux. The packaged macOS app uses `frontend/electron-builder.yml`, which includes the icon, standalone backend, license notices, and DMG layout.
