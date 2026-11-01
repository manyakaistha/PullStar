# Noisy RAW star trails

**Source frames → High-noise RAW recovery → Recover faint and streaked stars** is enabled by default. It changes RAW detection and export; ordinary JPEG/PNG/TIFF processing keeps its existing path. **RAW exposure boost** offers the original exposure or +1/+2/+3 stops. These settings do not rewrite source files.

For the supplied Nothing-phone sequence, leave Polaris unselected, use 1× trail length, enable recovery, and choose **+2 stops**. Start alignment normally. The frames contain only sky, so foreground preservation can be disabled. Leave **Fill timeline gaps** off to retain the actual capture gaps, or enable it to create interpolated samples between exposures. Interpolated samples are synthesized positions, not additional recorded exposures.

## What failed and what changed

The 255 supplied DNGs are 4096 × 3072, 10-bit Bayer samples stored in 16-bit containers, from a Nothing AIN065 phone. Exposures are 25 seconds at ISO 100. Their sky values sit close to the 64-DN sensor black level. White balance, demosaicing, and clipping can distort low-signal candidate shapes; many real stars also form short streaks during an exposure. Finding 100 candidates did not establish a reliable stellar match in the previous path.

- Detection now subtracts each Bayer channel's black level and averages complete 2×2 sensor cells before demosaicing or white balance. Signed dark fluctuations are retained in a float32 analysis image. Centroids are mapped back to the full, oriented image with the correct half-pixel offset. Unsupported sensor layouts fall back to LibRaw development. Sparse round-star fields also retain the established detector's additional centroids.
- Photutils DAOFIND measures short streaks as well as round points. Aperture checks and isolated-pixel rejection retain genuine stellar candidates, with spatial quotas to avoid concentrating every control in one cluster.
- FFT phase correlation seeds short RAW offsets. It never authorizes alignment by itself: source centroids must pass the same match-count, confidence, rigid-fit, residual, and field-spread checks. Unrelated centroids are rejected even when noise textures correlate strongly.
- Nearby exposures are matched first to avoid long-baseline PSF and projection changes. The original field is revisited every twenty frames when possible, and retained as a reacquisition fallback.
- Local Wiener shrinkage reduces noise in linear, 16-bit-derived colour data before display gamma and stacking. It reduces averaging in high-signal structure to preserve stars. RAW exposure boost is applied during development. CPU decoding/denoising remains bounded by the existing worker and memory limits; GPU Lanczos warps and stacking remain available.
- Cancellation checks, staged publication, and CPU fallback remain in place. RAW settings are included in automatic star-field checkpoint signatures so a stack cannot silently resume with a different exposure/noise treatment. Worker memory estimates include the new float32 denoising buffers.

This is conservative spatial noise reduction, not calibrated dark/flat subtraction or a photometric measurement pipeline. Very faint structure may be attenuated. No denoiser can recover information that was not recorded, and exposure boost amplifies remaining noise too. The recovery switch allows comparison with ordinary RAW development. The installed LibRaw must still support the RAW compression; embedded JPEG viewing alone does not make Samsung JPEG-XL RAW pixels processable.

## Validation on the supplied archive

Downloaded the public Drive archive `1lTweXOmcVpZbubRve4l989j7hXdT95kA`: 6,425,120,256 archive bytes, containing 255 DNGs. Extraction rejected unsafe paths and non-file/directory entries. SHA-256 was recorded for every extracted file and verified after rendering.

- Capture span: October 21, 2026, 00:52:24–02:46:05, about 114 minutes. Most intervals are 26 seconds; one is 144 seconds and three are 52 seconds.
- The current detection action matched 27 stars without Polaris in the production UI. Full analysis accepted **255/255 exposures**, with no skipped frames. Nearby pairs typically matched around 80–90 stars.
- The full unfilled render is **4078 × 3052, uint16 TIFF**, with a 14-pixel maximum crop margin and +2 EV. It contains the measured exposure span and preserves the actual gaps. It was visually checked at full-frame and preview sizes.
- Development hardware: Apple M4, 16 GB RAM, four CPU workers and OpenCL GPU rendering. Analysis took about 148 seconds including the initial detection probe; full rendering took about 141 seconds. These are local measurements, not performance guarantees.
- Six actual frames sampled across the capture span were developed at +2 EV through both paths. Robust high-frequency luminance MAD after recovery was 52–56% of the ordinary-development value, a median reduction of about 46%. This measures per-frame sky texture, not a claimed 46% improvement in whole-stack SNR. Synthetic fixtures independently check stellar flux preservation.
- Source hashes for all 255 DNGs were unchanged. The full UI workflow additionally creates a gap-filled version from this same sequence.
- 100 Python tests and 11 frontend/launcher tests passed, along with the production build. Coverage includes noisy elongated stars, hot-pixel rejection, strongly correlated noise without stellar consensus, rotated RAW coordinates, variance/flux preservation, cancellation, 16-bit export, CPU/GPU agreement, and failed-GPU replay.

The archive, extracted inputs, hash inventory, diagnostics, and render reports are outside the repository under `.codex-validation/noisy-dng-1lTweXOmcVpZbubRve4l989j7hXdT95kA` in the project parent. Deliverable TIFF/JPEG files are in `results/2026-10-21-noisy-raw`, also outside the repository. Source photographs and large results are not committed to GitHub.

Reproduce through the application CLI:

```bash
uv sync
uv run python main.py --input '/photos/dng images' --auto \
  --raw-exposure 2 --output '/photos/results/star-trails.tiff'
```

To write a source hash manifest, full-resolution JPEG, preview, and validation report:

```bash
uv run python scripts/validate_noisy_raw.py \
  --input-dir '/photos/dng images' --output-dir '/photos/results' --raw-exposure 2
```

The validator supports `--fill-gaps`, `--cpu-only`, and `--no-recovery`. Its input and output folders must be separate. The wrapper was exercised on a twelve-frame subset of the supplied archive; the full 255-frame processing and production UI were validated separately through the same engine.

Related references: [rawpy's sensor access](https://letmaik.github.io/rawpy/api/rawpy.RawPy.html), [Photutils DAOFIND](https://photutils.readthedocs.io/en/stable/api/photutils.detection.DAOStarFinder.html), and [Siril maximum-pixel trail stacking](https://siril.readthedocs.io/en/stable/preprocessing/stacking.html#pixel-maximum-stacking).
