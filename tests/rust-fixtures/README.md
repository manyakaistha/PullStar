# PullStar Deterministic Verification Fixtures (P0-03)

This directory contains deterministic, portable verification artifacts and ground-truth oracle evaluations used to validate the Rust rewrite (`pullstar-domain`, `pullstar-io`, `pullstar-astro`, `pullstar-render`, `pullstar-engine`, `pullstar-cli`, `pullstar-service`, and `pullstar-mcp`).

All fixtures conform to **Schema Version 1** (`schema/fixture_v1.schema.json`), matching `pullstar_domain::INTERCHANGE_SCHEMA_VERSION`.

## Structure

- `manifest.json`: Complete serialized ground-truth data including frame metadata, detected centroid coordinates, pairwise match sets, 2x3 row-major affine transformation matrices, common crop boundaries, video/synthesis step repeat schedules, negative case rejection expectations, and stack quality metrics.
- `hashes.json`: SHA-256 digests for every committed artifact.
- `schema/fixture_v1.schema.json`: Formal JSON Schema (Draft 2020-12) defining the version 1 fixture interchange format.
- `generate.py`: Deterministic generator script that runs with `.venv/bin/python` to recreate all synthetic images and oracle measurements.
- `verify.py`: Verification harness that confirms file hashes, schema compliance, oracle numerical parity, and generation idempotence.
- `images/standard/`:
  - `frame_00.png` through `frame_04.png`: 5-frame 240×320 synthetic starfield sequence with controlled Gaussian PSF stars, sky rotation around an off-screen center, and alternating camera jitter.
  - `frame_00.jpg`: 8-bit lossy JPEG reference (quality 95).
  - `frame_00_8bit.tiff`: 8-bit uncompressed TIFF reference.
  - `frame_00_16bit.tiff`: 16-bit uncompressed TIFF reference (values scaled by 257).
  - `synthetic_stack_preview.tiff`: Reference lighten-blend stack of the 5-frame standard sequence.
- `images/raw/`:
  - `dark_cfa_00.dng`, `dark_cfa_01.dng`, `dark_cfa_02.dng`: 384×512 10-bit Bayer CFA DNGs with black level (64 DN), white level (1023 DN), DNG metadata tags, anchor exposure strips, and sub-pixel shifted star positions for tracking verification.
  - `embedded_preview_only.dng`: DNG container with a deliberately undecodable RAW strip (tagged with unsupported compression ID 52546) and a valid embedded JPEG SubIFD (EXIF orientation 6). Exercises embedded-preview extraction without full RAW codec invocation.
- `images/negative/`:
  - `blank_zeros.png`: Completely zeroed frame.
  - `pure_noise.png`: Zero-star Gaussian noise floor (mean 25, std 4).
  - `unrelated_field.png`: Completely independent stellar field from a distinct seed; fails triangle consensus matching.
  - `hot_pixels_only.png`: Single-pixel impulsive noise (1×1 spikes at 255) to verify blob-area and PSF rejection.
  - `dim_streaked_sources.png`: Faint low-SNR linear streaks to verify rejection of non-stellar elongation.

## Provenance and Oracles

- **Image Generation**: Synthesized with fixed NumPy random seeds (`28`, `42`, `100-102`, `999`, `7777`) and standard mathematical PSF formulas (Gaussian $\sigma = 1.4\text{--}1.6\text{ px}$).
- **Source Detection**: Evaluated with `modules.astronomy.detect_sources` (Photutils DAOStarFinder / local peak detection).
- **Matching & Registration**: Evaluated with `modules.astronomy.match_images` (Astroalign triangle matching) and `backend.engine.field_alignment.analyze_field` (least-squares robust trajectory fitting).
- **Manual Tracking**: Evaluated with `modules.tracker.FrameTracking` and `modules.transform.calculate_transforms_from_tracking` / `calculate_common_crop`.
- **Schedules**: Evaluated with `core.video_schedule.video_step_repeats`.
- **Quality Evaluation**: Evaluated with `mcp_server.diagnostics.evaluate_stack_image`.

## Regeneration and Verification

To regenerate all fixtures from scratch:
```bash
.venv/bin/python tests/rust-fixtures/generate.py
```

To verify all file hashes, schema conformance, numerical parity, and generation idempotence:
```bash
.venv/bin/python tests/rust-fixtures/verify.py
```

The verification harness enforces:
1. **Hash match**: Every artifact matches its committed entry in `hashes.json`.
2. **Schema conformance**: `manifest.json` validates against `schema/fixture_v1.schema.json`.
3. **Parity**: Centroids match within $10^{-4}\text{ px}$, transforms within $10^{-4}$, and crops match exactly.
4. **Idempotence**: A second generation run generates a byte-identical manifest.
5. **Size constraint**: The entire fixture directory remains under 5 MB (measured ~1.91 MB).

## What is Intentionally Not Redistributable

The 255-frame real-world DNG dataset (4096×3072, ~5 GB) referenced in `docs/noisy-raw-recovery.md` and `docs/rust-migration-plan.md` lives outside the Git repository on private local storage. It is not redistributable in Git due to repository size constraints and licensing. The deterministic CFA DNGs provided here (`dark_cfa_*.dng`) serve as small, portable, and reproducible stand-ins for CI and local Rust development.
