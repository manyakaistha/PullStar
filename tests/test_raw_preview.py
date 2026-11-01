"""Exercise real LibRaw decoding and embedded-JPEG extraction with tiny DNGs."""

from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
import pytest
import rawpy
import tifffile
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from backend.api.images_router import router
from backend.api.router import stars_router
from modules.io_utils import get_image_info


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client


def write_dng(path: Path, *, orientation=6, embedded=False, jpeg_orientation=True,
              small_preview=False):
    """Create a CFA DNG, or an undecodable RAW strip with a real JPEG SubIFD.

    The second variant deliberately marks its RAW strip as JPEG-XL without
    encoding it: viewing must succeed solely from the valid embedded JPEG.
    This keeps the regression fixture independent of a JPEG-XL codec.
    """
    rgb = np.full((96, 128, 3), 40, dtype=np.uint8)
    rgb[8:32, 8:32] = (245, 20, 20)
    rgb[64:88, 96:120] = (20, 245, 20)
    tags = [
        (271, "s", 0, "Test", False),
        (272, "s", 0, "Preview camera", False),
        (274, "H", 1, orientation, False),
        (50706, "B", 4, (1, 4, 0, 0), False),
        (50707, "B", 4, (1, 1, 0, 0), False),
        (50708, "s", 0, "Preview camera", False),
        (50714, "H", 1, 0 if embedded else 64, False),
        (50717, "I", 1, 65535 if embedded else 1023, False),
        (50721, "2i", 9, (1, 1, 0, 1, 0, 1, 0, 1, 1, 1,
                              0, 1, 0, 1, 0, 1, 1, 1), False),
        (50728, "2I", 3, (1, 1, 1, 1, 1, 1), False),
        (50778, "H", 1, 21, False),
    ]
    if not embedded:
        sensor_rgb = rgb.astype(np.uint16) * 3 + 64
        sensor = np.empty(rgb.shape[:2], dtype=np.uint16)
        for y, x, channel in ((0, 0, 0), (0, 1, 1), (1, 0, 1), (1, 1, 2)):
            sensor[y::2, x::2] = sensor_rgb[y::2, x::2, channel]
        tags += [(33421, "H", 2, (2, 2), False),
                 (33422, "B", 4, (0, 1, 1, 2), False)]
        tifffile.imwrite(path, sensor, photometric=32803, metadata=None, extratags=tags)
        return

    preview = Image.fromarray(rgb)
    if small_preview:
        preview = preview.resize((64, 48))
    exif = Image.Exif()
    if jpeg_orientation:
        exif[274] = orientation
    buffer = BytesIO()
    preview.save(buffer, format="JPEG", quality=95, exif=exif)
    jpeg = buffer.getvalue()
    with tifffile.TiffWriter(path) as writer:
        writer.write(rgb.astype(np.uint16) * 257, photometric=34892,
                     metadata=None, extratags=tags, subifds=1)
        writer.write(np.asarray(preview), photometric="rgb", subfiletype=1,
                     metadata=None)
    offset = path.stat().st_size
    with path.open("ab") as file:
        file.write(jpeg)
    with tifffile.TiffFile(path, mode="r+") as tiff:
        tiff.pages[0].tags[259].overwrite(52546)
        page = tiff.pages[0].pages[0]
        page.tags[259].overwrite(7)
        page.tags[273].overwrite(offset)
        page.tags[279].overwrite(len(jpeg))


def decode_response(response):
    assert response.status_code == 200, response.text[:200] if response.is_error else ""
    assert response.headers["content-type"] == "image/jpeg"
    image = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return image


@pytest.mark.parametrize("orientation,shape", [(3, (96, 128, 3)), (6, (128, 96, 3))])
def test_cfa_dng_without_embedded_preview(client, tmp_path, orientation, shape):
    path = tmp_path / "sensor.DNG"
    write_dng(path, orientation=orientation)
    original = path.read_bytes()
    image = decode_response(client.get("/api/images/preview", params={"path": str(path)}))
    assert image.shape == shape
    assert image.dtype == np.uint8
    assert image.std() > 10
    info = get_image_info(path)
    assert (info["height"], info["width"]) == shape[:2]
    assert path.read_bytes() == original
    download = client.get("/api/images/download", params={"path": str(path)})
    assert download.status_code == 200
    assert download.content == original
    assert "attachment" in download.headers["content-disposition"]


@pytest.mark.parametrize("orientation", [3, 6, 8])
@pytest.mark.parametrize("jpeg_orientation", [True, False])
def test_embedded_jpeg_opens_without_raw_codec_and_rotates_once(
    client, tmp_path, orientation, jpeg_orientation,
):
    path = tmp_path / "linear.dng"
    write_dng(path, embedded=True, orientation=orientation, jpeg_orientation=jpeg_orientation)
    original = path.read_bytes()
    with rawpy.imread(str(path)) as raw:
        thumb = raw.extract_thumb()
        unrotated = cv2.imdecode(np.frombuffer(thumb.data, np.uint8),
                                cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
    with rawpy.imread(str(path)) as raw:
        with pytest.raises(rawpy.LibRawError):
            raw.postprocess()
    turns = {3: 2, 6: -1, 8: 1}[orientation]
    expected = np.rot90(unrotated, turns)
    image = decode_response(client.get("/api/images/preview", params={"path": str(path)}))
    assert image.shape == expected.shape
    assert np.abs(image.astype(float) - expected).mean() < 3
    assert path.read_bytes() == original


@pytest.mark.parametrize("embedded", [True, False])
def test_bounded_filmstrip_preview_keeps_full_view_coordinates(client, tmp_path, embedded):
    path = tmp_path / "frame.dng"
    write_dng(path, embedded=embedded)
    thumbnail = decode_response(client.get("/api/images/preview", params={
        "path": str(path), "max_size": 64,
    }))
    assert thumbnail.shape == (64, 48, 3)
    full = decode_response(client.get("/api/images/preview", params={"path": str(path)}))
    assert full.shape == (128, 96, 3)
    invalid = client.get("/api/images/preview", params={"path": str(path), "max_size": 0})
    assert invalid.status_code == 422


def test_small_embedded_fallback_uses_original_pixel_coordinates(client, tmp_path):
    path = tmp_path / "small-preview.dng"
    write_dng(path, embedded=True, small_preview=True)
    full = decode_response(client.get("/api/images/preview", params={"path": str(path)}))
    assert full.shape == (128, 96, 3)
    assert full.std() > 10


def test_viewable_but_unsupported_raw_reports_decoder_error_on_detection(tmp_path):
    for index in range(2):
        write_dng(tmp_path / f"frame_{index}.dng", embedded=True)
    app = FastAPI()
    app.include_router(stars_router)
    with TestClient(app) as client:
        response = client.post("/api/stars/detect", json={"path": str(tmp_path)})
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "Cannot decode RAW pixels" in detail
    assert "frame_" in detail
    assert "embedded preview" in detail
    assert "16-bit TIFF" in detail
    assert "Could not match" not in detail


@pytest.mark.parametrize("content", [b"not a camera image", b""])
def test_unreadable_dng_returns_decode_error(client, tmp_path, content):
    path = tmp_path / "broken.dng"
    path.write_bytes(content)
    response = client.get("/api/images/preview", params={"path": str(path)})
    assert response.status_code == 422
    assert response.json() == {"detail": "Unable to decode image preview"}
