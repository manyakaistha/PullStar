import numpy as np
import cv2
import os
from pathlib import Path
from typing import Callable, Optional, Tuple, List, Dict, Any
import sys
import math
import json
import tempfile
from contextlib import closing
from tempfile import TemporaryDirectory
from core.cancellation import CancellationToken
from core.compute import worker_count, configure_native_threads
from core.trail_effects import validate_tail_settings
from core.parallel import ordered_map
from backend.engine.render_backend import AccelerationError

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config import (
    DEFAULT_BLEND_MODE,
    CHECKPOINT_INTERVAL,
    CHECKPOINT_DIR,
    SEARCH_WINDOW_SIZE,
    MAX_JUMP_THRESHOLD,
    STAR_THRESHOLD_PERCENTILE,
    MIN_BLOB_AREA,
    MAX_BLOB_AREA,
)
from modules.io_utils import convert_image_for_stacking, get_image_info, get_image_list, load_image
from modules.tracker import TrackingResult
from modules.transform import TransformData, calculate_common_crop, calculate_translation_matrix
from core.validator import validate_inputs, validate_image_consistency
from core.checkpoint import save_checkpoint, load_checkpoint
from core.resolution import fit_dimensions, normalize_resolution

class AlignmentEngine:
    def __init__(self,
                 input_dir: Path,
                 output_file: Path,
                 extension_factor: float = 1.0,
                 tail_taper_strength: float = 0.0,
                 tail_angle_threshold: float = 0.0,
                 use_rotation: bool = False,
                 use_kalman: bool = True,
                 kalman_process_noise: float = 0.01,
                 kalman_measurement_noise: float = 2.0,
                 blend_mode: str = DEFAULT_BLEND_MODE,
                 video_enabled: bool = False,
                 video_fps: int = 30,
                 video_slowdown: int = 1,
                 image_resolution: str = "source",
                 video_resolution: str = "source",
                 quality: str = "high",
                 video_hyperlapse: bool = False,
                 use_foreground_mask: bool = True,
                 ghost_frames_per_real: int = 10,
                 synthetic_fade_factor: float = 0.2,
                 fill_gaps: bool = False,
                 save_frames: bool = False,
                 no_stack: bool = False,
                 image_format: str = "tiff", video_format: str = "auto",
                 use_checkpoint: bool = True,
                 resume: bool = False,
                 sort_by_time: bool = True,
                 progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
                 cancellation_token: Optional[CancellationToken] = None,
                 compute_backend: str = "auto", cpu_workers: Optional[int] = None,
                 raw_noise_reduction: bool = True, raw_exposure_ev: float = 0.0,
                 search_window_size: int = SEARCH_WINDOW_SIZE,
                 max_jump_threshold: float = MAX_JUMP_THRESHOLD,
                 star_threshold_percentile: float = STAR_THRESHOLD_PERCENTILE,
                 min_blob_area: int = MIN_BLOB_AREA,
                 max_blob_area: int = MAX_BLOB_AREA,
                 conversion_format: str = "none", conversion_output_dir: Optional[Path] = None):
        self.input_dir = Path(input_dir)
        self.output_file = Path(output_file)
        self.extension_factor = extension_factor
        self.tail_taper_strength, self.tail_angle_threshold = validate_tail_settings(
            tail_taper_strength, tail_angle_threshold
        )
        self.use_rotation = use_rotation
        self.use_kalman = use_kalman
        self.kalman_process_noise = kalman_process_noise
        self.kalman_measurement_noise = kalman_measurement_noise
        self.blend_mode = blend_mode
        self.video_enabled = video_enabled
        self.video_fps = video_fps
        self.video_slowdown = max(1, min(8, int(video_slowdown)))
        self.image_resolution = normalize_resolution(image_resolution)
        self.video_resolution = normalize_resolution(video_resolution)
        self.quality = quality
        self.video_hyperlapse = video_hyperlapse
        self.use_foreground_mask = use_foreground_mask
        self.ghost_frames_per_real = ghost_frames_per_real
        self.synthetic_fade_factor = synthetic_fade_factor
        self.fill_gaps = fill_gaps
        self.save_frames = save_frames
        self.no_stack = no_stack
        from modules.export_images import FORMATS
        if image_format not in FORMATS:
            raise ValueError("Image format must be tiff, png, or jpg")
        if video_format not in {"auto", "mp4", "mov"}:
            raise ValueError("Video format must be auto, mp4, or mov")
        if quality not in {"high", "medium", "lossless", "prores", "hevc"}:
            raise ValueError("Unsupported video quality")
        if no_stack and (not save_frames or video_enabled):
            raise ValueError("Images-only export requires frames and cannot create a trail video")
        if video_enabled and quality == "prores" and video_format == "mp4":
            raise ValueError("ProRes requires MOV")
        self.image_format = image_format
        self.video_format = video_format
        self.export_results = {}
        if not no_stack:
            self.output_file = self.output_file.with_suffix(FORMATS[image_format])
        self.use_checkpoint = use_checkpoint
        self.resume = resume
        self.sort_by_time = sort_by_time
        self.progress_callback = progress_callback
        self.cancellation_token = cancellation_token
        self.compute_backend = compute_backend
        self.requested_cpu_workers = cpu_workers
        self.raw_noise_reduction = raw_noise_reduction
        self.raw_exposure_ev = raw_exposure_ev
        self.conversion_format = str(conversion_format or "none").lower()
        conversion_dir = str(conversion_output_dir).strip() if conversion_output_dir else ""
        self.conversion_output_dir = Path(conversion_dir).expanduser() if conversion_dir else None
        self.search_window_size = search_window_size
        self.max_jump_threshold = max_jump_threshold
        self.star_threshold_percentile = star_threshold_percentile
        self.min_blob_area = min_blob_area
        self.max_blob_area = max_blob_area
        if not 0 <= raw_exposure_ev <= 3:
            raise ValueError("RAW exposure boost must be between 0 and 3 EV")
        if self.conversion_format not in {"none", "jpg", "tiff"}:
            raise ValueError("Conversion format must be one of: none, jpg, tiff")
        self.cpu_workers = 1
        self.compute_info = {"backend": "cpu", "device": "CPU", "workers": 1}

        self.image_paths = []
        self.source_image_paths: List[Path] = []
        self.first_info = None
        self.field_analysis = None
        self._conversion_temp_dir: Optional[TemporaryDirectory] = None
        self._resolution_temp_dir: Optional[TemporaryDirectory] = None
        self.converted_files_dir: Optional[str] = None
        self.processing_scale = (1.0, 1.0)

    _CONVERSION_MANIFEST = ".staraligner-conversion.json"

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.cleanup()

    def cleanup(self) -> None:
        """Remove the per-run conversion directory, if one was temporary."""
        if self._conversion_temp_dir is not None:
            self._conversion_temp_dir.cleanup()
            self._conversion_temp_dir = None
        if self._resolution_temp_dir is not None:
            self._resolution_temp_dir.cleanup()
            self._resolution_temp_dir = None

    def video_dimensions(self, width: int, height: int) -> tuple[int, int]:
        """Return the encoded video size for a rendered stack crop."""
        return fit_dimensions(width, height, self.video_resolution)

    def _scale_point(self, point: Optional[Tuple[float, float]]) -> Optional[Tuple[float, float]]:
        if point is None:
            return None
        return (float(point[0]) * self.processing_scale[0],
                float(point[1]) * self.processing_scale[1])

    def _resize_inputs(self) -> None:
        """Downsample the working sequence once before tracking and stacking."""
        source_info = get_image_info(self.image_paths[0])
        target_width, target_height = fit_dimensions(
            source_info["width"], source_info["height"], self.image_resolution)
        self.processing_scale = (
            target_width / source_info["width"],
            target_height / source_info["height"],
        )
        if (target_width, target_height) == (source_info["width"], source_info["height"]):
            return

        self._resolution_temp_dir = TemporaryDirectory(
            prefix=".staraligner-resolution-", dir=self.input_dir)
        destination = Path(self._resolution_temp_dir.name)
        extension = ".tiff" if source_info["dtype"] == "uint16" else ".png"
        source_paths = list(self.image_paths)
        total = len(source_paths)

        def resize(item):
            index, source = item
            self.check_cancelled()
            image = load_image(
                source,
                for_export=True,
                raw_noise_reduction=self.raw_noise_reduction,
                raw_exposure_ev=self.raw_exposure_ev,
            )
            self.check_cancelled()
            resized = cv2.resize(image, (target_width, target_height),
                                 interpolation=cv2.INTER_AREA)
            path = destination / f"{index:05d}_{source.stem[:120]}{extension}"
            if not cv2.imwrite(str(path), resized):
                raise IOError(f"Failed to write resized frame: {path}")
            try:
                stat = source.stat()
                os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            except OSError:
                pass
            return path

        self.emit_progress({"stage": "preparation", "status": "resizing",
                            "progress": 0, "current": 0, "total": total,
                            "image_resolution": self.image_resolution})
        resized_paths = []
        try:
            with closing(ordered_map(resize, enumerate(source_paths),
                                     workers=self.cpu_workers,
                                     cancel_check=self.check_cancelled)) as frames:
                for path in frames:
                    resized_paths.append(path)
                    self.emit_progress({
                        "stage": "preparation", "status": "resizing",
                        "progress": len(resized_paths) / total if total else 1,
                        "current": len(resized_paths), "total": total,
                        "image_resolution": self.image_resolution,
                    })
        except BaseException:
            self._resolution_temp_dir.cleanup()
            self._resolution_temp_dir = None
            raise
        self.image_paths = resized_paths
        self.first_info = get_image_info(self.image_paths[0])
        self.cpu_workers = worker_count(
            self.first_info["width"], self.first_info["height"],
            self.first_info["is_raw"], self.requested_cpu_workers)
        self.compute_info["workers"] = self.cpu_workers

    def _exclude_conversion_artifacts(self, paths: List[Path]) -> List[Path]:
        """Ignore generated files from an earlier run saved in the source folder."""
        manifest = self.input_dir / self._CONVERSION_MANIFEST
        try:
            data = json.loads(manifest.read_text())
            generated = {
                Path(path).resolve()
                for path in data.get("generated_files", [])
                if isinstance(path, str)
            }
        except (OSError, ValueError, TypeError):
            return paths
        return [path for path in paths if path.resolve() not in generated]

    def _conversion_destination(self) -> Path:
        if self.conversion_output_dir is not None:
            destination = self.conversion_output_dir.resolve()
            if destination.exists() and not destination.is_dir():
                raise ValueError(f"Conversion output location is not a directory: {destination}")
            destination.mkdir(parents=True, exist_ok=True)
            # If the source folder itself was chosen, clear only files owned by
            # the previous conversion run before scanning the new sequence.
            if destination == self.input_dir.resolve():
                manifest = destination / self._CONVERSION_MANIFEST
                try:
                    data = json.loads(manifest.read_text())
                    for path in data.get("generated_files", []):
                        Path(path).unlink(missing_ok=True)
                    manifest.unlink(missing_ok=True)
                except (OSError, ValueError, TypeError):
                    pass
            return destination
        # Keep temporary files beside the source sequence so large RAW jobs do
        # not unexpectedly fill the system temp volume.
        self._conversion_temp_dir = TemporaryDirectory(prefix=".staraligner-converted-", dir=self.input_dir)
        return Path(self._conversion_temp_dir.name)

    def _convert_inputs(self, source_paths: List[Path]) -> List[Path]:
        destination = self._conversion_destination()
        extension = ".jpg" if self.conversion_format == "jpg" else ".tiff"
        converted: List[Path] = []
        total = len(source_paths)
        destination_paths = [destination / f"{index:05d}_{source.stem[:120]}{extension}"
                             for index, source in enumerate(source_paths)]

        def progress(current):
            self.emit_progress({"stage": "conversion", "status": "converting",
                                "progress": current / total if total else 1,
                                "current": current, "total": total,
                                "conversion_format": self.conversion_format})

        def convert(item):
            index, source = item
            # The index preserves the selected order and disambiguates stems.
            return convert_image_for_stacking(
                source, destination_paths[index],
                self.conversion_format, raw_noise_reduction=self.raw_noise_reduction,
                raw_exposure_ev=self.raw_exposure_ev, cancel_check=self.check_cancelled)

        try:
            progress(0)
            # Keep RAW decode/denoising concurrency within the existing memory
            # budget. Closing the iterator joins workers before deleting files.
            with closing(ordered_map(convert, enumerate(source_paths), workers=self.cpu_workers,
                                     cancel_check=self.check_cancelled)) as frames:
                for path in frames:
                    converted.append(path)
                    progress(len(converted))
            manifest = destination / self._CONVERSION_MANIFEST
            manifest.write_text(json.dumps({
                "version": 1,
                "format": self.conversion_format,
                "raw_exposure_ev": self.raw_exposure_ev,
                "raw_noise_reduction": self.raw_noise_reduction,
                "generated_files": [str(path.resolve()) for path in converted],
                "frames": [{"source": str(source.resolve()), "converted": path.name}
                           for source, path in zip(source_paths, converted)],
            }, indent=2) + "\n")
            self.check_cancelled()
            if self.conversion_output_dir is not None:
                self.converted_files_dir = str(destination)
                self.emit_progress({"stage": "conversion", "status": "converted", "progress": 1,
                                    "converted_files_dir": self.converted_files_dir})
            return converted
        except BaseException:
            # Only remove this run's owned directory, including a partially
            # written file from a worker which failed before returning a path.
            if self._conversion_temp_dir is not None:
                self.cleanup()
            else:
                for path in destination_paths:
                    path.unlink(missing_ok=True)
            raise

    def check_cancelled(self):
        if self.cancellation_token is not None:
            self.cancellation_token.check()

    def emit_progress(self, data: Dict[str, Any]):
        self.check_cancelled()
        if self.progress_callback:
            self.progress_callback(data)
        self.check_cancelled()

    def prepare(self) -> Dict[str, Any]:
        """Validate sources, then optionally develop a reusable frame sequence."""
        self.cleanup()
        self.converted_files_dir = None
        try:
            return self._prepare()
        except BaseException:
            self.cleanup()
            raise

    def _prepare(self) -> Dict[str, Any]:
        frames_target = self.output_file if self.no_stack else self.output_file.with_name(self.output_file.stem + "_frames")
        if self.save_frames and frames_target.exists():
            raise ValueError(f"Export folder already exists: {frames_target}. Choose a new output name to preserve existing files.")
        if self.video_enabled and (self.quality != "high" or self.video_format == "mov"):
            from video.ffmpeg_writer import is_ffmpeg_available
            if not is_ffmpeg_available():
                raise ValueError("FFmpeg is required for this video format. Install FFmpeg or choose MP4 with high quality.")
        self.emit_progress({"stage": "preparation", "status": "scanning"})
        self.image_paths = get_image_list(self.input_dir, sort_by_time=self.sort_by_time,
                                          cancel_check=self.check_cancelled)
        self.image_paths = self._exclude_conversion_artifacts(self.image_paths)

        # The default output lives inside the input directory, so a previous run's
        # result would otherwise be picked up as an input frame. Its dimensions
        # differ from the source frames, which corrupts the common crop and the
        # per-frame warps. Drop it (and any non-image sibling) from the scan.
        try:
            out_resolved = self.output_file.resolve()
            before = len(self.image_paths)
            self.image_paths = [
                p for p in self.image_paths
                if p.resolve() != out_resolved
                and not p.name.endswith(".live.jpg")
                and p.suffix.lower() not in (".mp4", ".mov", ".avi")
            ]
            if len(self.image_paths) != before:
                self.emit_progress({
                    "stage": "preparation",
                    "status": "scanning",
                    "skipped": before - len(self.image_paths)
                })
        except OSError:
            pass

        if not self.image_paths:
            raise ValueError(f"No valid images found in {self.input_dir}")

        self.source_image_paths = list(self.image_paths)

        self.emit_progress({"stage": "preparation", "status": "validating"})
        errors, warnings = validate_inputs(
            image_list=self.image_paths,
            extension_factor=self.extension_factor,
            min_images=3 if self.no_stack else 10,
            output_path=self.output_file,
            cancel_check=self.check_cancelled,
        )
        if errors:
            raise ValueError(f"Validation failed: {errors}")

        consistency_errors, consistency_warnings = validate_image_consistency(
            self.image_paths, check_timestamps=False, cancel_check=self.check_cancelled,
        )
        if consistency_errors:
            raise ValueError(" ".join(consistency_errors))
        warnings.extend(consistency_warnings)

        self.first_info = get_image_info(self.image_paths[0])
        configure_native_threads()
        self.cpu_workers = worker_count(self.first_info["width"], self.first_info["height"],
                                        self.first_info["is_raw"], self.requested_cpu_workers)
        self.compute_info["workers"] = self.cpu_workers
        self.emit_progress({"stage": "preparation", "status": "ready",
                            "progress": 1, "compute": dict(self.compute_info)})
        if self.conversion_format != "none":
            self.image_paths = self._convert_inputs(self.source_image_paths)
            self.first_info = get_image_info(self.image_paths[0])
        self._resize_inputs()
        return {
            "num_images": len(self.image_paths),
            "first_info": self.first_info,
            "warnings": warnings,
            "converted_files_dir": self.converted_files_dir,
            "image_resolution": self.image_resolution,
            "video_resolution": self.video_resolution,
        }

    def run_pass1(self, polaris: Optional[Tuple[float, float]] = None, second_star: Optional[Tuple[float, float]] = None) -> Tuple[List[TrackingResult], List[TransformData]]:
        """Track stars and calculate transforms."""
        self.emit_progress({"stage": "pass1", "status": "tracking", "progress": 0})

        def track_cb(current, total, drift_x=None, drift_y=None):
            data = {
                "stage": "pass1",
                "status": "tracking",
                "progress": current / total if total else 0,
                "current": current,
                "total": total
            }
            if drift_x is not None and drift_y is not None:
                data["drift_x"] = drift_x
                data["drift_y"] = drift_y
            self.emit_progress(data)

        self.field_analysis = None
        if polaris is None:
            from backend.engine.field_alignment import analyze_field
            self.field_analysis = analyze_field(self.image_paths, progress_callback=track_cb,
                                                cancel_check=self.check_cancelled, workers=self.cpu_workers,
                                                raw_noise_reduction=self.raw_noise_reduction)
            for transform in self.field_analysis.transforms:
                if transform.is_valid:
                    track_cb(len(self.image_paths), len(self.image_paths), transform.dx, transform.dy)
            self.emit_progress({
                "stage": "pass1", "status": "calculating_transforms", "progress": 1,
                "selection_mode": "star_field",
                "detected_stars": len(self.field_analysis.reference_stars),
                "skipped_frames": self.field_analysis.skipped_frames,
            })
            return self.field_analysis.frames, self.field_analysis.transforms

        from backend.engine.pipeline import pass1_analysis
        from modules.gui import StarSelection

        selection = StarSelection(polaris=self._scale_point(polaris),
                                  second_star=self._scale_point(second_star))

        tracking_results, transforms = pass1_analysis(
            self.image_paths,
            selection,
            use_rotation=self.use_rotation,
            use_kalman=self.use_kalman,
            kalman_process_noise=self.kalman_process_noise,
            kalman_measurement_noise=self.kalman_measurement_noise,
            search_window_size=self.search_window_size,
            max_jump_threshold=self.max_jump_threshold,
            star_threshold_percentile=self.star_threshold_percentile,
            min_blob_area=self.min_blob_area,
            max_blob_area=self.max_blob_area,
            progress_callback=track_cb,
            cancel_check=self.check_cancelled,
            workers=self.cpu_workers,
        )

        self.emit_progress({"stage": "pass1", "status": "calculating_transforms", "progress": 1.0})
        return tracking_results, transforms

    def calculate_crop(self, transforms):
        self.check_cancelled()
        if self.field_analysis is not None:
            from backend.engine.field_alignment import field_crop
            return field_crop(transforms, self.first_info['width'], self.first_info['height'])
        return calculate_common_crop(transforms, self.first_info['width'], self.first_info['height'])

    def _export_frames(self, transforms, crop, destination):
        from modules.export_images import FORMATS, save_export_image
        from modules.transform import apply_transform_and_crop
        destination.mkdir()
        exported = []
        for index, (source, transform) in enumerate(zip(self.image_paths, transforms)):
            self.check_cancelled()
            if not transform.is_valid and self.field_analysis is not None:
                continue
            image = load_image(source, for_export=True,
                               raw_noise_reduction=self.raw_noise_reduction,
                               raw_exposure_ev=self.raw_exposure_ev)
            aligned = apply_transform_and_crop(image, transform, crop)
            name = f"{index:05d}_{self.source_image_paths[index].stem[:120]}{FORMATS[self.image_format]}"
            save_export_image(aligned, destination / name, self.image_format, self.first_info["dtype"])
            exported.append(name)
            self.emit_progress({"stage": "pass2", "status": "exporting_frames",
                                "progress": (index + 1) / len(self.image_paths),
                                "current": index + 1, "total": len(self.image_paths)})
        if not exported:
            raise ValueError("No valid aligned frames to export")
        (destination / "sequence.json").write_text(json.dumps({
            "format": self.image_format, "files": exported,
            "source_files": [str(path) for path in self.source_image_paths],
            "sky_motion_preserved": True,
            "crop": {"width": crop.width, "height": crop.height},
            "skipped_frames": len(self.image_paths) - len(exported),
        }, indent=2))
        return exported

    def run_pass2(self, transforms: List[TransformData], crop, polaris: Optional[Tuple[float, float]] = None):
        """Stage exports beside their destination; publish only complete outputs."""
        try:
            self.check_cancelled()
            frames_target = self.output_file if self.no_stack else self.output_file.with_name(self.output_file.stem + "_frames")
            if self.save_frames and frames_target.exists():
                raise ValueError(f"Export folder already exists: {frames_target}. Choose a new output name to preserve existing files.")
            self.output_file.parent.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(prefix=".staraligner-", dir=self.output_file.parent) as folder:
                stage = Path(folder)
                self.render_output_file = stage / self.output_file.name
                if self.save_frames:
                    names = self._export_frames(transforms, crop, stage / "frames")
                    self.export_results.update(frames_dir=str(frames_target), frame_count=len(names),
                                               preview_path=str(frames_target / names[0]), no_stack=self.no_stack)
                if not self.no_stack:
                    # Frame exports above own this concern for both render paths.
                    original_save = self.save_frames
                    self.save_frames = False
                    try:
                        try:
                            self._render_pass2(transforms, crop, self._scale_point(polaris))
                        except AccelerationError as error:
                            self.check_cancelled()
                            if self.compute_backend == "cpu":
                                raise
                            self.compute_backend = "cpu"
                            self.resume = False
                            self.compute_info.update(backend="cpu", device="CPU", fallback_reason=str(error))
                            self._render_pass2(transforms, crop, self._scale_point(polaris))
                    finally:
                        self.save_frames = original_save
                    for video in stage.glob("*"):
                        if video.suffix in {".mp4", ".mov"}:
                            self.export_results["video_path"] = str(self.output_file.parent / video.name)
                    self.export_results["preview_path"] = str(self.output_file)
                self.check_cancelled()

                def publish():
                    if self.save_frames:
                        if frames_target.exists():
                            raise ValueError(f"Export folder already exists: {frames_target}")
                        (stage / "frames").rename(frames_target)
                    for path in stage.iterdir():
                        if path.is_file():
                            path.replace(self.output_file.parent / path.name)
                    if self.field_analysis is not None and self.use_checkpoint:
                        self.output_file.with_suffix(".field-checkpoint.npz").unlink(missing_ok=True)

                if self.cancellation_token is not None:
                    self.cancellation_token.commit(publish)
                else:
                    publish()
            result_path = str(frames_target if self.no_stack else self.output_file)
            self.emit_progress({"stage": "done", "status": "complete", "progress": 1,
                                "result_path": result_path, **self.export_results})
            return result_path
        finally:
            self.cleanup()

    def _render_pass2(self, transforms, crop, polaris=None):
        """Stack aligned images."""
        self.emit_progress({"stage": "pass2", "status": "stacking", "progress": 0})

        if self.field_analysis is not None:
            from backend.engine.field_alignment import stack_field
            return stack_field(self, self.field_analysis, crop)

        self.compute_info.update(backend="cpu", device="CPU")
        if self.compute_backend != "cpu":
            self.compute_info["fallback_reason"] = "Manual reference rendering uses CPU workers."
        self.emit_progress({"stage": "pass2", "status": "stacking", "progress": 0,
                            "compute": dict(self.compute_info)})

        from backend.engine.pipeline import pass2_stacking
        def stack_cb(current, total):
            data = {
                "stage": "pass2", "status": "processing_frame",
                "progress": current / total if total else 0,
                "current": current, "total": total
            }
            if live_preview_state["path"]:
                data["live_preview_path"] = live_preview_state["path"]
                data["live_preview_revision"] = live_preview_state["revision"]
            self.emit_progress(data)

        live_preview_state = {"path": None, "revision": 0}

        def live_preview_cb(path, revision):
            live_preview_state.update(path=path, revision=revision)

        video_encoder = None
        if self.video_enabled:
            from video.ffmpeg_writer import create_video_writer
            video_encoder = create_video_writer(
                self.render_output_file.with_suffix('.mp4'),
                *self.video_dimensions(crop.width, crop.height),
                self.video_fps, self.quality, container=self.video_format)

        try:
            pass2_stacking(
                image_paths=self.image_paths,
                transforms=transforms,
                crop=crop,
                output_path=self.render_output_file,
                sample_is_raw=self.first_info['is_raw'],
                sample_dtype=self.first_info['dtype'],
                video_encoder=video_encoder,
                extension_factor=self.extension_factor,
                video_slowdown=self.video_slowdown,
                tail_taper_strength=self.tail_taper_strength,
                tail_angle_threshold=self.tail_angle_threshold,
                reference_polaris=polaris,
                use_foreground_mask=self.use_foreground_mask,
                video_hyperlapse=self.video_hyperlapse,
                blend_mode=self.blend_mode,
                checkpoint_dir=CHECKPOINT_DIR,
                use_checkpoint=self.use_checkpoint,
                resume=self.resume,
                ghost_frames_per_real=self.ghost_frames_per_real,
                synthetic_fade_factor=self.synthetic_fade_factor,
                fill_gaps=self.fill_gaps,
                progress_callback=stack_cb,
                cancel_check=self.check_cancelled,
                workers=self.cpu_workers,
                raw_noise_reduction=self.raw_noise_reduction,
                raw_exposure_ev=self.raw_exposure_ev,
                live_preview_path=self.output_file.with_suffix(".live.jpg"),
                live_preview_callback=live_preview_cb,
                conversion_format=self.conversion_format,
                image_format=self.image_format,
            )
        finally:
            if video_encoder:
                try:
                    self.emit_progress({"stage": "video_render", "status": "finalizing_video", "progress": 0})
                    video_encoder.close(cancel_check=self.check_cancelled)
                except BaseException:
                    video_encoder.abort()
                    raise

        return str(self.render_output_file)
