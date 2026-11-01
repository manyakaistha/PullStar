"""
Star Trail Aligner - Timeline Scheduler

The brain of the render pipeline. Generates a unified render schedule
that handles real frames, gap fills, and extensions uniformly.

This decouples "Input Files" from "Output Frames" - the video engine
just processes the linear schedule without knowing if a frame is real
or synthetic.
"""

from dataclasses import dataclass
from enum import IntEnum
from typing import List, Optional, Tuple
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np


class RenderActionType(IntEnum):
    """Types of actions in the render schedule."""
    REAL = 0        # Process actual image file
    GAP_FILL = 1    # Synthesize frame to fill timestamp gap
    EXTENSION = 2   # Extrapolate beyond last real frame


@dataclass
class RenderAction:
    """
    A single action in the render schedule.
    
    Attributes:
        action_type: Type of action (REAL, GAP_FILL, EXTENSION)
        source_index: Index of the source image file (for REAL, or source for synthesis)
        step_offset: For synthetic frames, the offset from source (e.g., 1 means one step ahead)
        timestamp: Calculated timestamp for this frame
        rotation_angle: Rotation angle relative to reference (filled during alignment)
    """
    action_type: RenderActionType
    source_index: int
    step_offset: int = 0
    timestamp: Optional[datetime] = None
    rotation_angle: float = 0.0
    
    @property
    def is_real(self) -> bool:
        return self.action_type == RenderActionType.REAL
    
    @property
    def is_synthetic(self) -> bool:
        return self.action_type in (RenderActionType.GAP_FILL, RenderActionType.EXTENSION)


@dataclass
class ScheduleStats:
    """Statistics about the generated schedule."""
    total_frames: int
    real_frames: int
    gap_fill_frames: int
    extension_frames: int
    gaps_detected: int
    median_interval_seconds: float
    total_duration_seconds: float
    effective_duration_seconds: float


def calculate_median_interval(timestamps: List[datetime]) -> float:
    """
    Calculate the median interval between consecutive timestamps.
    
    Args:
        timestamps: List of datetime objects, must be sorted
        
    Returns:
        Median interval in seconds
    """
    if len(timestamps) < 2:
        return 30.0  # Default to 30 seconds
    
    intervals = []
    for i in range(len(timestamps) - 1):
        delta = (timestamps[i + 1] - timestamps[i]).total_seconds()
        if delta > 0:  # Ignore zero or negative intervals
            intervals.append(delta)
    
    if not intervals:
        return 30.0
    
    return float(np.median(intervals))


def detect_gaps(
    timestamps: List[datetime],
    median_interval: float,
    gap_threshold_multiplier: float = 1.5
) -> List[Tuple[int, int, int]]:
    """
    Detect gaps in the timestamp sequence.
    
    Args:
        timestamps: Sorted list of timestamps
        median_interval: Calculated median interval in seconds
        gap_threshold_multiplier: Gap is detected if delta > threshold * median_interval
        
    Returns:
        List of (gap_after_index, missing_frame_count, gap_duration_seconds)
    """
    gaps = []
    threshold = median_interval * gap_threshold_multiplier
    
    for i in range(len(timestamps) - 1):
        delta = (timestamps[i + 1] - timestamps[i]).total_seconds()
        if delta > threshold:
            # Calculate how many frames are missing
            missing_count = max(1, int(round(delta / median_interval)) - 1)
            gaps.append((i, missing_count, delta))
    
    return gaps


def generate_schedule(
    file_list: List[Path],
    timestamps: List[datetime],
    extension_factor: float = 1.0,
    fill_gaps: bool = True,
    gap_threshold_multiplier: float = 1.5
) -> Tuple[List[RenderAction], ScheduleStats]:
    """
    Generate a complete render schedule from input files.
    
    This is the main entry point for the scheduler.
    
    Args:
        file_list: List of image file paths (will be sorted by timestamp)
        timestamps: Corresponding timestamps for each file
        extension_factor: Trail extension multiplier (1.0 = no extension, 2.0 = double)
        fill_gaps: Whether to fill detected gaps with synthetic frames
        gap_threshold_multiplier: Threshold for gap detection (1.5 = gap if > 1.5x median)
        
    Returns:
        Tuple of (schedule, stats)
    """
    if len(file_list) != len(timestamps):
        raise ValueError("file_list and timestamps must have same length")
    
    if len(file_list) == 0:
        raise ValueError("file_list cannot be empty")
    
    # Sort by timestamp
    sorted_indices = np.argsort([t.timestamp() for t in timestamps])
    sorted_timestamps = [timestamps[i] for i in sorted_indices]
    
    # Calculate median interval
    median_interval = calculate_median_interval(sorted_timestamps)
    
    # Build schedule
    schedule: List[RenderAction] = []
    gaps_detected = 0
    gap_fill_count = 0
    
    for idx, original_idx in enumerate(sorted_indices):
        # Add real frame
        schedule.append(RenderAction(
            action_type=RenderActionType.REAL,
            source_index=int(original_idx),
            step_offset=0,
            timestamp=sorted_timestamps[idx]
        ))
        
        # Check for gap to next frame
        if fill_gaps and idx < len(sorted_indices) - 1:
            delta = (sorted_timestamps[idx + 1] - sorted_timestamps[idx]).total_seconds()
            threshold = median_interval * gap_threshold_multiplier
            
            if delta > threshold:
                gaps_detected += 1
                missing_count = max(1, int(round(delta / median_interval)) - 1)
                
                # Insert gap fill frames
                for k in range(missing_count):
                    alpha = (k + 1) / (missing_count + 1)
                    synthetic_time = sorted_timestamps[idx] + timedelta(
                        seconds=alpha * delta
                    )
                    schedule.append(RenderAction(
                        action_type=RenderActionType.GAP_FILL,
                        source_index=int(original_idx),  # Use previous frame as source
                        step_offset=k + 1,
                        timestamp=synthetic_time
                    ))
                    gap_fill_count += 1
    
    # Handle extension (extrapolation beyond last frame)
    extension_count = 0
    if extension_factor > 1.0 and len(schedule) > 0:
        # Count real frames for extension calculation
        real_frame_count = sum(1 for a in schedule if a.is_real)
        
        # Calculate how many extension frames needed
        total_target = int(real_frame_count * extension_factor)
        needed_extension = total_target - len(schedule)
        
        if needed_extension > 0:
            last_real_idx = int(sorted_indices[-1])
            last_timestamp = sorted_timestamps[-1]
            
            for k in range(needed_extension):
                synthetic_time = last_timestamp + timedelta(
                    seconds=(k + 1) * median_interval
                )
                schedule.append(RenderAction(
                    action_type=RenderActionType.EXTENSION,
                    source_index=last_real_idx,
                    step_offset=k + 1,
                    timestamp=synthetic_time
                ))
                extension_count += 1
    
    # Calculate statistics
    real_count = sum(1 for a in schedule if a.action_type == RenderActionType.REAL)
    
    if len(sorted_timestamps) >= 2:
        original_duration = (sorted_timestamps[-1] - sorted_timestamps[0]).total_seconds()
    else:
        original_duration = 0.0
    
    if len(schedule) >= 2 and schedule[-1].timestamp and schedule[0].timestamp:
        effective_duration = (schedule[-1].timestamp - schedule[0].timestamp).total_seconds()
    else:
        effective_duration = original_duration
    
    stats = ScheduleStats(
        total_frames=len(schedule),
        real_frames=real_count,
        gap_fill_frames=gap_fill_count,
        extension_frames=extension_count,
        gaps_detected=gaps_detected,
        median_interval_seconds=median_interval,
        total_duration_seconds=original_duration,
        effective_duration_seconds=effective_duration
    )
    
    return schedule, stats


def print_schedule_summary(stats: ScheduleStats) -> None:
    """Print a human-readable summary of the schedule."""
    print(f"\n{'='*60}")
    print("RENDER SCHEDULE SUMMARY")
    print(f"{'='*60}")
    print(f"  Total frames to render: {stats.total_frames}")
    print(f"    • Real frames: {stats.real_frames}")
    if stats.gap_fill_frames > 0:
        print(f"    • Gap-fill frames: {stats.gap_fill_frames} ({stats.gaps_detected} gaps detected)")
    if stats.extension_frames > 0:
        print(f"    • Extension frames: {stats.extension_frames}")
    print(f"  Median interval: {stats.median_interval_seconds:.1f}s")
    print(f"  Original duration: {stats.total_duration_seconds / 60:.1f} min")
    if stats.effective_duration_seconds != stats.total_duration_seconds:
        print(f"  Effective duration: {stats.effective_duration_seconds / 60:.1f} min")
    print(f"{'='*60}\n")


def calculate_rotation_speed(rotation_angles: List[float], num_frames_for_average: int = 20) -> float:
    """
    Calculate the median rotation speed (degrees per frame) from alignment data.
    
    Uses the last N frames for stability, filtering out outliers.
    
    Args:
        rotation_angles: List of cumulative rotation angles for each frame
        num_frames_for_average: How many recent frames to use for averaging
        
    Returns:
        Median rotation speed in degrees per frame
    """
    if len(rotation_angles) < 2:
        # Fallback: Earth rotates 360° in 24h = 0.25°/min
        # Assuming 30s per frame = 0.125°/frame
        return 0.125
    
    # Calculate per-frame rotation deltas
    deltas = []
    start_idx = max(0, len(rotation_angles) - num_frames_for_average)
    
    for i in range(start_idx + 1, len(rotation_angles)):
        delta = rotation_angles[i] - rotation_angles[i - 1]
        if abs(delta) < 5.0:  # Filter outliers (> 5° per frame is unrealistic)
            deltas.append(delta)
    
    if not deltas:
        return 0.125  # Default fallback
    
    return float(np.median(deltas))


@dataclass
class ExtensionSchedule:
    """
    Schedule specifically for trail extension (extrapolation).
    
    Attributes:
        num_real_frames: Count of real input frames
        num_extension_frames: Count of synthetic future frames
        rotation_speed: Degrees per frame (median)
        extension_rotation_angles: List of cumulative rotation offsets for each extension frame
    """
    num_real_frames: int
    num_extension_frames: int
    rotation_speed: float
    extension_rotation_angles: List[float]


def generate_extension_schedule(
    num_real_frames: int,
    rotation_angles: List[float],
    extension_factor: float
) -> ExtensionSchedule:
    """
    Generate a schedule for trail extension (future extrapolation).
    
    This creates the synthetic future frames needed to extend trails.
    
    Example:
        - 240 real frames (covering 30° rotation)
        - extension_factor = 2.0
        - Result: 240 extension frames (covering additional 30° = 60° total)
    
    Args:
        num_real_frames: Number of real input frames
        rotation_angles: Cumulative rotation angles for each real frame
        extension_factor: Target multiplier (2.0 = double the trail length)
        
    Returns:
        ExtensionSchedule with rotation angles for each synthetic frame
    """
    # Calculate rotation speed from recent frames
    rotation_speed = calculate_rotation_speed(rotation_angles, num_frames_for_average=20)
    
    # Calculate how many extension frames we need
    # extension_factor of 2.0 means we need as many extension frames as real frames
    target_total = int(num_real_frames * extension_factor)
    num_extension = max(0, target_total - num_real_frames)
    
    # Generate rotation angles for each extension frame
    # These are OFFSETS from the last real frame
    extension_angles = []
    for k in range(num_extension):
        # Cumulative rotation beyond the last real frame
        angle_offset = (k + 1) * rotation_speed
        extension_angles.append(angle_offset)
    
    return ExtensionSchedule(
        num_real_frames=num_real_frames,
        num_extension_frames=num_extension,
        rotation_speed=rotation_speed,
        extension_rotation_angles=extension_angles
    )

