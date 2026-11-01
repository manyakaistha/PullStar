"""
Star Trail Aligner - I/O Utilities

This module handles all image loading and saving operations, including:
- Loading RAW files (NEF, CR2, ARW, etc.) using rawpy
- Loading standard formats (JPG, TIFF, PNG) using OpenCV
- Sorting images by EXIF creation timestamp
- Saving final output as TIFF with appropriate bit depth
"""

import os
import cv2
import numpy as np
import rawpy
from functools import lru_cache
from core.cancellation import check_cancelled
from pathlib import Path
from typing import List, Tuple, Optional, Union
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    RAW_EXTENSIONS,
    STANDARD_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
    VERBOSE,
    CHROMA_NOISE_REDUCTION_STRENGTH,
)


def get_exif_datetime(filepath: Path) -> Optional[datetime]:
    """
    Extract the creation datetime from image EXIF data.
    
    Tries multiple methods in order of preference:
    1. piexif for EXIF DateTimeOriginal
    2. File modification time as fallback
    
    Args:
        filepath: Path to the image file
        
    Returns:
        datetime object or None if extraction fails
    """
    filepath = Path(filepath)
    try:
        stat = filepath.stat()
        return _get_exif_datetime_cached(str(filepath.resolve()), stat.st_mtime_ns, stat.st_size)
    except OSError:
        return None


@lru_cache(maxsize=4096)
def _get_exif_datetime_cached(path: str, st_mtime_ns: int, st_size: int) -> Optional[datetime]:
    """Read EXIF once for an unchanged file.

    The stat tuple is part of the cache key so replacing an image at the same
    path cannot return stale capture metadata.
    """
    filepath = Path(path)
    ext = filepath.suffix.lower()
    
    # DNG is a TIFF/EXIF container too. File mtimes can change during copying or
    # ZIP extraction and must not reorder exposures or create artificial gaps.
    if ext in STANDARD_EXTENSIONS or ext == ".dng":
        try:
            import piexif
            exif_dict = piexif.load(str(filepath))
            
            # Try DateTimeOriginal first (when photo was taken)
            if piexif.ExifIFD.DateTimeOriginal in exif_dict.get('Exif', {}):
                dt_str = exif_dict['Exif'][piexif.ExifIFD.DateTimeOriginal]
                if isinstance(dt_str, bytes):
                    dt_str = dt_str.decode('utf-8')
                return datetime.strptime(dt_str, '%Y:%m:%d %H:%M:%S')
            
            # Fallback to DateTime (modification time in EXIF)
            if piexif.ImageIFD.DateTime in exif_dict.get('0th', {}):
                dt_str = exif_dict['0th'][piexif.ImageIFD.DateTime]
                if isinstance(dt_str, bytes):
                    dt_str = dt_str.decode('utf-8')
                return datetime.strptime(dt_str, '%Y:%m:%d %H:%M:%S')
                
        except Exception:
            pass  # Fall through to file mtime
    
    # Other RAW containers, or files without readable EXIF, use mtime.
    try:
        return datetime.fromtimestamp(st_mtime_ns / 1_000_000_000)
    except Exception as e:
        if VERBOSE:
            print(f"Warning: Could not get datetime for {filepath.name}: {e}")
        return None


def get_timestamps_for_files(file_list: List[Path], cancel_check=None) -> List[datetime]:
    """
    Get timestamps for a list of files.
    
    Args:
        file_list: List of image file paths
        
    Returns:
        List of datetime objects (same order as input)
        Files without valid timestamps get datetime.min
    """
    timestamps = []
    for filepath in file_list:
        check_cancelled(cancel_check)
        dt = get_exif_datetime(filepath)
        if dt is None:
            dt = datetime.min
        timestamps.append(dt)
    return timestamps


def get_image_list(folder_path: Union[str, Path], sort_by_time: bool = True,
                   cancel_check=None) -> List[Path]:
    """
    Get a sorted list of all supported image files in a folder.
    
    Args:
        folder_path: Path to the folder containing images
        sort_by_time: If True, sort by EXIF/file creation time. If False, sort by filename.
        
    Returns:
        List of Path objects to image files, sorted appropriately
        
    Raises:
        FileNotFoundError: If folder doesn't exist
        ValueError: If no supported images found
    """
    folder = Path(folder_path)
    
    if not folder.exists():
        raise FileNotFoundError(f"Folder not found: {folder}")
    
    if not folder.is_dir():
        raise ValueError(f"Path is not a directory: {folder}")
    
    # A single directory pass avoids one glob/system call per extension and
    # naturally handles mixed-case suffixes on every filesystem.
    supported = {ext.lower() for ext in SUPPORTED_EXTENSIONS}
    image_files = []
    with os.scandir(folder) as entries:
        for entry in entries:
            check_cancelled(cancel_check)
            if entry.is_file() and Path(entry.name).suffix.lower() in supported:
                image_files.append(Path(entry.path))
    
    if not image_files:
        raise ValueError(f"No supported image files found in {folder}")
    
    if sort_by_time:
        # Sort by creation/modification time
        def get_sort_key(f: Path) -> Tuple[datetime, str]:
            check_cancelled(cancel_check)
            dt = get_exif_datetime(f)
            if dt is None:
                dt = datetime.min
            return (dt, f.name)
        
        image_files.sort(key=get_sort_key)
    else:
        # Sort by filename
        image_files.sort(key=lambda f: f.name)
    
    if VERBOSE:
        print(f"Found {len(image_files)} images in {folder}")
        if image_files:
            print(f"  First: {image_files[0].name}")
            print(f"  Last:  {image_files[-1].name}")
    
    check_cancelled(cancel_check)
    return image_files


def is_raw_file(filepath: Path) -> bool:
    """Check if a file is a RAW image based on extension."""
    return filepath.suffix.lower() in RAW_EXTENSIONS


def load_raw(filepath: Path, for_tracking: bool = False, *, noise_reduction=False,
             exposure_ev=0.0) -> np.ndarray:
    """
    Load a RAW image file and convert to BGR numpy array.
    
    Args:
        filepath: Path to the RAW file
        for_tracking: If True, use simpler processing optimized for star detection.
                     If False, use full color-corrected output for final images.
        
    Returns:
        numpy array in BGR format, dtype uint16 (16-bit)
    """
    try:
        return _develop_raw(filepath, for_tracking, noise_reduction, exposure_ev)
    except (rawpy.LibRawError, rawpy.NotSupportedError) as error:
        version = ".".join(map(str, rawpy.libraw_version))
        detail = (f"Cannot decode RAW pixels in {filepath.name} with rawpy "
                  f"{rawpy.__version__} / LibRaw {version}: {error}.")
        if isinstance(error, rawpy.LibRawFileUnsupportedError):
            detail += (" An embedded preview may still be viewable. Convert the sequence "
                       "to a supported RAW encoding or 16-bit TIFF for alignment.")
        raise OSError(detail) from error


def _develop_raw(filepath: Path, for_tracking: bool, noise_reduction=False,
                 exposure_ev=0.0) -> np.ndarray:
    with rawpy.imread(str(filepath)) as raw:
        if for_tracking:
            # For tracking: use simpler processing - we just need to find bright spots
            rgb = raw.postprocess(
                use_camera_wb=True,
                no_auto_bright=True,
                output_bps=16,
                gamma=(1, 1),  # Linear for accurate star detection
                demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD,
            )
        else:
            # For final output: use proper color processing with noise reduction
            rgb = raw.postprocess(
                use_camera_wb=True,           # Use camera's white balance
                no_auto_bright=True,          # Don't auto-brighten (preserve exposure)
                output_bps=16,                # 16-bit output
                gamma=(1, 1) if noise_reduction else (2.222, 4.5),
                exp_shift=2.0 ** exposure_ev,
                output_color=rawpy.ColorSpace.sRGB,  # sRGB color space
                # Standard wheels omit the GPL demosaic pack required by LMMSE.
                demosaic_algorithm=(rawpy.DemosaicAlgorithm.LMMSE
                                    if rawpy.DemosaicAlgorithm.LMMSE.isSupported
                                    else rawpy.DemosaicAlgorithm.AHD),
                fbdd_noise_reduction=rawpy.FBDDNoiseReductionMode.Full,  # Reduce chroma noise
            )
    
    
    # Convert RGB to BGR for OpenCV compatibility
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    if not for_tracking and noise_reduction:
        from modules.raw_recovery import denoise_linear, display_gamma
        bgr = display_gamma(denoise_linear(bgr))
    
    # Apply additional chroma noise reduction for export
    if not for_tracking:
        bgr = reduce_chroma_noise(bgr)
    
    return bgr


def reduce_chroma_noise(image: np.ndarray, strength: int = CHROMA_NOISE_REDUCTION_STRENGTH) -> np.ndarray:
    """
    Reduce color (chroma) noise while preserving structural (luminance) detail.
    
    Converting to LAB color space allows us to blur the A and B (color) channels
    aggressively without affecting the L (lightness) channel, which contains the details.
    
    Args:
        image: BGR image
        strength: Kernel size for blurring (must be odd)
        
    Returns:
        Denoised BGR image
    """
    # Ensure kernel size is odd
    if strength % 2 == 0:
        strength += 1
        
    # OpenCV's Lab conversion accepts uint8 or normalized float32, not uint16.
    # Retain 16-bit precision instead of reducing a RAW frame to eight bits.
    is_16_bit = image.dtype == np.uint16
    working = image.astype(np.float32) if is_16_bit else image
    if is_16_bit:
        np.divide(working, 65535.0, out=working)
    lab = cv2.cvtColor(working, cv2.COLOR_BGR2Lab)
    
    # Keep luminance in the original Lab buffer. Only one contiguous chroma
    # channel is needed at a time; GaussianBlur supports an in-place dst.
    for channel in (1, 2):
        chroma = cv2.extractChannel(lab, channel)
        cv2.GaussianBlur(chroma, (strength, strength), 0, dst=chroma)
        cv2.insertChannel(chroma, lab, channel)
    if is_16_bit:
        cv2.cvtColor(lab, cv2.COLOR_Lab2BGR, dst=working)
        np.multiply(working, 65535, out=working)
        np.rint(working, out=working)
        np.clip(working, 0, 65535, out=working)
        return working.astype(np.uint16)
    return cv2.cvtColor(lab, cv2.COLOR_Lab2BGR)


def load_raw_for_tracking(filepath: Path) -> np.ndarray:
    """
    Load a RAW image optimized for star tracking (simpler, faster processing).
    
    Args:
        filepath: Path to the RAW file
        
    Returns:
        numpy array in BGR format
    """
    return load_raw(filepath, for_tracking=True)


def load_raw_for_export(filepath: Path) -> np.ndarray:
    """
    Load a RAW image with full color processing for final export.
    
    Args:
        filepath: Path to the RAW file
        
    Returns:
        numpy array in BGR format with proper colors
    """
    return load_raw(filepath, for_tracking=False)


def load_standard(filepath: Path) -> np.ndarray:
    """
    Load a standard image file (JPG, TIFF, PNG) as BGR numpy array.
    
    Args:
        filepath: Path to the image file
        
    Returns:
        numpy array in BGR format
    """
    # IMREAD_UNCHANGED preserves bit depth and alpha channel
    img = cv2.imread(str(filepath), cv2.IMREAD_UNCHANGED)
    
    if img is None:
        raise IOError(f"Failed to load image: {filepath}")
    
    # Handle grayscale images
    if len(img.shape) == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    
    # Handle RGBA images (drop alpha)
    if len(img.shape) == 3 and img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    
    return img


def load_image(filepath: Union[str, Path], for_export: bool = False, *,
               raw_noise_reduction=False, raw_exposure_ev=0.0) -> np.ndarray:
    """
    Universal image loader - handles both RAW and standard formats.
    
    Args:
        filepath: Path to the image file
        for_export: If True, use full color-corrected processing for RAW files.
                   If False, use simpler processing optimized for tracking.
        
    Returns:
        numpy array in BGR format
        
    Raises:
        ValueError: If file extension is not supported
        IOError: If file cannot be loaded
    """
    filepath = Path(filepath)
    
    if not filepath.exists():
        raise FileNotFoundError(f"Image not found: {filepath}")
    
    ext = filepath.suffix.lower()
    
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file extension: {ext}")
    
    if is_raw_file(filepath):
        return load_raw(filepath, for_tracking=not for_export,
                        noise_reduction=raw_noise_reduction, exposure_ev=raw_exposure_ev)
    else:
        return load_standard(filepath)


def get_image_info(filepath: Union[str, Path]) -> dict:
    """
    Get basic information about an image without fully loading it.
    
    Args:
        filepath: Path to the image file
        
    Returns:
        Dict with keys: width, height, channels, dtype, is_raw
    """
    filepath = Path(filepath)
    try:
        stat = filepath.stat()
        return _get_image_info_cached(str(filepath.resolve()), stat.st_mtime_ns, stat.st_size).copy()
    except OSError as error:
        raise IOError(f"Failed to read image: {filepath}") from error


@lru_cache(maxsize=2048)
def _get_image_info_cached(path: str, st_mtime_ns: int, st_size: int) -> dict:
    """Inspect dimensions and sample type from image headers when possible."""
    filepath = Path(path)
    is_raw = is_raw_file(filepath)
    if is_raw:
        with rawpy.imread(str(filepath)) as raw:
            height, width = raw.sizes.height, raw.sizes.width
            if raw.sizes.flip & 4:
                height, width = width, height
            return {'width': width, 'height': height, 'channels': 3,
                    'dtype': 'uint16', 'is_raw': True}

    # Pillow parses JPEG/PNG/TIFF headers without expanding the pixel buffer.
    # OpenCV remains the compatibility fallback for uncommon codecs/modes.
    try:
        from PIL import Image
        with Image.open(filepath) as image:
            width, height = image.size
            if image.format == "PNG":
                # Pillow exposes 16-bit RGB PNGs as mode RGB (8-bit). The
                # IHDR sample depth is authoritative, not the display mode.
                with filepath.open("rb") as stream:
                    header = stream.read(26)
                depth, colour = header[24:26]
                dtype = "uint16" if depth == 16 else "uint8"
                channels = {0: 1, 2: 3, 3: 3, 4: 4, 6: 4}[colour]
                if "transparency" in image.info:
                    channels = 4
            elif image.format == "JPEG":
                dtype = "uint8"
                channels = 1 if image.mode == "L" else 3
            elif image.format == "TIFF":
                tags = image.tag_v2
                bits = tags.get(258, (1,))
                bits = (bits,) if isinstance(bits, int) else bits
                sample_format = tags.get(339, (1,))
                sample_format = ((sample_format,) if isinstance(sample_format, int)
                                 else sample_format)
                photometric = tags.get(262, 1)
                if len(set(bits)) != 1 or set(sample_format) != {1} or photometric not in (0, 1, 2):
                    raise ValueError("TIFF sample layout needs decoder inspection")
                if bits[0] not in (1, 8, 16):
                    raise ValueError("TIFF sample depth needs decoder inspection")
                dtype = "uint16" if bits[0] == 16 else "uint8"
                channels = int(tags.get(277, 1))
                if tags.get(274, 1) in (5, 6, 7, 8):
                    width, height = height, width
            else:
                raise ValueError("Use the established decoder for other formats")
            return {'width': width, 'height': height, 'channels': channels,
                    'dtype': dtype, 'is_raw': False}
    except Exception:
        img = cv2.imread(str(filepath), cv2.IMREAD_UNCHANGED)
        if img is None:
            raise IOError(f"Failed to read image: {filepath}")
        if img.ndim == 2:
            height, width, channels = (*img.shape, 1)
        else:
            height, width, channels = img.shape
        return {'width': width, 'height': height, 'channels': channels,
                'dtype': str(img.dtype), 'is_raw': False}


def save_tiff(
    image: np.ndarray,
    filepath: Union[str, Path],
    bit_depth: Optional[int] = None,
    default_filename: str = "aligned_star_trails.tiff"
) -> Path:
    """
    Save an image as a TIFF file with specified bit depth.
    
    Args:
        image: numpy array to save (BGR format expected)
        filepath: Output path (can be a file path or directory path)
        bit_depth: 8 or 16. If None, infers from input dtype.
        default_filename: Filename to use if filepath is a directory
        
    Returns:
        Path to the saved file
    """
    filepath = Path(filepath)
    
    # Handle case where user provides a directory path instead of file path
    # Check if it looks like a directory (no extension or existing directory)
    if filepath.is_dir() or (not filepath.suffix and not filepath.exists()):
        # It's a directory path - create it and use default filename
        filepath.mkdir(parents=True, exist_ok=True)
        filepath = filepath / default_filename
    else:
        # It's a file path - ensure it has .tiff extension
        if filepath.suffix.lower() not in ('.tif', '.tiff'):
            filepath = filepath.with_suffix('.tiff')
        # Create parent directory if needed
        filepath.parent.mkdir(parents=True, exist_ok=True)
    
    # Determine bit depth
    if bit_depth is None:
        if image.dtype == np.float32 or image.dtype == np.float64:
            bit_depth = 16
        elif image.dtype == np.uint16:
            bit_depth = 16
        else:
            bit_depth = 8
    
    # Convert by row chunks to retain the original divide-then-multiply
    # rounding without two full-frame floating intermediates. Never mutate the
    # accumulator: callers may still need it for video or checkpoints.
    target = np.uint16 if bit_depth == 16 else np.uint8
    maximum = 65535 if bit_depth == 16 else 255
    if image.dtype in (np.float32, np.float64):
        max_val = image.max()
        output = np.empty(image.shape, target)
        rows = max(1, 262144 // max(1, int(np.prod(image.shape[1:]))))
        for start in range(0, len(image), rows):
            chunk = image[start:start + rows]
            if max_val > 0:
                work = np.divide(chunk, max_val)
                np.multiply(work, maximum, out=work)
                output[start:start + rows] = work
            else:
                output[start:start + rows] = chunk
        image = output
    elif image.dtype == np.uint8 and bit_depth == 16:
        image = np.multiply(image, 257, dtype=np.uint16)
    elif image.dtype == np.uint16 and bit_depth != 16:
        image = np.floor_divide(image, 257).astype(np.uint8)
    elif image.dtype != target:
        image = image.astype(target)

    # Save using OpenCV
    success = cv2.imwrite(str(filepath), image)
    
    if not success:
        raise IOError(f"Failed to save image: {filepath}")
    
    if VERBOSE:
        print(f"Saved: {filepath} ({bit_depth}-bit)")
    
    return filepath


def save_jpeg(
    image: np.ndarray,
    filepath: Union[str, Path],
    quality: int = 95,
) -> Path:
    """Save a BGR image as an 8-bit JPEG.

    JPEG does not support 16-bit samples.  Converting by the sensor/display
    range (65535 -> 255) preserves the exposure boost already applied while
    avoiding a per-frame contrast stretch that would change the relative
    brightness of the sequence.
    """
    filepath = Path(filepath)
    if filepath.suffix.lower() not in (".jpg", ".jpeg"):
        filepath = filepath.with_suffix(".jpg")
    filepath.parent.mkdir(parents=True, exist_ok=True)

    if image.dtype == np.uint16:
        output = np.floor_divide(image, 257).astype(np.uint8)
    elif image.dtype == np.uint8:
        output = image
    else:
        raise ValueError("JPEG conversion requires 8-bit or 16-bit source pixels")

    success = cv2.imwrite(str(filepath), output, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not success:
        raise IOError(f"Failed to save image: {filepath}")
    return filepath


def convert_image_for_stacking(
    source_path: Union[str, Path],
    destination_path: Union[str, Path],
    conversion_format: str,
    *,
    raw_noise_reduction: bool = True,
    raw_exposure_ev: float = 0.0,
    cancel_check=None,
) -> Path:
    """Decode one source image with export settings and save a stack input.

    The returned file is a normal OpenCV-readable image, which means the
    expensive RAW development is paid once during preparation instead of once
    per downstream pipeline pass.
    """
    check_cancelled(cancel_check)
    source_path = Path(source_path)
    destination_path = Path(destination_path)
    conversion_format = conversion_format.lower()
    if conversion_format not in {"jpg", "tiff"}:
        raise ValueError(f"Unsupported conversion format: {conversion_format}")

    image = load_image(
        source_path,
        for_export=True,
        raw_noise_reduction=raw_noise_reduction,
        raw_exposure_ev=raw_exposure_ev,
    )
    check_cancelled(cancel_check)
    if conversion_format == "jpg":
        result = save_jpeg(image, destination_path)
    else:
        if image.dtype == np.uint8:
            image = np.multiply(image, 257, dtype=np.uint16)
        elif image.dtype != np.uint16:
            raise ValueError("TIFF conversion requires 8-bit or 16-bit source pixels")
        result = destination_path.with_suffix(".tiff")
        result.parent.mkdir(parents=True, exist_ok=True)
        # Uncompressed intermediates trade disk space for fast sequential reads
        # while preserving every developed 16-bit sample without stretching.
        if not cv2.imwrite(str(result), image, [cv2.IMWRITE_TIFF_COMPRESSION, 1]):
            raise IOError(f"Failed to save image: {result}")
    del image

    # Use capture time, not the source mtime: copying/extracting RAW files often
    # changes mtimes. Timing controls gap filling and trail extrapolation.
    captured = get_exif_datetime(source_path)
    stat = source_path.stat()
    if captured is not None:
        timestamp_ns = round(captured.timestamp() * 1_000_000_000)
        os.utime(result, ns=(stat.st_atime_ns, timestamp_ns))
    else:
        os.utime(result, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    check_cancelled(cancel_check)
    return result


def determine_output_bit_depth(sample_image: np.ndarray, is_raw: bool) -> int:
    """
    Determine appropriate output bit depth based on input.
    
    Args:
        sample_image: A sample image from the input set
        is_raw: Whether the source was a RAW file
        
    Returns:
        8 or 16
    """
    if is_raw:
        return 16
    elif sample_image.dtype == np.uint16:
        return 16
    else:
        return 8
