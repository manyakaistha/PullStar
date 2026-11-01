"""Validate full views and thumbnails of every DNG in a supplied collection.

Run with the dev dependencies installed. Reports and sample previews are
written outside the source collection; source bytes are verified by SHA-256.
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import rawpy
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.main import app
from modules.io_utils import get_image_info


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def decode(response):
    if response.status_code != 200:
        raise ValueError(f"HTTP {response.status_code}: {response.text[:200]}")
    if response.headers.get("content-type") != "image/jpeg":
        raise ValueError("Expected a browser-readable JPEG")
    image = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.dtype != np.uint8 or image.max() == image.min():
        raise ValueError("Preview has no readable image content")
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    source = args.data_dir.expanduser().resolve()
    output = args.output_dir.expanduser().resolve()
    if not source.is_dir():
        parser.error("Data directory does not exist")
    if output.is_relative_to(source):
        parser.error("Write validation output outside the source collection")
    files = sorted(p for p in source.rglob("*") if p.is_file() and p.suffix.lower() == ".dng")
    if not files:
        parser.error("No DNG files found")
    output.mkdir(parents=True, exist_ok=True)
    results = []
    saved_folders = set()
    started = time.perf_counter()
    with TestClient(app) as client:
        for index, path in enumerate(files, 1):
            result = {"file": str(path.relative_to(source))}
            try:
                before = digest(path)
                result["source_bytes"] = path.stat().st_size
                if result["source_bytes"] == 0:
                    response = client.get("/api/images/preview", params={"path": str(path)})
                    if response.status_code != 422 or digest(path) != before:
                        raise ValueError("Empty source was not rejected without modification")
                    result.update(status="rejected_empty", source_sha256=before)
                    results.append(result)
                    print(f"[{index}/{len(files)}] rejected empty source: {path.name}", flush=True)
                    continue
                info = get_image_info(path)
                tick = time.perf_counter()
                response = client.get("/api/images/preview", params={"path": str(path)})
                full_seconds = time.perf_counter() - tick
                image = decode(response)
                expected = (info["height"], info["width"])
                if image.shape[:2] != expected:
                    raise ValueError(f"Full view {image.shape[:2]} differs from {expected}")
                tick = time.perf_counter()
                small_response = client.get("/api/images/preview", params={
                    "path": str(path), "max_size": 256,
                })
                thumbnail_seconds = time.perf_counter() - tick
                small = decode(small_response)
                if max(small.shape[:2]) > 256:
                    raise ValueError("Filmstrip preview exceeds 256 pixels")
                if digest(path) != before:
                    raise ValueError("Source bytes changed")
                result.update(status="passed", width=image.shape[1], height=image.shape[0],
                              preview_bytes=len(response.content),
                              thumbnail_bytes=len(small_response.content),
                              full_seconds=round(full_seconds, 4),
                              thumbnail_seconds=round(thumbnail_seconds, 4),
                              source_sha256=before)
                if path.parent not in saved_folders:
                    sample = output / path.parent.name
                    sample.mkdir(exist_ok=True)
                    (sample / f"{path.stem}.jpg").write_bytes(response.content)
                    saved_folders.add(path.parent)
            except Exception as error:
                result.update(status="failed", error=f"{type(error).__name__}: {error}")
            results.append(result)
            detail = f" ({result['error']})" if "error" in result else ""
            print(f"[{index}/{len(files)}] {result['status']}: {path.name}{detail}", flush=True)
    passed = sum(item["status"] == "passed" for item in results)
    empty = sum(item["status"] == "rejected_empty" for item in results)
    failed = len(results) - passed - empty
    report = {"data_dir": str(source), "rawpy_version": rawpy.__version__,
              "libraw_version": rawpy.libraw_version, "total": len(results),
              "passed": passed, "rejected_empty": empty, "failed": failed,
              "seconds": round(time.perf_counter() - started, 3), "files": results}
    report_path = output / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"{passed} previews passed, {empty} empty files rejected, {failed} failures; report: {report_path}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
