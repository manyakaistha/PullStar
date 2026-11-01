"""Create verified RAW trails, keeping outputs and a source hash manifest separate.

Example:
    uv run python scripts/validate_noisy_raw.py --input-dir '/photos/dng images' \
        --output-dir '/photos/results' --raw-exposure 2
"""

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


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--raw-exposure", type=float, default=2)
    parser.add_argument("--fill-gaps", action="store_true")
    parser.add_argument("--cpu-only", action="store_true")
    parser.add_argument("--no-recovery", action="store_true")
    args = parser.parse_args()
    source, output = args.input_dir.resolve(), args.output_dir.resolve()
    if not source.is_dir() or output.is_relative_to(source):
        parser.error("Choose an existing input folder and an output outside it")
    if not 0 <= args.raw_exposure <= 3:
        parser.error("--raw-exposure must be between 0 and 3 EV")
    output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    report = {"input_dir": str(source), "raw_exposure_ev": args.raw_exposure,
              "raw_noise_reduction": not args.no_recovery, "fill_gaps": args.fill_gaps}

    def progress(event):
        current = event.get("current")
        if current is not None and (current % 20 == 0 or current == event.get("total")):
            print(event["stage"], current, "/", event.get("total"), flush=True)

    try:
        engine = AlignmentEngine(
            source, output / "star-trails.tiff", raw_noise_reduction=not args.no_recovery,
            raw_exposure_ev=args.raw_exposure, fill_gaps=args.fill_gaps,
            compute_backend="cpu" if args.cpu_only else "auto", use_checkpoint=False,
            # This recipe is for sky-only sequences; no ground is synthesized.
            use_foreground_mask=False, progress_callback=progress)
        prepared = engine.prepare()
        hashes = {p.name: digest(p) for p in engine.image_paths}
        report["source_sha256"] = hashes
        report["num_images"] = prepared["num_images"]
        _, transforms = engine.run_pass1()
        report["accepted_frames"] = sum(t.is_valid for t in transforms)
        report["skipped_frames"] = engine.field_analysis.skipped_frames
        report["matched_stars"] = [f.num_matches for f in engine.field_analysis.frames]
        crop = engine.calculate_crop(transforms)
        result = engine.run_pass2(transforms, crop)
        image = cv2.imread(result, cv2.IMREAD_UNCHANGED)
        if image is None or image.dtype != np.uint16 or image.max() == 0:
            raise ValueError("RAW export is missing, empty, or not 16-bit")
        report.update(output=result, shape=list(image.shape), dtype=str(image.dtype),
                      compute=engine.compute_info)
        report["sources_unchanged"] = all(digest(p) == hashes[p.name] for p in engine.image_paths)
        if not report["sources_unchanged"]:
            raise ValueError("Source hash verification failed")
        jpeg = np.clip(image / 257, 0, 255).astype(np.uint8)
        cv2.imwrite(str(output / "star-trails.jpg"), jpeg, [cv2.IMWRITE_JPEG_QUALITY, 96])
        ratio = min(1.0, 1800 / image.shape[1])
        cv2.imwrite(str(output / "preview.jpg"), cv2.resize(jpeg, None, fx=ratio, fy=ratio))
        report["status"] = "passed"
    except Exception as error:
        report.update(status="failed", error=f"{type(error).__name__}: {error}")
    report["seconds"] = round(time.perf_counter() - started, 3)
    destination = output / "report.json"
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print("REPORT:", destination, report["status"], flush=True)
    if report["status"] != "passed":
        print(report["error"], file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
