# DNG viewing

Load the folder containing your photos, then select a DNG in the filmstrip. The studio displays a JPEG preview in the main viewfinder, with the usual zoom, pan, and reference picking. No conversion of your source files is needed.

## Rendering

The viewer first extracts the camera's rendered preview using [rawpy's thumbnail API](https://letmaik.github.io/rawpy/api/rawpy.RawPy.html#rawpy.RawPy.extract_thumb). A full-resolution camera preview can be displayed even if LibRaw cannot unpack that DNG's RAW encoding. This is how the supplied Samsung JPEG-XL linear DNGs are viewed.

For files without a full-size embedded render, the viewer uses 8-bit sRGB development with camera white balance, automatic display brightness, and the portable AHD demosaic algorithm. It does not invoke the export pipeline's optional LMMSE algorithm or its 16-bit Lab noise reduction. If decoding is unavailable but a smaller embedded render exists, that render is resized to the original pixel dimensions for reference picking; enlarging it does not recover missing detail.

Embedded JPEG orientation is applied exactly once. If the JPEG has no orientation tag, the viewer uses the RAW's orientation instead. Demosaiced images use LibRaw's orientation. Metadata dimensions describe the oriented view, so portrait photos and their reference coordinates agree.

The main preview retains the full oriented pixel dimensions. The filmstrip requests `/api/images/preview?path=...&max_size=256`; embedded JPEGs are decoded at reduced resolution, and files requiring demosaicing use half-size development before the final reduction. Ordinary JPEG/PNG delivery and original-file downloads remain unchanged. Source DNGs are never rewritten.

These are **display previews**. Star detection, alignment, and export continue to load the original image through the processing decoder. In particular, viewing Samsung JPEG-XL DNGs does not make their RAW pixels decodable by the installed LibRaw build. Use a supported RAW encoding or a separately converted image sequence for those processing operations.

## Pink previews and failed detection

Update both source and Python dependencies: close the app, run `git pull --ff-only` and `uv sync` from the repository root, then `cd frontend` and `npm start`. The minimum RAW decoder is now **rawpy 0.27.1**, including in `uv.lock` and `requirements.txt`.

The previous lock selected rawpy 0.26.0. Its default per-channel black correction is zero ([upstream source](https://github.com/letmaik/rawpy/blob/v0.26.0/rawpy/_rawpy.pyx#L1192-L1197)), which causes LibRaw to override the camera's black levels and clear a repeating DNG black table ([LibRaw's implementation](https://github.com/LibRaw/LibRaw/blob/0.22.0/src/utils/utils_libraw.cpp#L446-L461)). On the supplied dark Vivo photos, the resulting sensor bias was amplified by white balance and display brightness into a magenta sky. Rawpy 0.27.1 preserves the native settings when no override is supplied ([corrected upstream code](https://github.com/letmaik/rawpy/blob/v0.27.1/rawpy/_rawpy.pyx#L1288-L1292)). No guessed white balance or colour desaturation is applied to hide the error.

The corrected pipeline also:

- Reads DNG capture times from EXIF instead of relying on modification times changed by copying or ZIP extraction.
- Retries field matching with the strongest 60/40 candidates when faint noise defeats the full candidate pool. Original consensus counts, confidence denominator, residual limits, and rigid-transform checks still apply.
- Uses portable AHD development when the optional LMMSE demosaic pack is absent.
- Performs chroma reduction in normalized float32 before restoring uint16, because OpenCV cannot convert uint16 directly to Lab.
- Reports an unsupported RAW decoder with the offending filename instead of confusing it with an insufficient-star match. Embedded previews are never silently substituted for the original RAW pixels in an export.

The earlier viewing validation below checked readable content and dimensions but did not catch the colour error. New regressions cover actual dark CFA decoding, black-level preservation, matched centroids, capture order, a complete twelve-DNG alignment/export job, and clear errors for viewable but undecodable RAWs.

### Verification after the correction

Validated with rawpy 0.27.1 / LibRaw 0.22.1 and a fresh environment from `uv.lock`:

- All 89 nonempty supplied DNGs displayed; the one zero-byte DNG was rejected. Source SHA-256 hashes were unchanged.
- All ten Vivo files decoded for tracking. A consistent five-exposure burst (`IMG_20260415_014750.dng` through `IMG_20260415_014921.dng`) passed field analysis. The production studio detected 31 matched stars at 25.2% confidence, without Polaris, and showed no alerts.
- The five real exposures passed the analysis/render stages on both CPU and Apple M4 OpenCL, including 1.5× extension and foreground masks. Both TIFFs were readable uint16, 4074 × 3054, differing by at most one 16-bit brightness level; source bytes were unchanged.
- Desktop jobs require ten inputs, so the five-photo check is a rendering-stage validation. The complete production studio job was additionally exercised with twelve generated CFA DNG fixtures, and saved a readable 16-bit TIFF.
- Regression checks on three real JPEG bursts accepted all twelve exposures in each burst. One initial check was blocked by temporary-disk space; rerunning that collection with output on the project volume passed.
- 91 Python tests, 11 frontend/launcher tests, and the production frontend build passed. Windows hardware was not available for an end-to-end check.

The subsequently supplied 255-frame Nothing-phone TAR archive has now been downloaded and validated, including full-sequence 16-bit rendering. See [noisy RAW recovery](noisy-raw-recovery.md) for the new sensor-domain processing path and results. The available Samsung JPEG-XL DNGs still require conversion to a supported RAW encoding or 16-bit TIFF for processing; their embedded views alone do not make them processable.

Local diagnostic artifacts are under `/tmp/staraligner-dng-investigation`: `previews-fixed/report.json`, `analysis-fixed.json`, `processing-report.json`, and CPU/OpenCL TIFFs. The all-file preview check is reproducible using the command below.

## Earlier viewing validation

Validated October 22, 2026 against every DNG in the supplied `../naman-test-data` collection, using a fresh Python 3.11 environment installed from `uv.lock` (rawpy 0.26.0 / LibRaw 0.22.0).

- Samsung collection: all 79 nonempty DNGs produced readable full-resolution views and 256-pixel filmstrip previews. Their oriented dimensions included 4284 × 5712, 5712 × 4284, and 6120 × 8160.
- Vivo collection: all 10 DNGs, which have no embedded preview, produced readable full-resolution views and filmstrip previews. Two photos were portrait, 3060 × 4080; eight were landscape, 4080 × 3060.
- `20261002_230032.dng` is a zero-byte file. The preview endpoint correctly returned HTTP 422; it contains no image to decode.
- SHA-256 checks before and after previewing confirmed that all source bytes were unchanged.

The full collection check took approximately 33 seconds on the development machine. Median API times were 0.22 seconds for a full view and 0.06 seconds for a filmstrip preview; median thumbnail payload was about 7 KB. These are local sequential measurements, not a hardware-independent performance guarantee.

Both collections were also loaded into the studio UI. Full views, thumbnails, switching frames, portrait/landscape orientation, and zoom were checked without preview or console errors for valid files. The production frontend build passed. All 46 automated tests passed in the fresh environment, including 13 DNG regressions covering actual LibRaw CFA decoding, embedded JPEGs with undecodable RAW strips, orientation, thumbnail dimensions, source preservation, and malformed/empty files.

Reproduce the checks from the repository root:

```bash
uv sync --group dev --frozen
uv run --group dev pytest -q
uv run --group dev python scripts/validate_dng_previews.py \
  --data-dir ../naman-test-data \
  --output-dir /tmp/dng-preview-validation
cd frontend
npm ci
npm run build
```

The validator writes a per-file JSON report and a sample JPEG per collection outside the source directory. It reports successful previews, empty files rejected with HTTP 422, and unexpected failures separately. It returns a nonzero exit code for unexpected failures.
