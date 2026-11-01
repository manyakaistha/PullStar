"""
Star Trail Aligner - Synthetic Trail Generator

Creates interpolated "ghost" frames between real frames to simulate
longer exposure trails without requiring actual longer exposures.

This is the core of the trail extension feature. It works by:
1. Calculating the rotation between consecutive real frames
2. Generating intermediate rotations (ghost frames)
3. Applying optional sky mask to only rotate stars
4. Adding tail fade for natural appearance
"""

import cv2
import numpy as np
from typing import List, Tuple, Optional, Iterator
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import GHOST_FRAMES_PER_REAL, SYNTHETIC_FADE_FACTOR

from .rotation_engine import rotate_image
from .foreground_mask import segment_sky_ground, apply_mask_to_image
from core.cancellation import check_cancelled
from core.trail_effects import tail_opacity, validate_tail_settings, within_tail_angle


def iter_ghost_frames(
    current_frame: np.ndarray,
    current_rotation_angle: float,
    next_rotation_angle: float,
    rotation_center: Tuple[float, float],
    num_ghosts: int = GHOST_FRAMES_PER_REAL,
    fade_factor: float = SYNTHETIC_FADE_FACTOR,
    sky_mask: Optional[np.ndarray] = None,
    extension_factor: float = 1.0,
    cancel_check=None,
    tail_taper_strength: float = 0.0,
    tail_angle_threshold: float = 0.0,
) -> Iterator[np.ndarray]:
    """
    Generate interpolated ghost frames between two real frames.
    
    These ghost frames extend the apparent trail length by simulating
    what stars would look like at intermediate time points.
    
    Args:
        current_frame: Current aligned frame (should already be warped)
        current_rotation_angle: Cumulative rotation angle at current frame
        next_rotation_angle: Cumulative rotation angle at next frame
        rotation_center: (x, y) center of rotation (Polaris position)
        num_ghosts: Number of ghost frames to generate between real frames
        fade_factor: How much to fade each ghost (0=none, 1=full)
        sky_mask: Optional mask to only rotate sky portion (255=sky, 0=ground)
        extension_factor: Overall extension multiplier for adjusting ghost count
        tail_taper_strength: Additional fade applied toward a synthetic tail end.
        tail_angle_threshold: Maximum synthetic angular offset in degrees; zero disables it.
        
    Returns:
        List of ghost frame images (same shape/dtype as input)
    """
    tail_taper_strength, tail_angle_threshold = validate_tail_settings(
        tail_taper_strength, tail_angle_threshold
    )
    if num_ghosts < 1 or abs(next_rotation_angle - current_rotation_angle) < 0.001:
        return []
    
    # Adjust ghost count based on extension factor
    adjusted_num_ghosts = max(1, int(num_ghosts * (extension_factor - 1.0)))
    
    if adjusted_num_ghosts < 1:
        return []
    
    angle_delta = next_rotation_angle - current_rotation_angle
    
    # Prepare the frame for rotation
    if sky_mask is not None:
        # Only rotate the sky portion
        frame_to_rotate = apply_mask_to_image(current_frame, sky_mask)
    else:
        frame_to_rotate = current_frame
    
    # Generate ghost frames at interpolated positions
    for i in range(adjusted_num_ghosts):
        check_cancelled(cancel_check)
        # Calculate interpolation factor (0 to 1)
        alpha = (i + 1) / (adjusted_num_ghosts + 1)
        
        # Calculate the ghost's rotation angle relative to current frame
        ghost_rotation = alpha * angle_delta
        if not within_tail_angle(ghost_rotation, tail_angle_threshold):
            continue
        
        # Rotate the frame
        ghost = rotate_image(
            frame_to_rotate,
            ghost_rotation,
            rotation_center,
            use_phase=True  # Use phase rotation for sharpness
        )
        
        # Apply fade to create natural tail appearance
        # Later ghosts (further in time) are fainter
        brightness_factor = (1.0 - (alpha * fade_factor)) * tail_opacity(
            ghost_rotation,
            tail_angle_threshold if tail_angle_threshold > 0 else abs(angle_delta),
            tail_taper_strength,
        )
        ghost = (ghost.astype(np.float32) * brightness_factor)
        
        # Convert back to original dtype
        if current_frame.dtype == np.uint8:
            ghost = np.clip(ghost, 0, 255).astype(np.uint8)
        elif current_frame.dtype == np.uint16:
            ghost = np.clip(ghost, 0, 65535).astype(np.uint16)
        else:
            ghost = ghost.astype(current_frame.dtype)
        
        yield ghost


def generate_ghost_frames(
    current_frame: np.ndarray, current_rotation_angle: float, next_rotation_angle: float,
    rotation_center: Tuple[float, float], num_ghosts: int = GHOST_FRAMES_PER_REAL,
    fade_factor: float = SYNTHETIC_FADE_FACTOR, sky_mask: Optional[np.ndarray] = None,
    extension_factor: float = 1.0, cancel_check=None,
    tail_taper_strength: float = 0.0, tail_angle_threshold: float = 0.0,
) -> List[np.ndarray]:
    """Compatibility list API; render pipelines consume iter_ghost_frames directly."""
    return list(iter_ghost_frames(current_frame, current_rotation_angle, next_rotation_angle,
                                  rotation_center, num_ghosts, fade_factor, sky_mask,
                                  extension_factor, cancel_check,
                                  tail_taper_strength, tail_angle_threshold))


def extend_trails(
    aligned_frames: List[np.ndarray],
    rotation_angles: List[float],
    rotation_center: Tuple[float, float],
    extension_factor: float = 2.0,
    use_foreground_mask: bool = True,
    progress_callback=None
) -> np.ndarray:
    """
    Extend star trails by generating and accumulating ghost frames.
    
    This is a high-level function that processes all frames and returns
    a single extended trail image.
    
    Args:
        aligned_frames: List of aligned frame images
        rotation_angles: List of cumulative rotation angles (one per frame)
        rotation_center: (x, y) center of rotation
        extension_factor: Trail length multiplier (1.0=original, 2.0=double)
        use_foreground_mask: Whether to protect foreground from rotation
        progress_callback: Optional callable(frame_index, total_frames)
        
    Returns:
        Accumulated trail image with extended trails
    """
    if len(aligned_frames) == 0:
        raise ValueError("No frames provided")
    
    if len(rotation_angles) != len(aligned_frames):
        raise ValueError("Rotation angles count must match frames count")
    
    # Initialize accumulator
    h, w = aligned_frames[0].shape[:2]
    channels = 3 if len(aligned_frames[0].shape) == 3 else 1
    accumulator = np.zeros((h, w, channels) if channels > 1 else (h, w), dtype=np.float64)
    
    # Create foreground mask from first frame if requested
    sky_mask = None
    if use_foreground_mask:
        sky_mask = segment_sky_ground(aligned_frames[0])
    
    # Calculate ghost frames per real frame based on extension
    ghosts_per_frame = int((extension_factor - 1.0) * GHOST_FRAMES_PER_REAL)
    
    total = len(aligned_frames)
    
    for i, frame in enumerate(aligned_frames):
        if progress_callback:
            progress_callback(i, total)
        
        # Add real frame to accumulator (lighten blend)
        frame_float = frame.astype(np.float64)
        np.maximum(accumulator, frame_float, out=accumulator)
        
        # Generate ghost frames if not the last frame
        if i < len(aligned_frames) - 1 and extension_factor > 1.0:
            current_angle = rotation_angles[i]
            next_angle = rotation_angles[i + 1]
            
            ghosts = generate_ghost_frames(
                frame,
                current_angle,
                next_angle,
                rotation_center,
                num_ghosts=ghosts_per_frame,
                sky_mask=sky_mask,
                extension_factor=extension_factor
            )
            
            # Add ghost frames to accumulator
            for ghost in ghosts:
                ghost_float = ghost.astype(np.float64)
                np.maximum(accumulator, ghost_float, out=accumulator)
    
    # Convert to original dtype
    if aligned_frames[0].dtype == np.uint8:
        return np.clip(accumulator, 0, 255).astype(np.uint8)
    elif aligned_frames[0].dtype == np.uint16:
        return np.clip(accumulator, 0, 65535).astype(np.uint16)
    else:
        return accumulator.astype(aligned_frames[0].dtype)


def calculate_extension_rotation_angles(
    tracking_results,
    reference_polaris: Tuple[float, float]
) -> List[float]:
    """
    Calculate cumulative rotation angles from tracking results.
    
    Uses the Polaris position as the rotation center and calculates
    how much each frame has rotated relative to the reference frame.
    
    Args:
        tracking_results: List of FrameTracking from tracker module
        reference_polaris: (x, y) reference Polaris position (typically frame 0)
        
    Returns:
        List of cumulative rotation angles in degrees
    """
    if len(tracking_results) == 0:
        return []
    
    angles = [0.0]  # First frame has 0 rotation
    
    for i in range(1, len(tracking_results)):
        prev_result = tracking_results[i - 1]
        curr_result = tracking_results[i]
        
        # Get Polaris positions
        prev_polaris = prev_result.polaris.centroid
        curr_polaris = curr_result.polaris.centroid
        
        if prev_polaris and curr_polaris:
            # If second star tracking is available, use it for rotation
            if prev_result.second_star and curr_result.second_star:
                prev_star2 = prev_result.second_star.centroid
                curr_star2 = curr_result.second_star.centroid
                
                if prev_star2 and curr_star2:
                    # Calculate angle change using second star position
                    # relative to Polaris (rotation center)
                    prev_angle = np.arctan2(
                        prev_star2[1] - prev_polaris[1],
                        prev_star2[0] - prev_polaris[0]
                    )
                    curr_angle = np.arctan2(
                        curr_star2[1] - curr_polaris[1],
                        curr_star2[0] - curr_polaris[0]
                    )
                    
                    delta_angle = np.degrees(curr_angle - prev_angle)
                    
                    # Normalize to [-180, 180]
                    while delta_angle > 180:
                        delta_angle -= 360
                    while delta_angle < -180:
                        delta_angle += 360
                    
                    angles.append(angles[-1] + delta_angle)
                else:
                    angles.append(angles[-1])
            else:
                # No second star, estimate from time or just use 0
                # Could estimate ~0.004 deg/sec (Earth rotation rate)
                angles.append(angles[-1])
        else:
            angles.append(angles[-1])
    
    return angles


def estimate_earth_rotation_angle(
    elapsed_seconds: float,
    latitude: float = 45.0
) -> float:
    """
    Estimate the apparent rotation angle due to Earth's rotation.
    
    The apparent rotation rate depends on latitude:
    - At the pole, full 360°/day
    - At the equator, 0° (trails are straight lines)
    
    Args:
        elapsed_seconds: Time elapsed since reference frame
        latitude: Observer latitude in degrees
        
    Returns:
        Estimated rotation angle in degrees
    """
    # Earth rotates 360° in 23h 56m 4s (sidereal day)
    sidereal_day_seconds = 86164.1
    
    # Full rotation rate
    degrees_per_second = 360.0 / sidereal_day_seconds
    
    # Adjust for latitude (apparent rate = full rate * sin(latitude))
    apparent_rate = degrees_per_second * np.sin(np.radians(latitude))
    
    return elapsed_seconds * apparent_rate
