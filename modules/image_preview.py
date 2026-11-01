"""Display-only RAW rendering, independent of the 16-bit processing pipeline."""

from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
import rawpy
from PIL import Image


# LibRaw's flip flags differ from TIFF/EXIF orientation values.
_RAW_ORIENTATION = {0: 1, 1: 2, 2: 4, 3: 3, 4: 5, 5: 8, 6: 6, 7: 7}
_TRANSPOSE = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}


def _embedded_preview(raw: rawpy.RawPy, max_size: int | None = None) -> np.ndarray:
    """Decode the camera's rendered preview and apply its orientation once."""
    thumb = raw.extract_thumb()
    if thumb.format == rawpy.ThumbFormat.JPEG:
        with Image.open(BytesIO(thumb.data)) as image:
            orientation = image.getexif().get(274)
            if max_size is not None:
                # JPEG draft decoding avoids expanding a 50 MP DNG preview
                # into a full RGB buffer just to draw a tiny filmstrip tile.
                image.draft("RGB", (max_size, max_size))
                image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            rgb = image.convert("RGB")
    elif thumb.format == rawpy.ThumbFormat.BITMAP:
        rgb = Image.fromarray(thumb.data)
        orientation = None
        if max_size is not None:
            rgb.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    else:
        raise ValueError("Unsupported embedded preview format")

    if orientation not in range(1, 9):
        orientation = _RAW_ORIENTATION.get(raw.sizes.flip, 1)
    if orientation in _TRANSPOSE:
        rgb = rgb.transpose(_TRANSPOSE[orientation])
    return cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR)


def load_raw_preview(filepath: Path, *, max_size: int | None = None) -> np.ndarray:
    """Use a camera render when available, otherwise portable 8-bit demosaicing.

    In particular, Samsung JPEG-XL DNGs contain a full-size JPEG that LibRaw
    can extract even when its RAW decoder does not support the compression.
    These pixels are for viewing only; alignment/export still use load_image.
    """
    with rawpy.imread(str(filepath)) as raw:
        height, width = raw.sizes.height, raw.sizes.width
        if raw.sizes.flip & 4:
            height, width = width, height

        # Extract before unpacking the RAW: a failed unpack can leave LibRaw
        # unable to extract an otherwise readable embedded JPEG afterwards.
        try:
            embedded = _embedded_preview(raw, max_size)
        except (rawpy.LibRawError, rawpy.NotSupportedError, OSError, ValueError):
            embedded = None

        if embedded is not None and (
            max_size is not None or embedded.shape[:2] == (height, width)
        ):
            return embedded

        try:
            rgb = raw.postprocess(
                use_camera_wb=True,
                output_bps=8,
                output_color=rawpy.ColorSpace.sRGB,
                gamma=(2.222, 4.5),
                no_auto_bright=False,
                half_size=max_size is not None and max_size <= max(height, width) // 2,
                # AHD is included in standard rawpy wheels. LMMSE requires
                # an optional demosaic pack.
                demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD,
            )
            return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        except (rawpy.LibRawError, rawpy.NotSupportedError):
            if embedded is None:
                raise
            # Keep full-view reference picking in the RAW's pixel coordinates
            # even if an unsupported camera provides only a small preview.
            return cv2.resize(embedded, (width, height), interpolation=cv2.INTER_CUBIC)
