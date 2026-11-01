"""
Star Trail Aligner - Global Configuration

This module contains all configurable parameters and constants used throughout
the star trail alignment process. Modify these values to fine-tune the algorithm
for different shooting conditions.
"""

from pathlib import Path
from typing import Tuple

# =============================================================================
# TRACKING PARAMETERS
# =============================================================================

# Size of the search window (in pixels) around the tracked star
# A 100x100 box provides enough margin for typical tripod wobble
SEARCH_WINDOW_SIZE: int = 100

# Maximum allowed jump between frames (in pixels)
# If a star moves more than this in one frame, it's flagged as a tracking error
# Based on: 30-second exposures should not have >50px drift from wind alone
MAX_JUMP_THRESHOLD: float = 50.0

# Percentile threshold for star detection
# Only consider pixels brighter than this percentile in the ROI
# 99.5 means we look at the top 0.5% brightest pixels
STAR_THRESHOLD_PERCENTILE: float = 99.5

# Minimum blob area (in pixels) to be considered a valid star detection
# Filters out hot pixels and noise
MIN_BLOB_AREA: int = 5

# Maximum blob area - stars should be point sources, not large
MAX_BLOB_AREA: int = 500

# =============================================================================
# KALMAN FILTER PARAMETERS
# =============================================================================

# Process noise - accounts for wind-induced camera acceleration
# Higher values = more responsive to sudden movements, but noisier
KALMAN_PROCESS_NOISE: float = 0.01

# Measurement noise - centroid detection uncertainty in pixels
# Higher values = smoother tracking, but slower response
KALMAN_MEASUREMENT_NOISE: float = 2.0

# Minimum confidence threshold for accepting a centroid measurement
# Below this, fallback to previous position (e.g., cloud covering star)
KALMAN_MIN_CONFIDENCE: float = 0.3

# Enable Kalman filtering (set to False for legacy behavior)
USE_KALMAN_FILTER: bool = True

# =============================================================================
# IMAGE PROCESSING PARAMETERS
# =============================================================================

# Gaussian blur parameters for noise reduction
GAUSSIAN_BLUR_SIZE: int = 5  # Kernel size (must be odd)
GAUSSIAN_BLUR_SIGMA: float = 1.0

# Chroma noise reduction strength (kernel size for LAB channel blur)
# Must be odd. Higher values remove more color splotches but may bleed colors.
CHROMA_NOISE_REDUCTION_STRENGTH: int = 15

# Interpolation method for warping
# INTER_LANCZOS4 provides highest quality for star sharpness
# Other options: cv2.INTER_LINEAR, cv2.INTER_CUBIC
WARP_INTERPOLATION: int = 4  # cv2.INTER_LANCZOS4

# =============================================================================
# SYNTHETIC TRAIL EXTENSION
# =============================================================================

# Number of ghost frames to generate between each real frame
# Higher = smoother extended trails, but slower processing
GHOST_FRAMES_PER_REAL: int = 10

# Fade factor for synthetic trail tails (0.0 = no fade, 1.0 = full fade)
# Slight fade makes trails look more natural
SYNTHETIC_FADE_FACTOR: float = 0.2

# Use phase-based (FFT) rotation for synthetic frames
# True = sharper stars, False = faster processing
USE_PHASE_ROTATION: bool = True

# Maximum angle for phase-based rotation (degrees)
# Beyond this, falls back to standard rotation for stability
PHASE_ROTATION_MAX_ANGLE: float = 5.0

# =============================================================================
# VIDEO ENCODING
# =============================================================================

# Output video frame rate
VIDEO_FPS: int = 30

# Video codec (use 'mp4v' for maximum compatibility)
# Other options: 'XVID', 'avc1' (may require additional codecs)
VIDEO_CODEC: str = 'mp4v'

# Gamma value for tone-mapping video frames
# Lower values (0.3-0.5) enhance faint trails, higher (0.7-1.0) preserve highlights
TONE_MAP_GAMMA: float = 0.5

# Blending
DEFAULT_BLEND_MODE: str = "lighten"  # 'lighten' (np.maximum) or 'add' (np.add)

# Hardware acceleration
VIDEOTOOLBOX_ENABLED: bool = True  # Use macOS VideoToolbox when available

# =============================================================================
# CHECKPOINT & RESUME
# =============================================================================

# Save checkpoint every N frames during processing
CHECKPOINT_INTERVAL: int = 20

# Default directory for checkpoint files
CHECKPOINT_DIR: str = './checkpoints'

# =============================================================================
# FILE HANDLING
# =============================================================================

# Supported image file extensions
RAW_EXTENSIONS: Tuple[str, ...] = (
    '.nef',   # Nikon
    '.cr2',   # Canon (older)
    '.cr3',   # Canon (newer)
    '.arw',   # Sony
    '.dng',   # Adobe DNG
    '.orf',   # Olympus
    '.rw2',   # Panasonic
    '.raf',   # Fujifilm
    '.pef',   # Pentax
)

STANDARD_EXTENSIONS: Tuple[str, ...] = (
    '.jpg',
    '.jpeg',
    '.tif',
    '.tiff',
    '.png',
)

# All supported extensions
SUPPORTED_EXTENSIONS: Tuple[str, ...] = RAW_EXTENSIONS + STANDARD_EXTENSIONS

# Default output filename
DEFAULT_OUTPUT_FILENAME: str = "aligned_star_trails.tiff"

# Default video output filename
DEFAULT_VIDEO_FILENAME: str = "trail_lapse.mp4"

# =============================================================================
# COLOR SPACE
# =============================================================================

# We use BGR throughout (OpenCV native) for simplicity
# Conversion to RGB happens only at final output if needed
COLOR_SPACE: str = "BGR"

# =============================================================================
# PROGRESS & LOGGING
# =============================================================================

# Enable verbose logging
VERBOSE: bool = True

# Progress bar format
PROGRESS_BAR_FORMAT: str = "{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]"

