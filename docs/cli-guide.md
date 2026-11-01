# PullStar command-line guide

Run `uv sync --locked` from the repository root. For source-based video export, install FFmpeg and make it available on `PATH`.

## Align and create trails

```bash
uv run python main.py --input /path/to/exposures --auto --output /path/to/trails.tiff
```

Automatic alignment matches the stellar field and removes camera wobble while preserving natural sky motion. It does not require Polaris in the frame. Without `--auto`, the CLI can use manual reference selection; run `uv run python main.py --help` for the current controls.

## Export aligned images for another editor

```bash
uv run python main.py --input /path/to/exposures --auto \
  --output /path/to/new-aligned-folder --save-frames --no-stack --image-format tiff
```

Choose `tiff`, `png`, or `jpg`. The destination folder must not already exist. The exported sequence uses a common crop. TIFF and PNG preserve 16-bit processing data; JPEG is 8-bit and lossy. RAW inputs are developed into these formats, not saved as RAW or DNG.

## Save a stack and its aligned frames

```bash
uv run python main.py --input /path/to/exposures --auto \
  --output /path/to/trails.png --image-format png --save-frames
```

The sequence is written to a sibling folder with `_frames` appended to the output stem.

## Choose video delivery

```bash
# H.264 MP4
uv run python main.py --input /path/to/exposures --auto \
  --output /path/to/trails.tiff --video --video-format mp4 --quality high

# ProRes MOV for editing
uv run python main.py --input /path/to/exposures --auto \
  --output /path/to/trails.tiff --video --video-format mov --quality prores
```

`--video-fps` sets the frame rate. `--video-resolution` accepts `source`, `4k`, `2k`, `1080p`, or `720p`. `--video-slowdown` accepts `1`, `2`, `4`, or `8`; higher values create more snapshots per exposure interval. ProRes requires MOV. Images-only mode cannot generate a trail video.

Use `--image-resolution` to lower working-image dimensions and reduce memory/processing cost. Resolution presets never upscale a smaller source. `--convert jpg` or `--convert tiff` develops inputs once before alignment; `--conversion-dir` retains those developed inputs instead of using temporary storage.

Synthetic extension is optional: `--extension 1.5` extends the modeled trajectory. `--tail-taper` controls fading of that synthetic tail, and `--tail-angle-threshold` limits its angular growth. Synthetic frames do not recover missing observed detail. Consult the [algorithm guide](automatic-star-alignment.md), [export workflow](export-workflow.md), and `--help` before long renders.
