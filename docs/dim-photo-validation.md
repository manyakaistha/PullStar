# Dim-photo detection validation

Validated October 22, 2026 against the supplied `../naman-test-data` collection. No source photographs were modified or added to Git. The comparison baseline is commit `162b8cf`; the final detection implementation is `922a2fb`.

## Sampling and results

The collection contains 977 JPEG/DNG files across three directories. It mixes resolutions, camera orientations, and separate shooting sessions. The validation script separates JPEG bursts by dimensions and by gaps exceeding 30 minutes, then takes the first twelve exposures from the longest consistent burst in each directory. These are representative samples, not a claim of testing every image in the collection.

- Samsung, 8160 × 6120: `20261002_225524.jpg` through `20261002_225926.jpg`. Baseline accepted only its initial reference (1/12). Enhanced processing accepted 11/12, with 21–77 matching stars in accepted later frames; `20261002_225546.jpg` was safely skipped. The final TIFF is 8142 × 6094, 8-bit. Analysis plus rendering took approximately 25.3 seconds.
- March 2023 set, 4080 × 3072: `IMG_20230326_233008559.jpg` through `IMG_20230326_233633588.jpg`. Both versions accepted 12/12. Enhanced processing found 21–96 corresponding stars in later frames and produced a 4074 × 3066 TIFF in approximately 17.2 seconds.
- April 2026 set, 4080 × 3060: `IMG_20260415_041355.jpg` through `IMG_20260415_041757.jpg`. Both versions accepted 12/12. Enhanced processing found 20–89 corresponding stars in later frames and produced a 4070 × 3050 TIFF in approximately 16.7 seconds.

All three outputs were readable, nonempty TIFFs rendered at their full source resolution minus the common crop. Their previews were visually inspected for retained star trails. One uncertain Samsung exposure was rejected rather than inventing a location. Matching uses randomized robust estimation, so exact inlier counts and marginal frame acceptance can vary. Timings describe this sample and development machine.

The final code also passed all 33 automated tests. New tests cover faint 16-bit stars beside saturated highlights, exposure/gain changes, locally varying noise, a small shared stellar field in a large candidate pool, original-pixel coordinates after reduction, and preservation of faint flux during integer-image resampling. Existing blank/noise/hot-pixel rejection, 16-bit rendering, off-image pole, trail extension, video, and checkpoint tests continue to pass. Synthetic image checks verify that detection does not mutate the input array.

## Reproduce

From the repository root:

```bash
uv run --group dev pytest -q
uv run python scripts/validate_dim_detection.py \
  --data-dir ../naman-test-data \
  --baseline-ref 162b8cf \
  --samples 12 --render \
  --output-dir /tmp/dim-star-validation
```

The script writes `report.json`, temporary input links, full-resolution stacks, and display previews outside the source directory. It includes the exact file names and accepted/matched frame counts. `--baseline-report` can reuse a prior report for the same source sample instead of recomputing the older detector.

## Data and decoder limits

Keep a render input folder to one consistently sized sequence. Increasing a white point cannot repair a mixture of different resolutions, rotations, unrelated shooting sessions, or an unsupported RAW encoding.

RAW decoding was probed separately from JPEG alignment. The supplied Vivo `IMG_20260415_014207.dng` decoded as uint16 successfully; this probe does not establish a successful RAW sequence alignment. The Samsung `20261002_223158.dng` uses JPEG-XL-compressed linear DNG and raises `LibRawFileUnsupportedError` with the installed LibRaw build. RAW processing remains unsupported for that encoding; the corresponding JPEG collection was tested above. The [DNG viewer](dng-viewing.md) now displays these Samsung files using their embedded camera renders. Detection preprocessing cannot run on RAW pixels that the processing decoder cannot read.
