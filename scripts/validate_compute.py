"""Benchmark bounded CPU extraction and compare CPU/GPU trails on real photos."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.engine.alignment_engine import AlignmentEngine
from backend.engine.field_alignment import iter_field_sources
from core.compute import system_capabilities
from scripts.validate_dim_detection import jpeg_bursts


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=12)
    args = parser.parse_args()
    source = args.data_dir.resolve()
    target = args.output_dir.resolve()
    if not source.is_dir() or target.is_relative_to(source) or args.samples < 10:
        parser.error("Use at least ten samples and write output outside a valid source directory")
    target.mkdir(parents=True, exist_ok=True)
    report = {"hardware": system_capabilities(), "series": []}
    for folder in sorted(p for p in source.iterdir() if p.is_dir()):
        bursts = jpeg_bursts(folder)
        if not bursts or len(bursts[0]) < 10:
            continue
        paths = bursts[0][:args.samples]
        result = {"dataset": folder.name, "files": [p.name for p in paths]}
        report["series"].append(result)
        output = target / folder.name
        inputs = output / "inputs"
        inputs.mkdir(parents=True, exist_ok=True)
        for path in paths:
            link = inputs / path.name
            if not link.exists():
                link.symlink_to(path)
        before = [digest(path) for path in paths]
        try:
            engine = AlignmentEngine(inputs, output / "cpu.tiff", compute_backend="cpu",
                                      sort_by_time=False, use_checkpoint=False,
                                      extension_factor=1.5, ghost_frames_per_real=2,
                                      use_foreground_mask=False)
            engine.prepare()
            result["workers"] = engine.cpu_workers
            result["width"], result["height"] = engine.first_info["width"], engine.first_info["height"]
            # Read through both paths once before comparing; filesystem/cache
            # effects are included, so these are local timings, not guarantees.
            for name, workers in (("serial", 1), ("parallel", engine.cpu_workers)):
                tick = time.perf_counter()
                fields = list(iter_field_sources(engine.image_paths, workers=workers))
                result[f"{name}_detection_seconds"] = round(time.perf_counter() - tick, 3)
                if name == "serial":
                    reference_fields = fields
                else:
                    for (shape, points), (old_shape, old_points) in zip(fields, reference_fields):
                        if shape != old_shape or not np.array_equal(points, old_points):
                            raise ValueError("Parallel extraction changed the detected star coordinates")
                print(json.dumps({"dataset": folder.name, "phase": name,
                                   "seconds": result[f"{name}_detection_seconds"]}), flush=True)
            result["parallel_coordinates_identical"] = True
            _, transforms = engine.run_pass1()
            result["accepted_frames"] = sum(frame.is_valid for frame in engine.field_analysis.frames)
            crop = engine.calculate_crop(transforms)
            for name in ("cpu", "opencl"):
                engine.compute_backend = name
                engine.output_file = output / f"{name}.tiff"
                tick = time.perf_counter()
                path = engine.run_pass2(transforms, crop)
                result[f"{name}_render_seconds"] = round(time.perf_counter() - tick, 3)
                result[f"{name}_compute"] = dict(engine.compute_info)
                image = cv2.imread(path, cv2.IMREAD_UNCHANGED)
                if image is None or image.max() == image.min():
                    raise ValueError("Render is missing or empty")
                if name == "cpu":
                    cpu_image = image
                else:
                    difference = np.abs(image.astype(np.int32) - cpu_image.astype(np.int32))
                    result["maximum_pixel_difference"] = int(difference.max())
                    result["mean_pixel_difference"] = round(float(difference.mean()), 8)
                    if difference.max() > 1:
                        raise ValueError("GPU/CPU export differs by more than one brightness level")
                    scale = min(1, 1200 / max(image.shape[:2]))
                    cv2.imwrite(str(output / "preview.jpg"), cv2.resize(image, None, fx=scale, fy=scale))
                print(json.dumps({"dataset": folder.name, "phase": name,
                                   "seconds": result[f"{name}_render_seconds"],
                                   "compute": result[f"{name}_compute"]}), flush=True)
            if [digest(path) for path in paths] != before:
                raise ValueError("Source photographs changed")
            result["source_sha256"] = before
            result["status"] = "passed"
        except Exception as error:
            result.update(status="failed", error=f"{type(error).__name__}: {error}")
        (target / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"dataset": folder.name, "status": result["status"],
                           "error": result.get("error")}), flush=True)
    return 0 if report["series"] and all(r["status"] == "passed" for r in report["series"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
