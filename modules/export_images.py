"""Image export with fixed sample ranges, preserving brightness across a sequence."""
from pathlib import Path
import cv2
import numpy as np

FORMATS = {"tiff": ".tiff", "png": ".png", "jpg": ".jpg"}


def save_export_image(image, path, image_format, source_dtype="uint8"):
    path = Path(path)
    if image_format not in FORMATS:
        raise ValueError("Image format must be tiff, png, or jpg")
    target = np.uint8 if image_format == "jpg" or source_dtype != "uint16" else np.uint16
    maximum = 65535 if source_dtype == "uint16" else 255
    # Never normalize each frame by its brightest pixel: that causes flicker.
    pixels = np.clip(image, 0, maximum)
    if target == np.uint8 and maximum == 65535:
        pixels = pixels / 257
    pixels = pixels.astype(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    params = [cv2.IMWRITE_JPEG_QUALITY, 95] if image_format == "jpg" else []
    if not cv2.imwrite(str(path), pixels, params):
        raise IOError(f"Failed to save image: {path}")
    return path


def save_stack_export(image, path, bit_depth, image_format="tiff"):
    """Write a final stack directly, retaining the stack's legacy tonal range."""
    if image_format == "tiff":
        from modules.io_utils import save_tiff
        return save_tiff(image, path, bit_depth=bit_depth)
    dtype = np.uint16 if bit_depth == 16 else np.uint8
    maximum = 65535 if bit_depth == 16 else 255
    if image.dtype in (np.float32, np.float64):
        peak = float(image.max())
        pixels = np.empty(image.shape, dtype=dtype)
        rows = max(1, 262144 // max(1, int(np.prod(image.shape[1:]))))
        for start in range(0, len(image), rows):
            chunk = image[start:start + rows]
            work = chunk / peak * maximum if peak > 0 else chunk
            pixels[start:start + rows] = np.clip(work, 0, maximum)
    else:
        pixels = image
    return save_export_image(pixels, path, image_format, np.dtype(dtype).name)
