import os
import hashlib
import threading
from collections import OrderedDict
from typing import Annotated
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

router = APIRouter(prefix="/api/images", tags=["images"])

_PREVIEW_CACHE_MAX = 32
_preview_cache = OrderedDict()
_preview_cache_lock = threading.Lock()

class DirectoryRequest(BaseModel):
    path: str
    sort_by_time: bool = True

@router.post("/list")
def list_images(req: DirectoryRequest):
    if not os.path.exists(req.path):
        raise HTTPException(status_code=400, detail="Directory not found")

    from pathlib import Path
    from modules.io_utils import get_image_list
    try:
        files = get_image_list(Path(req.path), sort_by_time=req.sort_by_time)
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"files": [str(file) for file in files if not file.name.endswith(".live.jpg")]}

def validated_image_path(path: str) -> str:
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found")
    abs_path = os.path.abspath(path)
    ext = os.path.splitext(abs_path)[1].lower()
    if ext not in [".jpg", ".jpeg", ".png", ".tif", ".tiff", ".nef", ".cr2", ".cr3", ".arw", ".dng"]:
        raise HTTPException(status_code=403, detail="Invalid file type")
    return abs_path


@router.get("/preview")
def preview_image(path: str, max_size: Annotated[int | None, Query(ge=64, le=4096)] = None,
                  request: Request = None):
    abs_path = validated_image_path(path)
    stat = os.stat(abs_path)
    etag = '"' + hashlib.sha1(f"{abs_path}:{stat.st_mtime_ns}:{stat.st_size}:{max_size}".encode()).hexdigest() + '"'
    if request is not None and request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "public, max-age=3600"})
    if max_size is None and os.path.splitext(abs_path)[1].lower() in [".jpg", ".jpeg", ".png"]:
        return FileResponse(abs_path, headers={"ETag": etag, "Cache-Control": "public, max-age=3600"})

    # Browsers cannot display TIFF or camera RAW directly. Convert only the
    # display preview; the original scientific output stays unchanged.
    import cv2
    import numpy as np
    from pathlib import Path
    from modules.io_utils import is_raw_file, load_image
    from modules.image_preview import load_raw_preview
    key = (abs_path, stat.st_mtime_ns, stat.st_size, max_size)
    with _preview_cache_lock:
        cached = _preview_cache.get(key)
        if cached is not None:
            _preview_cache.move_to_end(key)
    if cached is not None:
        return Response(content=cached, media_type="image/jpeg",
                        headers={"ETag": etag, "Cache-Control": "public, max-age=3600"})
    try:
        if is_raw_file(Path(abs_path)):
            image = load_raw_preview(Path(abs_path), max_size=max_size)
        else:
            image = load_image(abs_path, for_export=True)
        if image.dtype == np.uint16:
            image = (image / 257).clip(0, 255).astype(np.uint8)
        elif image.dtype != np.uint8:
            image = image.clip(0, 255).astype(np.uint8)
        if max_size is not None and max(image.shape[:2]) > max_size:
            ratio = max_size / max(image.shape[:2])
            image = cv2.resize(image, (max(1, round(image.shape[1] * ratio)),
                                       max(1, round(image.shape[0] * ratio))),
                               interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 95])
        if not ok:
            raise ValueError("Preview encoding failed")
        content = encoded.tobytes()
        with _preview_cache_lock:
            _preview_cache[key] = content
            _preview_cache.move_to_end(key)
            while len(_preview_cache) > _PREVIEW_CACHE_MAX:
                _preview_cache.popitem(last=False)
        return Response(content=content, media_type="image/jpeg",
                        headers={"ETag": etag, "Cache-Control": "public, max-age=3600"})
    except Exception as error:
        raise HTTPException(status_code=422, detail="Unable to decode image preview") from error


@router.get("/download")
def download_image(path: str):
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found")
    if os.path.splitext(path)[1].lower() not in {".mp4", ".mov"}:
        validated_image_path(path)
    return FileResponse(os.path.abspath(path), filename=os.path.basename(path), media_type="application/octet-stream")


@router.get("/download-sequence")
def download_sequence(path: str):
    import json
    import tempfile
    import zipfile
    from pathlib import Path
    from starlette.background import BackgroundTask
    folder = Path(path)
    try:
        manifest = json.loads((folder / "sequence.json").read_text())
        names = manifest["files"]
        if not names or any(Path(name).name != name or not (folder / name).is_file() for name in names):
            raise ValueError("Invalid sequence")
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(status_code=404, detail="Exported sequence not found")
    archive = tempfile.NamedTemporaryFile(suffix=".zip", delete=False, dir=folder.parent)
    archive.close()
    try:
        # Image formats are already compressed; avoid a second compression pass.
        with zipfile.ZipFile(archive.name, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as output:
            for name in names + ["sequence.json"]:
                output.write(folder / name, arcname=name)
        return FileResponse(archive.name, filename=folder.name + ".zip", media_type="application/zip",
                            background=BackgroundTask(os.unlink, archive.name))
    except BaseException:
        os.unlink(archive.name)
        raise

@router.post("/metadata")
def get_metadata(req: DirectoryRequest):
    if not os.path.exists(req.path):
        raise HTTPException(status_code=400, detail="Directory not found")

    from modules.io_utils import get_image_list, get_exif_datetime, get_image_info
    from pathlib import Path
    import statistics

    try:
        image_paths = get_image_list(Path(req.path), sort_by_time=True)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    def read_metadata(p):
        try:
            info = get_image_info(p)
            dt = get_exif_datetime(p)
            return p, info, dt, os.path.getsize(p)
        except Exception:
            return p, None, None, 0

    metadata_list = []
    timestamps = []
    from core.parallel import ordered_map
    workers = min(4, len(image_paths))
    for p, info, dt, size in ordered_map(read_metadata, image_paths, workers=workers):
        if info is None:
            continue
        meta = {"file_name": p.name, "size": size,
                "width": info.get("width"), "height": info.get("height"),
                "timestamp": dt.isoformat() if dt else None, "gap_detected": False}
        metadata_list.append(meta)
        if dt:
            timestamps.append((len(metadata_list) - 1, dt))

    # Detect gaps
    if len(timestamps) > 1:
        deltas = []
        for i in range(1, len(timestamps)):
            dt1 = timestamps[i-1][1]
            dt2 = timestamps[i][1]
            deltas.append((dt2 - dt1).total_seconds())

        median_delta = statistics.median(deltas) if deltas else 0
        if median_delta > 0:
            threshold = 1.5 * median_delta
            for i in range(1, len(timestamps)):
                if deltas[i-1] > threshold:
                    idx = timestamps[i][0]
                    metadata_list[idx]["gap_detected"] = True

    return {"metadata": metadata_list}
