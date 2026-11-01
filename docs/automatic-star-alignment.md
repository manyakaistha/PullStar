# Automatic star alignment

The app automatically matches stars whenever a job has no manual Polaris selection. Use **Detect references** to preview their pixel positions, then **Start alignment**. The CLI equivalent is:

```bash
python main.py --input /path/to/exposures --auto --output /path/to/trails.tiff
python main.py --input /path/to/exposures --auto --extension 1.5 --output /path/to/longer-trails.tiff
```

Install with `uv sync` or `pip install -r requirements.txt`. Automatic processing runs offline, without a catalogue download, API key, observer location, or visible pole star. The app requires at least ten exposures; at least six stars must match in half the exposures. Blank or cloudy frames are skipped and reported as zero-based `skipped_frames` in job updates. Tracking resumes when stars reappear.

The default runtime is Python 3.11. Use that runtime on recent macOS releases: a fresh Python 3.10 install selected SciPy 1.15.3, whose wheel failed to load here with `__DATA/__thread_bss` validation errors. The failure is also described in the [upstream SciPy issue](https://github.com/scipy/scipy/issues/25635). The Python 3.11 environment uses the newer SciPy wheel.

## Detection and matching

[Photutils DAOStarFinder](https://photutils.readthedocs.io/en/stable/user_guide/detection.html) measures centroids in an enhanced analysis copy. Shape checks reject isolated hot pixels and extended objects. The detector retains up to 100 separated sources and returns their coordinates in the original image's pixels. RAW detection uses the same rawpy loader as manual processing.

### Dim exposures

Enhancement is automatic for **Detect references** and automatic alignment; no white-point adjustment is required in the UI. The analysis copy uses percentile black/white points, sky subtraction, and a local background-noise map from [Photutils Background2D](https://photutils.readthedocs.io/en/stable/user_guide/background.html). Mild smoothing and several star-size kernels help locate faint sources. Extended bright foreground structures are masked, and source selection is spread across the image so bright roofs and walls cannot consume every control point.

A brightness multiplier alone increases noise along with stars. Local noise normalization and aperture checks are therefore used together with the stretch. Hot-pixel and compactness checks remain active, and positions must agree between exposures. For large candidate pools, twenty precise correspondences suffice; small pools retain the earlier 30% consensus requirement and six-star minimum.

Detection images are limited to a 2048-pixel longest side to reduce sensor/JPEG noise and processing memory on large photographs. Resampling happens in floating point so weak signals do not round away. The original-pixel coordinate mapping includes the resize pixel-centre offset. Original photographs, preview exposure, stacking inputs, and export bit depth are not changed by this enhancement.

[Astroalign](https://astroalign.quatrope.org/en/latest/api.html) matches triangle patterns between exposures. Matches must agree on a rigid field transform, with at least six corresponding stars, sufficient spatial separation, plausible scale, and small residual errors. A subsequent rigid fit removes spurious scale changes. Matching against the last valid frame allows reacquisition when the first field no longer overlaps enough.

This identifies corresponding image sources, **not catalogue names or celestial coordinates**. `polaris` is null in automatic detection responses. A fitted `rotation_center`, when measurable, can lie outside the image; it is a geometric estimate, not an identification of Polaris.

## Keeping the trails

Registering every exposure directly onto the first exposure would collapse moving stars back into points. Instead, automatic alignment fits a robust constant-speed rotation and circular translation trajectory across time and corrects only departures from that smooth path. Very small rotations use a linear translation model. Positive, usable exposure timestamps determine the trajectory's timing; otherwise frames are treated as evenly spaced.

Without pointing metadata or a fixed ground reference, smooth camera drift cannot be distinguished completely from smooth sky motion. Automatic mode removes framewise wobble while retaining the fitted motion. Severe lens distortion, clouds obscuring most stars, little field overlap, or deliberate camera pans can prevent reliable matching. Manual Polaris tracking remains available when its coordinates are known.

Synthetic interpolation, gap filling, and trail extension use relative transforms along the fitted trajectory. They work with an off-image pole and with almost pure translation, without assuming rotation about the image centre. Foreground masks apply to synthetic frames. The real frames retain their original scene content. Output cropping includes translation and roll, and produces even dimensions for video encoders.

Automatic recovery uses an output-specific `.field-checkpoint.npz` file, with input and settings validation. A completed render removes its checkpoint. Video jobs replay the schedule on resume to retain the start of the video. When FFmpeg cannot execute, video export falls back to OpenCV.

## API

`POST /api/stars/detect` accepts `{"path": "/path/to/exposures", "frame_step": 10, "sort_by_time": true}`. Its response includes `reference_stars` as `(x, y)` pixel pairs in `reference_image`, `second_star`, `confidence`, `num_inliers`, `rotation_angle` in degrees, `rotation_center`, `method`, and `selection_mode: "star_field"`. Confidence summarizes matching agreement and residual precision; it is not a probability of catalogue identification. No reliable match returns HTTP 400; an invalid frame step returns HTTP 422.

`POST /api/jobs` uses automatic field matching when `polaris_x` and `polaris_y` are omitted. Supplying both coordinates retains manual tracking. `extension_factor`, `ghost_frames_per_real`, `fill_gaps`, `use_foreground_mask`, video options, and recovery options also apply to automatic jobs.

## Validation

Run the regression suite with:

```bash
uv run --group dev pytest -q
cd frontend && npm run build
```

The tests use real Photutils/Astroalign calculations on deterministic synthetic skies: centroid precision and hot-pixel rejection at both bit depths, unrelated/blank fields, large motion, an off-image pole, camera translation and roll, preserved trail motion, cloudy-frame reacquisition, pure translation with extension, conservative cropping, HTTP validation, 16-bit rendering, monotonic progress, interrupted render recovery, and playable video output.

All 27 tests passed in both the existing Python 3.11 environment and a fresh Python 3.11 environment installed from the lockfile. The committed source was separately extracted and tested, and its frontend production build passed. The current application workspace's frontend build also passed.

A separate real-image check used twelve exposures from `corr_to_jpeg`, each cropped to 1800 × 1300 pixels to exclude the estimated pole. All twelve frames matched, with 45–92 correspondences in later exposures. Analysis and a 1.5× extended stack took about 6.6 seconds on the development machine and produced a 1792 × 1292 TIFF. The browser workflow separately detected 45 stars, completed a job without Polaris, and displayed the resulting stack. These timings describe this sample and machine, not a general performance guarantee.

The dim-exposure update adds six regression cases (33 tests total) and a full-resolution comparison on the supplied `naman-test-data` collection. See [dim-photo validation](dim-photo-validation.md) for exact sample ranges, results, and decoder limits.
