"""
Star Trail Aligner - Rotation Engine

Provides image rotation functions optimized for star trail work:
- Standard OpenCV rotation (fast, good for large angles)
- Phase-based FFT rotation (sharper, better for small angles < 5°)

The phase-based rotation is particularly useful for synthetic trail
extension where we generate many small-angle rotations.

Note: All operations use CPU (numpy FFT). No CUDA dependencies.
Works on Mac Metal/CPU, Linux, and Windows.
"""

import cv2
import numpy as np
from typing import Tuple, Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import PHASE_ROTATION_MAX_ANGLE, USE_PHASE_ROTATION


def rotate_image(
    image: np.ndarray,
    angle_degrees: float,
    center: Tuple[float, float],
    use_phase: bool = USE_PHASE_ROTATION
) -> np.ndarray:
    """
    Rotate an image around a specified center point.
    
    Automatically selects the best rotation method based on angle size
    and configuration settings.
    
    Args:
        image: Input image (grayscale or BGR, uint8/uint16/float32)
        angle_degrees: Rotation angle in degrees (positive = counterclockwise)
        center: (x, y) center of rotation
        use_phase: Whether to use phase-based rotation for small angles
        
    Returns:
        Rotated image with same shape and dtype as input
    """
    if abs(angle_degrees) < 0.001:
        # Negligible rotation, return copy
        return image.copy()
    
    # Use phase-based rotation for small angles if enabled
    if use_phase and abs(angle_degrees) <= PHASE_ROTATION_MAX_ANGLE:
        return rotate_via_phase(image, angle_degrees, center)
    else:
        return _rotate_standard(image, angle_degrees, center)


def _rotate_standard(
    image: np.ndarray,
    angle_degrees: float,
    center: Tuple[float, float]
) -> np.ndarray:
    """
    Standard rotation using OpenCV's warpAffine.
    
    Fast and robust for all angles. Uses LANCZOS interpolation
    for best quality with star images.
    """
    h, w = image.shape[:2]
    
    # Get rotation matrix
    M = cv2.getRotationMatrix2D(center, angle_degrees, 1.0)
    
    # Apply rotation with LANCZOS interpolation
    rotated = cv2.warpAffine(
        image,
        M,
        (w, h),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0
    )
    
    return rotated


def rotate_via_phase(
    image: np.ndarray,
    angle_degrees: float,
    center: Tuple[float, float]
) -> np.ndarray:
    """
    Rotate image using phase-space transformation in frequency domain.
    
    This method provides sharper results for small angles by avoiding
    spatial interpolation. Instead, it applies the rotation as a phase
    shift in Fourier space.
    
    Note: Best for angles < 5 degrees. For larger angles, use standard
    rotation to avoid artifacts.
    
    Args:
        image: Input image
        angle_degrees: Rotation angle in degrees
        center: (x, y) rotation center
        
    Returns:
        Rotated image
    """
    # Convert to float for processing
    original_dtype = image.dtype
    if image.dtype == np.uint8:
        img_float = image.astype(np.float32) / 255.0
        scale = 255.0
    elif image.dtype == np.uint16:
        img_float = image.astype(np.float32) / 65535.0
        scale = 65535.0
    else:
        img_float = image.astype(np.float32)
        scale = 1.0
    
    h, w = img_float.shape[:2]
    cx, cy = center
    
    # For very small angles, the phase-based approach works well
    # For angles approaching the threshold, blend with standard rotation
    blend_start = PHASE_ROTATION_MAX_ANGLE * 0.7
    
    if abs(angle_degrees) > blend_start:
        # Blend phase and standard rotation for smoother transition
        alpha = (abs(angle_degrees) - blend_start) / (PHASE_ROTATION_MAX_ANGLE - blend_start)
        phase_result = _rotate_phase_core(img_float, angle_degrees, center)
        standard_result = _rotate_standard(img_float, angle_degrees, center)
        result = (1 - alpha) * phase_result + alpha * standard_result
    else:
        result = _rotate_phase_core(img_float, angle_degrees, center)
    
    # Convert back to original dtype
    if original_dtype == np.uint8:
        return (np.clip(result * scale, 0, 255)).astype(np.uint8)
    elif original_dtype == np.uint16:
        return (np.clip(result * scale, 0, 65535)).astype(np.uint16)
    else:
        return result.astype(original_dtype)


def _rotate_phase_core(
    image: np.ndarray,
    angle_degrees: float,
    center: Tuple[float, float]
) -> np.ndarray:
    """
    Core phase-based rotation implementation.
    
    Uses three shear decomposition of rotation followed by FFT-based shear.
    R(θ) = Sx(tan(θ/2)) @ Sy(sin(θ)) @ Sx(tan(θ/2))
    
    This is more numerically stable than direct frequency-domain rotation.
    """
    angle_rad = np.radians(angle_degrees)
    
    h, w = image.shape[:2]
    cx, cy = center
    
    # Check if color image
    is_color = len(image.shape) == 3 and image.shape[2] == 3
    
    if is_color:
        # Process each channel
        channels = cv2.split(image)
        rotated_channels = []
        for ch in channels:
            rotated_ch = _shear_rotate_channel(ch, angle_rad, (cx, cy))
            rotated_channels.append(rotated_ch)
        result = cv2.merge(rotated_channels)
    else:
        result = _shear_rotate_channel(image, angle_rad, (cx, cy))
    
    return result


def _shear_rotate_channel(
    channel: np.ndarray,
    angle_rad: float,
    center: Tuple[float, float]
) -> np.ndarray:
    """
    Rotate a single channel using three-shear decomposition.
    
    For small angles, this provides excellent quality.
    """
    h, w = channel.shape
    cx, cy = center
    
    # Compute shear values
    # tan(θ/2) for horizontal shears, sin(θ) for vertical shear
    tan_half = np.tan(angle_rad / 2)
    sin_theta = np.sin(angle_rad)
    
    # For very small angles, use direct shear
    # This avoids numerical issues with tan() near zero
    if abs(angle_rad) < 0.01:
        # For tiny angles, linear approximation works well
        # Just apply a single small shear
        result = _apply_fft_shear_x(channel, angle_rad, center)
        return result
    
    # Three-shear decomposition
    # 1. Horizontal shear by tan(θ/2)
    temp1 = _apply_fft_shear_x(channel, tan_half, center)
    # 2. Vertical shear by sin(θ)
    temp2 = _apply_fft_shear_y(temp1, -sin_theta, center)
    # 3. Horizontal shear by tan(θ/2)
    result = _apply_fft_shear_x(temp2, tan_half, center)
    
    return result


def _apply_fft_shear_x(
    channel: np.ndarray,
    shear_amount: float,
    center: Tuple[float, float]
) -> np.ndarray:
    """Apply horizontal shear using FFT."""
    h, w = channel.shape
    cx, cy = center
    
    spectrum = np.fft.rfft(np.asarray(channel, dtype=np.float32), axis=1)
    freq_x = np.fft.rfftfreq(w).astype(np.float32)[None, :]
    row = np.arange(h, dtype=np.float32)[:, None] - np.float32(cy)
    phase = np.exp((-2j * np.pi * freq_x * np.float32(shear_amount) * row)
                   .astype(np.complex64))
    result = np.fft.irfft(spectrum * phase, n=w, axis=1)

    return np.clip(result, 0, None)


def _apply_fft_shear_y(
    channel: np.ndarray,
    shear_amount: float,
    center: Tuple[float, float]
) -> np.ndarray:
    """Apply vertical shear using FFT."""
    h, w = channel.shape
    cx, cy = center
    
    spectrum = np.fft.rfft(np.asarray(channel, dtype=np.float32), axis=0)
    freq_y = np.fft.rfftfreq(h).astype(np.float32)[:, None]
    column = np.arange(w, dtype=np.float32)[None, :] - np.float32(cx)
    phase = np.exp((-2j * np.pi * freq_y * np.float32(shear_amount) * column)
                   .astype(np.complex64))
    result = np.fft.irfft(spectrum * phase, n=h, axis=0)

    return np.clip(result, 0, None)


def calculate_rotation_angle(
    star1_old: Tuple[float, float],
    star1_new: Tuple[float, float],
    star2_old: Tuple[float, float],
    star2_new: Tuple[float, float],
    rotation_center: Tuple[float, float]
) -> float:
    """
    Calculate the rotation angle between two frames using two star positions.
    
    Uses the change in angle between the rotation center and the stars
    to compute the rotation.
    
    Args:
        star1_old: Position of first star in old frame
        star1_new: Position of first star in new frame
        star2_old: Position of second star in old frame
        star2_new: Position of second star in new frame
        rotation_center: Center of rotation (typically Polaris)
        
    Returns:
        Rotation angle in degrees (positive = counterclockwise)
    """
    cx, cy = rotation_center
    
    # Calculate angles for star 1
    angle1_old = np.arctan2(star1_old[1] - cy, star1_old[0] - cx)
    angle1_new = np.arctan2(star1_new[1] - cy, star1_new[0] - cx)
    delta1 = np.degrees(angle1_new - angle1_old)
    
    # Calculate angles for star 2
    angle2_old = np.arctan2(star2_old[1] - cy, star2_old[0] - cx)
    angle2_new = np.arctan2(star2_new[1] - cy, star2_new[0] - cx)
    delta2 = np.degrees(angle2_new - angle2_old)
    
    # Normalize to [-180, 180]
    def normalize_angle(angle):
        while angle > 180:
            angle -= 360
        while angle < -180:
            angle += 360
        return angle
    
    delta1 = normalize_angle(delta1)
    delta2 = normalize_angle(delta2)
    
    # Average the two measurements for robustness
    return (delta1 + delta2) / 2
