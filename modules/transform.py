"""
Star Trail Aligner - Transform Module

This module handles geometric transformations:
- Translation-only transform (single star mode)
- Rotation + translation transform (two-star mode) [Phase 8]
- Common crop region calculation
- Image warping with high-quality interpolation
"""

import cv2
import numpy as np
from pathlib import Path
from typing import Tuple, List, Optional, Dict
from dataclasses import dataclass
from math import ceil, floor

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import WARP_INTERPOLATION, VERBOSE


@dataclass
class TransformData:
    """Data for a single frame's transformation."""
    frame_index: int
    dx: float  # Translation in X
    dy: float  # Translation in Y
    rotation: float  # Rotation angle in radians (0 for translation-only mode)
    matrix: np.ndarray  # 2x3 affine transformation matrix
    is_valid: bool  # Whether this is a valid computed transform or a fallback


@dataclass
class CropRegion:
    """Defines the common crop region for all aligned frames."""
    x_start: int
    x_end: int
    y_start: int
    y_end: int
    width: int
    height: int


class WarpWorkspace:
    """Reusable scratch storage for the CPU crop warp.

    Siril's stacker keeps per-thread image and coordinate buffers alive while
    it processes blocks. The same idea avoids allocating multi-megabyte remap
    grids for every exposure here. A workspace is owned by one worker because
    OpenCV writes into the arrays during ``remap``.
    """

    def __init__(self, strip_height: int = 256):
        self.strip_height = max(32, int(strip_height))
        self.width = 0
        self.rows = 0
        self.sx = self.sy = None
        self.coordinates = self.fractions = None

    def ensure(self, width: int, rows: int) -> None:
        width = int(width)
        rows = int(rows)
        if width <= self.width and rows <= self.rows:
            return
        self.width = max(self.width, width)
        self.rows = max(self.rows, rows)
        self.sx = np.empty((self.rows, self.width), dtype=np.int32)
        self.sy = np.empty((self.rows, self.width), dtype=np.int32)
        self.coordinates = np.empty((self.rows, self.width, 2), dtype=np.int16)
        self.fractions = np.empty((self.rows, self.width), dtype=np.uint16)


def calculate_translation_matrix(
    reference_pos: Tuple[float, float],
    current_pos: Tuple[float, float]
) -> np.ndarray:
    """
    Calculate a translation-only affine matrix.
    
    This matrix, when applied to an image, will shift it so that
    the current_pos ends up at the reference_pos.
    
    Args:
        reference_pos: (x, y) target position (from frame 0)
        current_pos: (x, y) current star position
        
    Returns:
        2x3 affine transformation matrix
    """
    dx = reference_pos[0] - current_pos[0]
    dy = reference_pos[1] - current_pos[1]
    
    # Affine matrix for translation:
    # [1, 0, dx]
    # [0, 1, dy]
    matrix = np.array([
        [1.0, 0.0, dx],
        [0.0, 1.0, dy]
    ], dtype=np.float64)
    
    return matrix


def calculate_rotation_matrix(
    ref_polaris: Tuple[float, float],
    ref_star2: Tuple[float, float],
    curr_polaris: Tuple[float, float],
    curr_star2: Tuple[float, float]
) -> np.ndarray:
    """
    Calculate a rotation + translation affine matrix.
    
    Uses two stars to compute both the rotation angle and translation
    needed to align the current frame with the reference.
    
    Note: This is for Phase 8 - rotation correction. Currently placeholder.
    
    Args:
        ref_polaris: Reference Polaris position
        ref_star2: Reference second star position
        curr_polaris: Current frame's Polaris position
        curr_star2: Current frame's second star position
        
    Returns:
        2x3 affine transformation matrix
    """
    # Calculate vectors from Polaris to second star
    ref_vector = np.array([
        ref_star2[0] - ref_polaris[0],
        ref_star2[1] - ref_polaris[1]
    ])
    curr_vector = np.array([
        curr_star2[0] - curr_polaris[0],
        curr_star2[1] - curr_polaris[1]
    ])
    
    # Calculate rotation angle
    ref_angle = np.arctan2(ref_vector[1], ref_vector[0])
    curr_angle = np.arctan2(curr_vector[1], curr_vector[0])
    rotation = ref_angle - curr_angle
    
    # Build rotation matrix around Polaris
    cos_r = np.cos(rotation)
    sin_r = np.sin(rotation)
    
    # First: translate so curr_polaris is at origin
    # Second: rotate
    # Third: translate so result matches ref_polaris
    
    # Combined transformation:
    # The point curr_polaris should end up at ref_polaris
    dx = ref_polaris[0] - (cos_r * curr_polaris[0] - sin_r * curr_polaris[1])
    dy = ref_polaris[1] - (sin_r * curr_polaris[0] + cos_r * curr_polaris[1])
    
    matrix = np.array([
        [cos_r, -sin_r, dx],
        [sin_r, cos_r, dy]
    ], dtype=np.float64)
    
    return matrix


def calculate_transforms_from_tracking(
    tracking_results: List,  # List[FrameTracking] - imported type
    use_rotation: bool = False
) -> List[TransformData]:
    """
    Calculate transformation matrices from tracking results.
    
    Args:
        tracking_results: List of FrameTracking objects from tracker module
        use_rotation: Whether to use rotation correction (requires second star)
        
    Returns:
        List of TransformData, one per frame
    """
    if not tracking_results:
        return []
    
    transforms = []
    
    # Reference position from frame 0
    ref_polaris = tracking_results[0].polaris.centroid
    ref_star2 = None
    if use_rotation and tracking_results[0].second_star:
        ref_star2 = tracking_results[0].second_star.centroid
    
    for tracking in tracking_results:
        curr_polaris = tracking.polaris.centroid
        is_valid = tracking.polaris.centroid is not None
        
        if not is_valid:
            # Create identity transform as fallback
            matrix = np.array([
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0]
            ], dtype=np.float64)
            transforms.append(TransformData(
                frame_index=tracking.frame_index,
                dx=0.0,
                dy=0.0,
                rotation=0.0,
                matrix=matrix,
                is_valid=False
            ))
            continue
        
        if use_rotation and ref_star2 and tracking.second_star and tracking.second_star.centroid:
            # Rotation + translation mode
            curr_star2 = tracking.second_star.centroid
            matrix = calculate_rotation_matrix(
                ref_polaris, ref_star2,
                curr_polaris, curr_star2
            )
            
            # Extract rotation angle from matrix
            rotation = np.arctan2(matrix[1, 0], matrix[0, 0])
            dx = matrix[0, 2]
            dy = matrix[1, 2]
        else:
            # Translation-only mode
            matrix = calculate_translation_matrix(ref_polaris, curr_polaris)
            dx = matrix[0, 2]
            dy = matrix[1, 2]
            rotation = 0.0
        
        transforms.append(TransformData(
            frame_index=tracking.frame_index,
            dx=dx,
            dy=dy,
            rotation=rotation,
            matrix=matrix,
            is_valid=True
        ))
    
    return transforms


def calculate_common_crop(
    transforms: List[TransformData],
    image_width: int,
    image_height: int
) -> CropRegion:
    """
    Calculate the common crop region that contains no black borders.
    
    After applying different translations to each frame, the aligned images
    will have different "valid" regions. This function finds the intersection
    of all valid regions.
    
    Args:
        transforms: List of TransformData with dx, dy values
        image_width: Width of source images
        image_height: Height of source images
        
    Returns:
        CropRegion defining the safe crop area
    """
    if not transforms:
        return CropRegion(
            x_start=0, x_end=image_width,
            y_start=0, y_end=image_height,
            width=image_width, height=image_height
        )
    
    # Collect all dx and dy values
    dx_values = [t.dx for t in transforms if t.is_valid]
    dy_values = [t.dy for t in transforms if t.is_valid]
    
    if not dx_values:
        dx_values = [0]
    if not dy_values:
        dy_values = [0]
    
    # Find extremes
    min_dx = min(dx_values)  # Biggest shift left (negative)
    max_dx = max(dx_values)  # Biggest shift right (positive)
    min_dy = min(dy_values)  # Biggest shift up (negative)
    max_dy = max(dy_values)  # Biggest shift down (positive)
    
    if VERBOSE:
        print(f"Transform range: dx=[{min_dx:.1f}, {max_dx:.1f}], dy=[{min_dy:.1f}, {max_dy:.1f}]")
    
    # Calculate crop bounds
    # When an image is shifted RIGHT by dx pixels, we need to crop
    # dx pixels from the LEFT to avoid black border on the left.
    # When shifted LEFT (negative dx), we need to crop from the RIGHT.
    
    # x_start: must accommodate the maximum rightward shift
    x_start = int(ceil(max(0, max_dx)))
    
    # x_end: must accommodate the maximum leftward shift
    x_end = int(floor(image_width + min(0, min_dx)))
    
    # Same logic for y
    y_start = int(ceil(max(0, max_dy)))
    y_end = int(floor(image_height + min(0, min_dy)))
    
    # Ensure valid dimensions
    x_start = max(0, x_start)
    x_end = min(image_width, x_end)
    y_start = max(0, y_start)
    y_end = min(image_height, y_end)
    
    # Ensure minimum dimensions
    if x_end <= x_start:
        x_start = 0
        x_end = image_width
    if y_end <= y_start:
        y_start = 0
        y_end = image_height
    
    width = x_end - x_start
    height = y_end - y_start
    
    if VERBOSE:
        print(f"Common crop region: ({x_start}, {y_start}) to ({x_end}, {y_end})")
        print(f"Output dimensions: {width}x{height}")
        print(f"Pixels cropped: {image_width - width}x (horizontal), {image_height - height}y (vertical)")
    
    return CropRegion(
        x_start=x_start,
        x_end=x_end,
        y_start=y_start,
        y_end=y_end,
        width=width,
        height=height
    )


def warp_image(
    image: np.ndarray,
    transform: TransformData,
    interpolation: int = WARP_INTERPOLATION
) -> np.ndarray:
    """
    Apply affine transformation to an image.
    
    Args:
        image: Input image array
        transform: TransformData with the affine matrix
        interpolation: OpenCV interpolation flag (default: LANCZOS4)
        
    Returns:
        Warped image with same dimensions as input
    """
    h, w = image.shape[:2]
    
    warped = cv2.warpAffine(
        image,
        transform.matrix,
        (w, h),
        flags=interpolation,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0
    )
    
    return warped


def crop_image(image: np.ndarray, crop: CropRegion) -> np.ndarray:
    """
    Crop an image to the specified region.
    
    Args:
        image: Input image array
        crop: CropRegion defining the crop bounds
        
    Returns:
        Cropped image
    """
    return image[crop.y_start:crop.y_end, crop.x_start:crop.x_end].copy()


def apply_transform_and_crop(
    image: np.ndarray,
    transform: TransformData,
    crop: CropRegion,
    interpolation: int = WARP_INTERPOLATION,
    workspace: Optional[WarpWorkspace] = None,
) -> np.ndarray:
    """
    Convenience function to warp and crop in one step.
    
    Args:
        image: Input image
        transform: TransformData with affine matrix
        crop: CropRegion for cropping
        interpolation: OpenCV interpolation flag
        
    Returns:
        Warped and cropped image
    """
    return warp_to_crop(image, transform.matrix, crop, interpolation, workspace=workspace)


def warp_to_crop(image, matrix, crop, interpolation=cv2.INTER_LANCZOS4,
                 cancel_check=None, workspace: Optional[WarpWorkspace] = None):
    """Render only the crop, retaining warpAffine's original fixed-point grid.

    Shifting an affine matrix changes where OpenCV rounds the x and y terms.
    Construct its 10-bit coordinates in the original destination space, then
    feed the same 1/32-pixel table indices to remap in bounded row strips.
    """
    from core.cancellation import check_cancelled
    check_cancelled(cancel_check)
    if (interpolation not in (cv2.INTER_LINEAR, cv2.INTER_CUBIC, cv2.INTER_LANCZOS4)
            or max(image.shape[:2]) >= 32767
            or not (0 <= crop.x_start < crop.x_end <= image.shape[1]
                    and 0 <= crop.y_start < crop.y_end <= image.shape[0])):
        full = cv2.warpAffine(image, matrix, (image.shape[1], image.shape[0]), flags=interpolation)
        return crop_image(full, crop)
    matrix = np.asarray(matrix, dtype=np.float64)

    # Most fixed-tripod sequences only need translation. For an exact integer
    # translation every destination pixel maps to one source pixel, so slicing
    # is both much faster and numerically identical to the Lanczos warp.
    linear_identity = np.allclose(matrix[:, :2], np.eye(2), rtol=0, atol=1e-10)
    tx, ty = matrix[0, 2], matrix[1, 2]
    integer_translation = (linear_identity and abs(tx - round(tx)) < 1e-7
                           and abs(ty - round(ty)) < 1e-7)
    if integer_translation:
        tx, ty = int(round(tx)), int(round(ty))
        output = np.zeros((crop.height, crop.width, *image.shape[2:]), dtype=image.dtype)
        src_x0, src_x1 = crop.x_start - tx, crop.x_end - tx
        src_y0, src_y1 = crop.y_start - ty, crop.y_end - ty
        dst_x0, dst_y0 = max(0, -src_x0), max(0, -src_y0)
        dst_x1 = crop.width - max(0, src_x1 - image.shape[1])
        dst_y1 = crop.height - max(0, src_y1 - image.shape[0])
        src_x0, src_y0 = max(0, src_x0), max(0, src_y0)
        src_x1, src_y1 = min(image.shape[1], src_x1), min(image.shape[0], src_y1)
        if src_x1 > src_x0 and src_y1 > src_y0 and dst_x1 > dst_x0 and dst_y1 > dst_y0:
            output[dst_y0:dst_y1, dst_x0:dst_x1] = image[src_y0:src_y1, src_x0:src_x1]
        return output

    inverse = cv2.invertAffineTransform(matrix)
    if workspace is None:
        workspace = WarpWorkspace()
    x = np.arange(crop.x_start, crop.x_end, dtype=np.float64)
    dx = np.rint(inverse[0, 0] * x * 1024).astype(np.int32)
    dy = np.rint(inverse[1, 0] * x * 1024).astype(np.int32)
    output = np.empty((crop.height, crop.width, *image.shape[2:]), dtype=image.dtype)
    # Larger strips amortize remap call setup while keeping coordinate scratch
    # bounded for wide camera frames and retaining cancellation checkpoints.
    strip_height = workspace.strip_height
    for start in range(0, crop.height, strip_height):
        check_cancelled(cancel_check)
        stop = min(start + strip_height, crop.height)
        y = np.arange(crop.y_start + start, crop.y_start + stop, dtype=np.float64)
        rx = np.rint((inverse[0, 1] * y + inverse[0, 2]) * 1024).astype(np.int32) + 16
        ry = np.rint((inverse[1, 1] * y + inverse[1, 2]) * 1024).astype(np.int32) + 16
        rows = stop - start
        workspace.ensure(crop.width, rows)
        sx = workspace.sx[:rows, :crop.width]
        sy = workspace.sy[:rows, :crop.width]
        np.add(dx[None, :], rx[:, None], out=sx)
        np.add(dy[None, :], ry[:, None], out=sy)
        sx >>= 5
        sy >>= 5
        coordinates = workspace.coordinates[:rows, :crop.width]
        coordinates[:, :, 0] = np.clip(sx >> 5, -32768, 32767)
        coordinates[:, :, 1] = np.clip(sy >> 5, -32768, 32767)
        fractions = workspace.fractions[:rows, :crop.width]
        fractions[:] = ((sy & 31) << 5) + (sx & 31)
        cv2.remap(image, coordinates, fractions, interpolation, dst=output[start:stop],
                  borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    check_cancelled(cancel_check)
    return output


def get_transform_statistics(transforms: List[TransformData]) -> Dict:
    """
    Calculate statistics about the transforms.
    
    Args:
        transforms: List of TransformData
        
    Returns:
        Dict with statistics
    """
    valid_transforms = [t for t in transforms if t.is_valid]
    
    if not valid_transforms:
        return {
            'total': len(transforms),
            'valid': 0,
            'invalid': len(transforms),
            'max_dx': 0,
            'max_dy': 0,
            'avg_dx': 0,
            'avg_dy': 0,
            'total_drift': 0,
            'total_rotation_deg': 0
        }
    
    dx_values = [abs(t.dx) for t in valid_transforms]
    dy_values = [abs(t.dy) for t in valid_transforms]
    rotation_values = [np.degrees(t.rotation) for t in valid_transforms]
    
    return {
        'total': len(transforms),
        'valid': len(valid_transforms),
        'invalid': len(transforms) - len(valid_transforms),
        'max_dx': max(dx_values),
        'max_dy': max(dy_values),
        'avg_dx': sum(dx_values) / len(dx_values),
        'avg_dy': sum(dy_values) / len(dy_values),
        'total_drift': np.sqrt(max(dx_values)**2 + max(dy_values)**2),
        'total_rotation_deg': sum(rotation_values)
    }


def get_cumulative_rotation_angles(transforms: List[TransformData]) -> List[float]:
    """
    Get cumulative rotation angles from transforms for synthetic extension.
    
    This is useful for the synthetic trail generator which needs to know
    the rotation angle at each frame relative to the first frame.
    
    Args:
        transforms: List of TransformData with rotation information
        
    Returns:
        List of cumulative rotation angles in degrees
    """
    angles = []
    cumulative = 0.0
    
    for i, transform in enumerate(transforms):
        if i == 0:
            angles.append(0.0)
        else:
            # The transform rotation is the angle needed to align TO reference
            # So cumulative rotation is the sum of all angles
            cumulative += np.degrees(transform.rotation)
            angles.append(cumulative)
    
    return angles


def estimate_rotation_from_translation(
    transforms: List[TransformData],
    polaris_position: Tuple[float, float],
    image_center: Tuple[float, float]
) -> List[float]:
    """
    Estimate rotation angles from translation data when rotation tracking isn't available.
    
    Uses the geometry of Polaris motion relative to image center to estimate
    the apparent rotation. This is less accurate than two-star tracking but
    can be useful for synthetic extension without a second star.
    
    Args:
        transforms: List of TransformData (translation only)
        polaris_position: Reference Polaris position
        image_center: Image center point
        
    Returns:
        List of estimated rotation angles in degrees
    """
    if not transforms:
        return []
    
    angles = [0.0]  # First frame is reference
    
    # Calculate the distance from Polaris to image center
    # This affects how much apparent rotation we see per pixel of motion
    px, py = polaris_position
    cx, cy = image_center
    radius = np.sqrt((px - cx)**2 + (py - cy)**2)
    
    if radius < 100:
        # Polaris is near image center, can't estimate rotation reliably
        return [0.0] * len(transforms)
    
    for i in range(1, len(transforms)):
        # Calculate the angular displacement based on translation
        dx = transforms[i].dx
        dy = transforms[i].dy
        
        # The apparent motion should be tangential to the rotation
        # Estimate angle from arc length / radius
        arc_length = np.sqrt(dx**2 + dy**2)
        angle_rad = arc_length / radius
        
        # Determine direction from cross product
        # Translation direction relative to radial direction from center
        radial = np.array([px - cx, py - cy])
        trans = np.array([dx, dy])
        cross = radial[0] * trans[1] - radial[1] * trans[0]
        
        if cross < 0:
            angle_rad = -angle_rad
        
        angles.append(angles[-1] + np.degrees(angle_rad))
    
    return angles

