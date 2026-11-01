"""
Star Trail Aligner - Foreground Mask Module

Provides sky/ground segmentation for foreground preservation during
synthetic trail extension. This ensures the landscape stays sharp
while only the stars are rotated.

The segmentation uses a combination of:
1. Color analysis in HSV space (sky is typically blue/gray)
2. Brightness thresholding (stars are bright points)
3. Morphological cleanup (reduce noise)
"""

import cv2
import numpy as np
from typing import Optional, Tuple


def segment_sky_ground(
    image: np.ndarray,
    method: str = 'combined',
    refinement_iterations: int = 2
) -> np.ndarray:
    """
    Create a binary mask separating sky from ground.
    
    Args:
        image: Input image in BGR format (uint8 or uint16)
        method: Segmentation method ('brightness', 'color', 'combined')
        refinement_iterations: Number of morphological cleanup passes
        
    Returns:
        Binary mask where 255 = sky, 0 = ground
    """
    # Normalize to uint8 if needed
    if image.dtype == np.uint16:
        img_8bit = (image / 256).astype(np.uint8)
    elif image.dtype == np.float32 or image.dtype == np.float64:
        img_8bit = (np.clip(image, 0, 255)).astype(np.uint8)
    else:
        img_8bit = image.astype(np.uint8)
    
    if method == 'brightness':
        sky_mask = _segment_by_brightness(img_8bit)
    elif method == 'color':
        sky_mask = _segment_by_color(img_8bit)
    else:  # combined
        sky_mask = _segment_combined(img_8bit)
    
    # Morphological cleanup
    sky_mask = _morphological_cleanup(sky_mask, iterations=refinement_iterations)
    
    return sky_mask


def _segment_by_brightness(image: np.ndarray) -> np.ndarray:
    """
    Segment sky based on brightness threshold.
    
    Assumes sky is generally brighter than dark ground (common at night).
    Uses Otsu's method for automatic threshold selection.
    """
    # Convert to grayscale
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    
    # Apply Gaussian blur to reduce noise
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    
    # Use Otsu's method for automatic threshold
    _, sky_mask = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    return sky_mask


def _segment_by_color(image: np.ndarray) -> np.ndarray:
    """
    Segment sky based on color characteristics.
    
    Night sky is typically:
    - Low saturation (gray/dark blue)
    - Can be any hue, but often blue-ish
    - Darker than twilight/light pollution
    """
    # Convert to HSV
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    
    # Sky characteristics:
    # - Low saturation (< 100) for dark night sky
    # - High value (> 200) for twilight/light pollution
    # Combine both conditions
    low_saturation = s < 100
    high_brightness = v > 200
    
    sky_mask = (low_saturation | high_brightness).astype(np.uint8) * 255
    
    return sky_mask


def _segment_combined(image: np.ndarray) -> np.ndarray:
    """
    Combined sky segmentation using multiple methods.
    
    Uses color analysis, brightness, and edge detection to create
    a robust sky mask.
    """
    brightness_mask = _segment_by_brightness(image)
    color_mask = _segment_by_color(image)
    
    # Combine masks (pixels that satisfy either condition)
    combined = cv2.bitwise_or(brightness_mask, color_mask)
    
    return combined


def _morphological_cleanup(
    mask: np.ndarray,
    iterations: int = 2,
    kernel_size: int = 5
) -> np.ndarray:
    """
    Clean up mask using morphological operations.
    
    1. Close (fill small holes) - for gaps in star trails
    2. Open (remove small noise) - for false positives
    """
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    
    result = mask
    for _ in range(iterations):
        # Close: fill small holes
        result = cv2.morphologyEx(result, cv2.MORPH_CLOSE, kernel)
        # Open: remove small noise
        result = cv2.morphologyEx(result, cv2.MORPH_OPEN, kernel)
    
    return result


def detect_horizon_line(image: np.ndarray) -> Optional[Tuple[int, float]]:
    """
    Attempt to detect the horizon line using edge detection.
    
    Returns:
        Tuple of (y_position, angle_degrees) or None if not detected
    """
    # Convert to grayscale
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    
    # Edge detection
    edges = cv2.Canny(gray, 50, 150)
    
    # Hough line detection
    lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=200)
    
    if lines is None or len(lines) == 0:
        return None
    
    # Find predominantly horizontal lines
    horizontal_lines = []
    for line in lines:
        rho, theta = line[0]
        # Horizontal lines have theta near 0 or pi
        angle_deg = np.degrees(theta)
        if abs(angle_deg - 90) < 20:  # Near horizontal
            y = int(rho / np.sin(theta)) if np.sin(theta) != 0 else 0
            horizontal_lines.append((y, angle_deg - 90))
    
    if not horizontal_lines:
        return None
    
    # Return the most prominent horizontal line (assuming it's horizon)
    # Sort by y position and return median
    horizontal_lines.sort(key=lambda x: x[0])
    median_idx = len(horizontal_lines) // 2
    
    return horizontal_lines[median_idx]


def create_gradient_mask(
    height: int,
    width: int,
    horizon_y: int,
    transition_height: int = 100
) -> np.ndarray:
    """
    Create a gradient mask for smooth sky/ground transition.
    
    Args:
        height: Image height
        width: Image width
        horizon_y: Y position of horizon line
        transition_height: Height of gradient transition zone
        
    Returns:
        Gradient mask (0-255) with smooth sky-ground transition
    """
    mask = np.zeros((height, width), dtype=np.float32)
    
    for y in range(height):
        if y < horizon_y - transition_height // 2:
            # Pure sky
            mask[y, :] = 255
        elif y > horizon_y + transition_height // 2:
            # Pure ground
            mask[y, :] = 0
        else:
            # Transition zone
            progress = (y - (horizon_y - transition_height // 2)) / transition_height
            mask[y, :] = 255 * (1 - progress)
    
    return mask.astype(np.uint8)


def apply_mask_to_image(
    image: np.ndarray,
    mask: np.ndarray,
    feather: int = 5
) -> np.ndarray:
    """
    Apply a mask to an image with optional feathering.
    
    Args:
        image: Input image (BGR)
        mask: Binary or gradient mask
        feather: Feathering radius for smooth edges
        
    Returns:
        Masked image (sky portion only, ground is black)
    """
    # Feather the mask if requested
    if feather > 0:
        mask_float = mask.astype(np.float32) / 255.0
        mask_float = cv2.GaussianBlur(mask_float, (feather * 2 + 1, feather * 2 + 1), 0)
    else:
        mask_float = mask.astype(np.float32) / 255.0
    
    # Handle multi-channel images
    if len(image.shape) == 3:
        mask_float = mask_float[:, :, np.newaxis]
    
    # Apply mask
    result = (image.astype(np.float32) * mask_float)
    
    # Convert back to original dtype
    if image.dtype == np.uint8:
        return result.astype(np.uint8)
    elif image.dtype == np.uint16:
        return result.astype(np.uint16)
    else:
        return result
