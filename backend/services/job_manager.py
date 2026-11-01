import asyncio
import uuid
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Any, Callable, List
from backend.engine.alignment_engine import AlignmentEngine
from core.cancellation import CancellationToken, OperationCancelled
from core.compute import worker_count, configure_native_threads

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

class JobManager:
    def __init__(self):
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self.listeners: Dict[str, List[Callable]] = {}
        self.tokens: Dict[str, CancellationToken] = {}
        self.workers: Dict[str, threading.Thread] = {}
        self._lock = threading.RLock()

    def create_job(self, config: Dict[str, Any], kind: str = "alignment") -> str:
        job_id = str(uuid.uuid4())
        self.jobs[job_id] = {
            "id": job_id,
            "kind": kind,
            "config": config,
            "status": "created",
            "progress": 0,
            "overall_progress": 0,
            "stage": "pending",
            "result_path": None,
            "error": None
        }
        self.listeners[job_id] = []
        self.tokens[job_id] = CancellationToken()
        return job_id

    def get_job(self, job_id):
        with self._lock:
            return dict(self.jobs[job_id])

    def subscribe(self, job_id: str, callback: Callable):
        if job_id not in self.listeners:
            self.listeners[job_id] = []
        self.listeners[job_id].append(callback)

    def _emit(self, job_id: str, data: Dict[str, Any]):
        with self._lock:
            self._update(job_id, data)

    def _update(self, job_id: str, data: Dict[str, Any]):
        if job_id not in self.jobs:
            return
        job = self.jobs[job_id]
        if job["status"] in TERMINAL_STATUSES:
            return
        data = dict(data)
        if data.get("stage", job["stage"]) != job["stage"]:
            data.setdefault("current", 0)
            data.setdefault("total", 0)
        if job["status"] == "cancelling" and data.get("status") == "running":
            return
        # Stage weights describe completed work, not an estimated remaining time.
        stacking_end = 0.95 if job['config'].get('video_enabled') else 0.99
        ranges = {
            'preparation': (0, 0.05), 'pass1': (0.05, 0.35),
            'crop_calc': (0.35, 0.4), 'pass2': (0.4, stacking_end),
            'video_render': (0.95, 0.99), 'done': (0.99, 0.99),
        }
        if job['config'].get('conversion_format', 'none') != 'none':
            ranges.update(conversion=(0.05, 0.20), pass1=(0.20, 0.35))
        if data.get('status') == 'completed':
            data['overall_progress'] = 1.0
        elif data.get('stage') in ranges:
            start, end = ranges[data['stage']]
            fraction = min(1, max(0, data.get('progress', 0)))
            data['overall_progress'] = max(job.get('overall_progress', 0), start + (end - start) * fraction)
        job.update(data)
        snapshot = dict(job)

        # Safely run callbacks
        for cb in self.listeners.get(job_id, []):
            try:
                if asyncio.iscoroutinefunction(cb):
                    # We are running in a background thread here!
                    # The callback was registered in the main event loop thread (FastAPI).
                    # We must schedule it to run on the main loop.
                    # Since we don't have direct access to the main loop here easily,
                    # we can use a small hack or simply define the callback to use asyncio.run_coroutine_threadsafe.
                    # Actually, the callback itself handles that now (see router.py changes).
                    cb(snapshot)
                else:
                    cb(snapshot)
            except Exception as e:
                import traceback
                traceback.print_exc()

    def start_job(self, job_id: str):
        with self._lock:
            if self.jobs[job_id]["status"] != "created":
                return
            self._emit(job_id, {"status": "running"})
            thread = threading.Thread(target=self._run_job, args=(job_id,), daemon=True)
            self.workers[job_id] = thread
            thread.start()

    def cancel_job(self, job_id):
        with self._lock:
            job = self.jobs[job_id]
            if job["status"] not in TERMINAL_STATUSES and self.tokens[job_id].cancel():
                self._emit(job_id, {
                    "status": "cancelled" if job["status"] == "created" else "cancelling",
                    "result_path": None, "error": None,
                })
            return dict(job)

    def _complete(self, job_id, data):
        with self._lock:
            self.tokens[job_id].commit(lambda: self._emit(job_id, {
                **data, "status": "completed",
            }))

    def _run_detection(self, job_id, config, token):
        from modules.io_utils import get_image_list, get_image_info
        from modules.auto_selector import auto_detect_stars

        token.check()
        paths = get_image_list(Path(config["path"]),
                               sort_by_time=config.get("sort_by_time", True),
                               cancel_check=token.check)
        info = get_image_info(paths[0])
        configure_native_threads()
        workers = worker_count(info["width"], info["height"], info["is_raw"], config.get("cpu_workers"))
        self._emit(job_id, {"status": "running", "compute": {
            "backend": "cpu", "device": "CPU", "workers": workers,
        }})
        result = auto_detect_stars(paths, frame_step=config.get("frame_step", 10),
                                   cancel_check=token.check, workers=workers,
                                   raw_noise_reduction=config.get("raw_noise_reduction", True))
        token.check()
        if result is None:
            raise ValueError("Could not match at least six stars across exposures. "
                             "Check focus, clouds, and sequence overlap.")
        self._complete(job_id, {"result": {**asdict(result), "reference_image": str(paths[0])},
                                "progress": 1})

    def _run_job(self, job_id: str):
        job = self.jobs[job_id]
        config = job["config"]
        token = self.tokens[job_id]

        def progress_cb(data: Dict[str, Any]):
            self._emit(job_id, {**data, "activity": data.get("status"), "status": "running"})

        try:
            token.check()
            self._emit(job_id, {"status": "running", "stage": "preparation", "progress": 0})
            if job["kind"] == "detection":
                self._run_detection(job_id, config, token)
                return
            engine = AlignmentEngine(
                input_dir=config["input_dir"],
                output_file=config["output_file"],
                extension_factor=config.get("extension_factor", 1.0),
                tail_taper_strength=config.get("tail_taper_strength", 0.0),
                tail_angle_threshold=config.get("tail_angle_threshold", 0.0),
                use_rotation=config.get("use_rotation", False),
                use_kalman=config.get("use_kalman", True),
                kalman_process_noise=config.get("kalman_process_noise", 0.01),
                kalman_measurement_noise=config.get("kalman_measurement_noise", 2.0),
                blend_mode=config.get("blend_mode", "lighten"),
                video_enabled=config.get("video_enabled", False),
                video_fps=config.get("video_fps", 30),
                video_slowdown=config.get("video_slowdown", 1),
                image_resolution=config.get("image_resolution", "source"),
                video_resolution=config.get("video_resolution", "source"),
                quality=config.get("quality", "high"),
                video_hyperlapse=config.get("video_hyperlapse", False),
                use_foreground_mask=config.get("use_foreground_mask", True),
                ghost_frames_per_real=config.get("ghost_frames_per_real", 10),
                synthetic_fade_factor=config.get("synthetic_fade_factor", 0.2),
                fill_gaps=config.get("fill_gaps", False),
                image_format=config.get("image_format", "tiff"),
                video_format=config.get("video_format", "auto"),
                save_frames=config.get("save_frames", False),
                no_stack=config.get("no_stack", False),
                use_checkpoint=config.get("use_checkpoint", True),
                resume=config.get("resume", False),
                sort_by_time=config.get("sort_by_time", True),
                progress_callback=progress_cb,
                cancellation_token=token,
                compute_backend=config.get("compute_backend", "auto"),
                cpu_workers=config.get("cpu_workers"),
                raw_noise_reduction=config.get("raw_noise_reduction", True),
                raw_exposure_ev=config.get("raw_exposure_ev", 0.0),
                conversion_format=config.get("conversion_format", "none"),
                conversion_output_dir=config.get("conversion_output_dir"),
            )

            with engine:
                info = engine.prepare()
                polaris = config.get("polaris")

                second_star = config.get("second_star")

                tracking_results, transforms = engine.run_pass1(polaris, second_star)

                self._emit(job_id, {"stage": "crop_calc", "progress": 0})
                crop = engine.calculate_crop(transforms)
                self._emit(job_id, {"stage": "crop_calc", "progress": 1})

                result_path = engine.run_pass2(transforms, crop, polaris)

            self._complete(job_id, {
                "result_path": result_path,
                **engine.export_results,
                "conversion_format": config.get("conversion_format", "none"),
                "converted_files_dir": info.get("converted_files_dir"),
            })

        except OperationCancelled:
            self._emit(job_id, {"status": "cancelled", "result_path": None, "error": None})
        except Exception as e:
            if token.cancelled:
                self._emit(job_id, {"status": "cancelled", "result_path": None, "error": None})
            else:
                import traceback
                traceback.print_exc()
                self._emit(job_id, {"status": "failed", "error": str(e)})
        finally:
            with self._lock:
                self.workers.pop(job_id, None)

job_manager = JobManager()
