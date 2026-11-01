# Exporting images and trails

In the desktop app, load a sequence and use **What would you like to create?**:

- **Aligned images only** corrects camera wobble and exports real exposures with a common crop. It preserves natural sky motion for stacking in another app, and skips stacking, trail synthesis, and video encoding. At least three exposures are required.
- **Star trails** creates the blended trail image and can also export the aligned exposures and a trail-lapse video. At least ten exposures are required.

Reference selection is optional. Automatic field matching estimates camera motion without Polaris. For manual tracking, select Polaris on the first frame; select a second reference and enable rotation correction if needed. Changing the sequence order requires reloading it before placing new references.

## Image formats

Choose TIFF, PNG, or JPEG for the final trail image and aligned sequence. TIFF and PNG keep the developed source's bit depth (8-bit or 16-bit); JPEG uses 8-bit samples and quality 95. If inputs were converted to JPEG, the export cannot recover their original precision. RAW is developed into pixels; exporting an aligned RAW sensor file is not supported.

Individual exposures use a fixed sample range, avoiding per-frame brightness normalization and resulting flicker. Frames are numbered in processing order and keep the original filename stem. `sequence.json` records export order, original source paths, crop dimensions, and skipped frames. Automatic alignment skips frames without a reliable transform.

Enter a filename (trails) or new folder name (images only), or a full destination path. A simple name is placed inside the loaded source folder. With both trails and images selected, the sequence is saved to `<trail-name>_frames` beside the trail image. Existing sequence folders are preserved: choose a new name for another run.

Exports are staged beside their destination. Cancellation or rendering errors remove the staging directory instead of publishing an incomplete sequence. Images-only export holds one exposure and its warped image at a time and does not allocate a stack accumulator. PNG/JPEG trails are written directly, without an intermediate TIFF decode. Exporting both images and trails requires an additional decode/warp pass for the sequence.

Results link to the trail image, video, and aligned sequence separately. Files are already saved locally; the ZIP button is optional for moving a sequence. ZIP archives are built on demand on the destination volume without recompressing images, then deleted after transfer. Allow free disk space for that additional copy when using ZIP.

## Video formats

MP4 and MOV containers are selectable independently of image format. H.264 has high, medium, and lossless presets; ProRes 422 HQ requires MOV, selected automatically by the UI. Resolution can be set independently from images. FFmpeg is required for MOV and advanced presets. Without FFmpeg, high-quality MP4 uses the existing OpenCV fallback. Encoding failures fail the job instead of silently omitting the requested video or changing a selected professional codec.

## Command line

```sh
uv run python main.py -i ./photos -o ./aligned_images --auto \
  --save-frames --no-stack --image-format png

uv run python main.py -i ./photos -o ./trails.png --auto \
  --image-format png --save-frames --video --video-format mov --quality prores
```

`--no-stack` requires `--save-frames` and cannot be combined with trail video. `--image-format` determines the actual image extension. The API exposes the equivalent `no_stack`, `save_frames`, `image_format`, and `video_format` settings.

## Validation and remaining release work

Regression coverage includes automatic/manual image-only export in each format, sample range/bit depth, short sequences, existing-folder protection, cancellation cleanup, stack + sequence + MOV rendering, download links, invalid format combinations, and FFmpeg failure reporting. Browser review covers the loaded workspace, completed export, and narrow layouts.

This change does not establish a signed installer or replace release testing on Windows/Linux and different GPU/RAW combinations. RAW decoding still depends on the camera format supported by the installed decoder. Long sequences still require sufficient disk space for developed inputs, outputs, and optional download archives.

Local validation: 144 Python tests and four subtests, 12 frontend tests, production build, and lint passed. A 12-photo sample from `corr_to_jpeg` exported successfully as aligned PNGs. Encode/decode smoke checks passed for MP4 high/medium/lossless, MOV H.264, and MOV ProRes.
