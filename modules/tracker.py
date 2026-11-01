"""
Star Trail Aligner - Tracker Module

This module contains the core star tracking algorithm:
- Dynamic ROI (Region of Interest) extraction
- Gaussian blur preprocessing for noise reduction
- Adaptive thresholding for star detection
- Connected component analysis for blob detection
- Sub-pixel centroiding using image moments
- Kalman filtering for noise reduction and smooth tracking
- Failsafe handling for clouds, satellites, and tracking errors
"""

import cv2
import numpy as np
from pathlib import Path
from typing import Tuple, Optional, List, Dict
from dataclasses import dataclass
from enum import Enum

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    SEARCH_WINDOW_SIZE,
    MAX_JUMP_THRESHOLD,
    STAR_THRESHOLD_PERCENTILE,
    MIN_BLOB_AREA,
    MAX_BLOB_AREA,
    GAUSSIAN_BLUR_SIZE,
    GAUSSIAN_BLUR_SIGMA,
    VERBOSE,
    KALMAN_PROCESS_NOISE,
    KALMAN_MEASUREMENT_NOISE,
    KALMAN_MIN_CONFIDENCE,
    USE_KALMAN_FILTER,
)


class TrackingStatus(Enum):
    """Status of a tracking attempt."""
    SUCCESS = "success"
    STAR_NOT_FOUND = "star_not_found"
    MULTIPLE_CANDIDATES = "multiple_candidates"
    JUMP_TOO_LARGE = "jump_too_large"
    BRIGHTNESS_TOO_LOW = "brightness_too_low"
    USING_FALLBACK = "using_fallback"


class KalmanCentroidTracker:
    """
    Kalman filter for smooth centroid tracking across frames.
    
    Uses a constant velocity model to predict star positions and
    reject noisy measurements that violate physics.
    
    The state vector is [x, y, vx, vy] representing position and velocity.
    This helps smooth out jitter from wind-induced camera shake while
    still following real star motion.
    
    Works on CPU only - no GPU dependencies required.
    
    Example:
        >>> tracker = KalmanCentroidTracker()
        >>> tracker.initialize((100.0, 200.0))
        >>> predicted = tracker.predict()
        >>> filtered = tracker.update((101.5, 199.8))
    """
    
    def __init__(
        self,
        process_noise: float = KALMAN_PROCESS_NOISE,
        measurement_noise: float = KALMAN_MEASUREMENT_NOISE
    ):
        """
        Initialize Kalman filter.
        
        Args:
            process_noise: Variance of the process (camera shake from wind).
                          Higher values make filter more responsive to sudden movements.
            measurement_noise: Variance of centroid measurement (detection uncertainty).
                              Higher values make filter smoother but slower to respond.
        """
        # State transition matrix (constant velocity model)
        # State: [x, y, vx, vy]
        # x' = x + vx, y' = y + vy, vx' = vx, vy' = vy
        self.F = np.array([
            [1, 0, 1, 0],
            [0, 1, 0, 1],
            [0, 0, 1, 0],
            [0, 0, 0, 1]
        ], dtype=np.float64)
        
        # Process noise covariance
        # Accounts for random accelerations from wind
        self.Q = np.eye(4, dtype=np.float64) * process_noise
        
        # Measurement noise covariance
        # Accounts for centroid detection uncertainty
        self.R = np.eye(2, dtype=np.float64) * measurement_noise
        
        # Measurement matrix (we observe x, y only)
        self.H = np.array([
            [1, 0, 0, 0],
            [0, 1, 0, 0]
        ], dtype=np.float64)
        
        # Initial covariance (high uncertainty)
        self.P = np.eye(4, dtype=np.float64) * 10.0
        
        # State vector [x, y, vx, vy]
        self.X = None
        
        # Track whether filter is initialized
        self._initialized = False
    
    def initialize(self, position: Tuple[float, float]):
        """
        Initialize state with first measurement.
        
        Sets position to the provided coordinates and velocity to zero.
        
        Args:
            position: (x, y) initial position
        """
        self.X = np.array([
            position[0],  # x
            position[1],  # y
            0.0,          # vx (assume stationary initially)
            0.0           # vy
        ], dtype=np.float64)
        self.P = np.eye(4, dtype=np.float64) * 10.0
        self._initialized = True
    
    @property
    def is_initialized(self) -> bool:
        """Check if filter has been initialized."""
        return self._initialized
    
    def predict(self) -> Tuple[float, float]:
        """
        Predict next state before measurement.
        
        Call this before update() to get predicted position.
        
        Returns:
            (x, y) predicted position
        """
        if not self._initialized:
            raise RuntimeError("Kalman filter not initialized. Call initialize() first.")
        
        # Predict state: X' = F @ X
        self.X = self.F @ self.X
        
        # Predict covariance: P' = F @ P @ F.T + Q
        self.P = self.F @ self.P @ self.F.T + self.Q
        
        return (self.X[0], self.X[1])
    
    def update(self, measured: Tuple[float, float]) -> Tuple[float, float]:
        """
        Update state with new measurement.
        
        Incorporates a new centroid measurement and returns the filtered position.
        
        Args:
            measured: (x, y) measured centroid position
            
        Returns:
            (x, y) filtered position (Kalman estimate)
        """
        if not self._initialized:
            # Auto-initialize if not done
            self.initialize(measured)
            return measured
        
        # Measurement vector
        z = np.array([measured[0], measured[1]], dtype=np.float64)
        
        # Innovation (measurement residual)
        y = z - (self.H @ self.X)
        
        # Innovation covariance
        S = self.H @ self.P @ self.H.T + self.R
        
        # Kalman gain
        K = self.P @ self.H.T @ np.linalg.inv(S)
        
        # Update state
        self.X = self.X + K @ y
        
        # Update covariance (Joseph form for numerical stability)
        I_KH = np.eye(4) - K @ self.H
        self.P = I_KH @ self.P @ I_KH.T + K @ self.R @ K.T
        
        return (self.X[0], self.X[1])
    
    def get_velocity(self) -> Tuple[float, float]:
        """
        Get current estimated velocity.
        
        Returns:
            (vx, vy) velocity in pixels per frame
        """
        if not self._initialized:
            return (0.0, 0.0)
        return (self.X[2], self.X[3])
    
    def get_innovation(self, measured: Tuple[float, float]) -> float:
        """
        Calculate the Mahalanobis distance of a measurement.
        
        This can be used to detect outliers (e.g., cloud interference).
        High values indicate the measurement is far from expected.
        
        Args:
            measured: (x, y) measured position
            
        Returns:
            Mahalanobis distance (chi-squared with 2 DOF)
        """
        if not self._initialized:
            return 0.0
        
        z = np.array([measured[0], measured[1]], dtype=np.float64)
        predicted = self.H @ self.X
        
        S = self.H @ self.P @ self.H.T + self.R
        innovation = z - predicted
        
        mahalanobis = innovation.T @ np.linalg.inv(S) @ innovation
        return float(mahalanobis)
    
    def reset(self):
        """Reset the filter to uninitialized state."""
        self.X = None
        self.P = np.eye(4, dtype=np.float64) * 10.0
        self._initialized = False


@dataclass
class TrackingResult:
    """Result of tracking a star in a single frame."""
    status: TrackingStatus
    centroid: Optional[Tuple[float, float]]  # (x, y) in full image coordinates
    confidence: float  # 0.0 to 1.0
    blob_area: Optional[int] = None
    max_brightness: Optional[float] = None
    message: str = ""


@dataclass
class FrameTracking:
    """Complete tracking data for a single frame."""
    frame_index: int
    polaris: TrackingResult
    second_star: Optional[TrackingResult] = None


def extract_roi(
    image: np.ndarray,
    center: Tuple[float, float],
    size: int = SEARCH_WINDOW_SIZE
) -> Tuple[np.ndarray, Tuple[int, int]]:
    """
    Extract a Region of Interest around the specified center point.
    
    Args:
        image: Full image array
        center: (x, y) center point for the ROI
        size: Size of the square ROI
        
    Returns:
        Tuple of (roi_array, offset) where offset is (x_offset, y_offset)
        from the ROI origin to the full image coordinates
    """
    h, w = image.shape[:2]
    cx, cy = int(center[0]), int(center[1])
    half_size = size // 2
    
    # Calculate ROI bounds with clamping
    x_start = max(0, cx - half_size)
    x_end = min(w, cx + half_size)
    y_start = max(0, cy - half_size)
    y_end = min(h, cy + half_size)
    
    # Extract ROI
    roi = image[y_start:y_end, x_start:x_end]
    
    return roi, (x_start, y_start)


def preprocess_roi(roi: np.ndarray) -> np.ndarray:
    """
    Preprocess ROI for star detection.
    
    Steps:
    1. Convert to grayscale if needed
    2. Apply Gaussian blur to remove hot pixels
    3. Normalize to float32
    
    Args:
        roi: Input ROI array
        
    Returns:
        Preprocessed grayscale ROI as float32
    """
    # Convert to grayscale if color
    if len(roi.shape) == 3:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    else:
        gray = roi.copy()
    
    # Convert to float for processing
    gray = gray.astype(np.float32)
    
    # Normalize 16-bit images
    if gray.max() > 255:
        gray = gray / 256.0
    
    # Apply Gaussian blur
    blurred = cv2.GaussianBlur(
        gray,
        (GAUSSIAN_BLUR_SIZE, GAUSSIAN_BLUR_SIZE),
        GAUSSIAN_BLUR_SIGMA
    )
    
    return blurred


def threshold_star(
    roi: np.ndarray,
    percentile: float = STAR_THRESHOLD_PERCENTILE
) -> np.ndarray:
    """
    Apply adaptive threshold to isolate star pixels.
    
    Uses percentile-based thresholding to find only the brightest pixels.
    
    Args:
        roi: Preprocessed grayscale ROI
        percentile: Only keep pixels above this percentile
        
    Returns:
        Binary mask of star pixels
    """
    # Calculate threshold value from percentile
    threshold_value = np.percentile(roi, percentile)
    
    # Apply threshold (THRESH_TOZERO keeps values above threshold)
    _, thresholded = cv2.threshold(
        roi,
        threshold_value,
        255,
        cv2.THRESH_TOZERO
    )
    
    # Convert to binary for connected components
    binary = (thresholded > 0).astype(np.uint8) * 255
    
    return binary


def find_star_blob(
    binary_mask: np.ndarray,
    roi_center: Tuple[int, int],
    preprocessed_roi: np.ndarray,
    min_blob_area: int = MIN_BLOB_AREA,
    max_blob_area: int = MAX_BLOB_AREA,
) -> Optional[Dict]:
    """
    Find the star blob closest to the ROI center.
    
    Uses connected component analysis to find all blobs, then selects
    the one closest to the expected position (center of ROI).
    
    Args:
        binary_mask: Binary image of thresholded star regions
        roi_center: (x, y) center of the ROI in ROI coordinates
        preprocessed_roi: Original preprocessed ROI for brightness calculation
        min_blob_area: Minimum connected component area
        max_blob_area: Maximum connected component area
        
    Returns:
        Dict with blob info: centroid, area, max_brightness, or None if not found
    """
    # Find connected components
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        binary_mask,
        connectivity=8
    )
    
    if num_labels <= 1:  # Only background
        return None
    
    # Find best blob (closest to center that meets size criteria). Do not build
    # a full ROI mask for every candidate; the labels image already contains
    # the answer and we materialize only the selected bounding box below.
    best_blob = None
    best_distance = float('inf')
    
    for i in range(1, num_labels):  # Skip background (label 0)
        area = stats[i, cv2.CC_STAT_AREA]
        
        # Check size criteria
        if area < min_blob_area or area > max_blob_area:
            continue
        
        # Calculate distance to ROI center
        cx, cy = centroids[i]
        dist = np.sqrt((cx - roi_center[0])**2 + (cy - roi_center[1])**2)
        
        if dist < best_distance:
            best_distance = dist
            best_blob = {
                'label': i,
                'centroid': (cx, cy),
                'area': area,
                'distance_to_center': dist
            }

    if best_blob is not None:
        label = best_blob['label']
        left = int(stats[label, cv2.CC_STAT_LEFT])
        top = int(stats[label, cv2.CC_STAT_TOP])
        width = int(stats[label, cv2.CC_STAT_WIDTH])
        height = int(stats[label, cv2.CC_STAT_HEIGHT])
        local_labels = labels[top:top + height, left:left + width]
        blob_mask = (local_labels == label).astype(np.uint8)
        roi_slice = preprocessed_roi[top:top + height, left:left + width]
        best_blob.update({
            'bbox': (left, top, width, height),
            'blob_mask': blob_mask,
            'max_brightness': float(roi_slice[blob_mask.astype(bool)].max()),
        })
    
    return best_blob


def compute_subpixel_centroid(
    preprocessed_roi: np.ndarray,
    blob_mask: np.ndarray
) -> Tuple[float, float]:
    """
    Compute sub-pixel accurate centroid using image moments.
    
    Args:
        preprocessed_roi: Grayscale ROI
        blob_mask: Binary mask of the star blob
        
    Returns:
        (x, y) sub-pixel centroid in ROI coordinates
    """
    # Create weighted image (intensity as weight)
    weighted = preprocessed_roi * blob_mask.astype(np.float32)
    
    # Compute moments
    moments = cv2.moments(weighted)
    
    if moments['m00'] == 0:
        # Fallback: use mask centroid
        mask_moments = cv2.moments(blob_mask)
        if mask_moments['m00'] == 0:
            return (blob_mask.shape[1] / 2, blob_mask.shape[0] / 2)
        return (
            mask_moments['m10'] / mask_moments['m00'],
            mask_moments['m01'] / mask_moments['m00']
        )
    
    # Calculate centroid
    cx = moments['m10'] / moments['m00']
    cy = moments['m01'] / moments['m00']
    
    return (cx, cy)


def track_star_in_frame(
    image: np.ndarray,
    expected_position: Tuple[float, float],
    previous_position: Optional[Tuple[float, float]] = None,
    search_window_size: int = SEARCH_WINDOW_SIZE,
    max_jump_threshold: float = MAX_JUMP_THRESHOLD,
    star_threshold_percentile: float = STAR_THRESHOLD_PERCENTILE,
    min_blob_area: int = MIN_BLOB_AREA,
    max_blob_area: int = MAX_BLOB_AREA,
) -> TrackingResult:
    """
    Track a star in a single frame.
    
    Args:
        image: Full image array (BGR)
        expected_position: Expected (x, y) position (from previous frame or initial selection)
        previous_position: Position from previous frame (for jump detection)
        search_window_size: Size of square ROI around expected_position
        max_jump_threshold: Maximum allowed frame-to-frame jump in pixels
        star_threshold_percentile: Brightness percentile threshold within ROI
        min_blob_area: Minimum star blob area in pixels
        max_blob_area: Maximum star blob area in pixels
        
    Returns:
        TrackingResult with centroid and status
    """
    # Extract ROI around expected position
    roi, offset = extract_roi(image, expected_position, search_window_size)
    
    if roi.size == 0:
        return TrackingResult(
            status=TrackingStatus.STAR_NOT_FOUND,
            centroid=None,
            confidence=0.0,
            message="ROI extraction failed (position outside image bounds)"
        )
    
    # Preprocess
    preprocessed = preprocess_roi(roi)
    
    # Threshold
    binary = threshold_star(preprocessed, star_threshold_percentile)
    
    # Find star blob
    roi_center = (roi.shape[1] / 2, roi.shape[0] / 2)
    blob = find_star_blob(
        binary,
        roi_center,
        preprocessed,
        min_blob_area=min_blob_area,
        max_blob_area=max_blob_area,
    )
    
    if blob is None:
        return TrackingResult(
            status=TrackingStatus.STAR_NOT_FOUND,
            centroid=None,
            confidence=0.0,
            message="No valid star blob found in ROI"
        )
    
    # Check brightness
    if blob['max_brightness'] < np.percentile(preprocessed, 90):
        return TrackingResult(
            status=TrackingStatus.BRIGHTNESS_TOO_LOW,
            centroid=None,
            confidence=0.0,
            max_brightness=blob['max_brightness'],
            message="Star brightness below threshold (possible cloud cover)"
        )
    
    # Get sub-pixel centroid from the selected bounding box. Connected
    # components were already computed by find_star_blob.
    left, top, width, height = blob['bbox']
    local_centroid = compute_subpixel_centroid(
        preprocessed[top:top + height, left:left + width], blob['blob_mask'])
    local_centroid = (local_centroid[0] + left, local_centroid[1] + top)
    
    # Convert to full image coordinates
    global_centroid = (
        local_centroid[0] + offset[0],
        local_centroid[1] + offset[1]
    )
    
    # Check for excessive jump
    if previous_position is not None:
        jump = np.sqrt(
            (global_centroid[0] - previous_position[0])**2 +
            (global_centroid[1] - previous_position[1])**2
        )
        if jump > max_jump_threshold:
            return TrackingResult(
                status=TrackingStatus.JUMP_TOO_LARGE,
                centroid=global_centroid,
                confidence=0.3,
                blob_area=blob['area'],
                max_brightness=blob['max_brightness'],
                message=f"Jump of {jump:.1f}px exceeds threshold of {max_jump_threshold}px"
            )
    
    # Calculate confidence based on blob quality
    confidence = min(1.0, (
        (blob['area'] / (min_blob_area + max_blob_area) * 2) * 0.3 +  # Area score
        (1.0 - blob['distance_to_center'] / max(1.0, (search_window_size / 2))) * 0.4 +  # Position score
        min(blob['max_brightness'] / 200.0, 1.0) * 0.3  # Brightness score
    ))
    
    return TrackingResult(
        status=TrackingStatus.SUCCESS,
        centroid=global_centroid,
        confidence=confidence,
        blob_area=blob['area'],
        max_brightness=blob['max_brightness'],
        message="Star successfully tracked"
    )


def track_sequence(
    images: List[np.ndarray],
    initial_polaris: Tuple[float, float],
    initial_second_star: Optional[Tuple[float, float]] = None,
    progress_callback=None,
    use_kalman: bool = USE_KALMAN_FILTER,
    kalman_process_noise: float = KALMAN_PROCESS_NOISE,
    kalman_measurement_noise: float = KALMAN_MEASUREMENT_NOISE,
    search_window_size: int = SEARCH_WINDOW_SIZE,
    max_jump_threshold: float = MAX_JUMP_THRESHOLD,
    star_threshold_percentile: float = STAR_THRESHOLD_PERCENTILE,
    min_blob_area: int = MIN_BLOB_AREA,
    max_blob_area: int = MAX_BLOB_AREA,
    cancel_check=None,
    prefetch_workers=1,
) -> List[FrameTracking]:
    """
    Track stars through a sequence of images.
    
    Uses dynamic ROI: each frame's search is centered on the previous frame's result.
    Optionally uses Kalman filtering for smoother, noise-resistant tracking.
    
    Args:
        images: List of image arrays OR list of image paths
        initial_polaris: (x, y) position of Polaris in the first frame
        initial_second_star: Optional (x, y) position of second star
        progress_callback: Optional callable(frame_index, total_frames)
        use_kalman: Whether to use Kalman filtering (default from config)
        kalman_process_noise: Process noise variance for Kalman filter
        kalman_measurement_noise: Measurement noise variance for Kalman filter
        search_window_size: ROI size for star search
        max_jump_threshold: Maximum allowed frame-to-frame jump in pixels
        star_threshold_percentile: Percentile threshold for star pixels in ROI
        min_blob_area: Minimum star blob area in pixels
        max_blob_area: Maximum star blob area in pixels
        
    Returns:
        List of FrameTracking objects, one per frame
    """
    from modules.io_utils import load_image
    from core.cancellation import check_cancelled
    from core.parallel import ordered_map
    
    results = []
    
    # Initialize Kalman filters if enabled
    polaris_kalman = None
    second_star_kalman = None
    
    if use_kalman:
        polaris_kalman = KalmanCentroidTracker(
            process_noise=kalman_process_noise,
            measurement_noise=kalman_measurement_noise,
        )
        polaris_kalman.initialize(initial_polaris)
        
        if initial_second_star is not None:
            second_star_kalman = KalmanCentroidTracker(
                process_noise=kalman_process_noise,
                measurement_noise=kalman_measurement_noise,
            )
            second_star_kalman.initialize(initial_second_star)
    
    # Initialize with reference positions
    current_polaris = initial_polaris
    current_second_star = initial_second_star
    previous_polaris = None
    previous_second_star = None
    
    # Last known good positions (for fallback)
    last_good_polaris = initial_polaris
    last_good_second_star = initial_second_star
    
    total = len(images)
    
    def read(img_or_path):
        check_cancelled(cancel_check)
        image = load_image(img_or_path) if isinstance(img_or_path, (str, Path)) else img_or_path
        check_cancelled(cancel_check)
        return image

    for i, image in enumerate(ordered_map(read, images, workers=prefetch_workers,
                                         cancel_check=cancel_check)):
        check_cancelled(cancel_check)
        if progress_callback:
            # Calculate drift if we have current_polaris
            dx = current_polaris[0] - initial_polaris[0] if current_polaris else 0.0
            dy = current_polaris[1] - initial_polaris[1] if current_polaris else 0.0
            progress_callback(i, total, drift_x=dx, drift_y=dy)
        
        check_cancelled(cancel_check)
        
        # Get predicted position from Kalman filter if available
        if use_kalman and polaris_kalman.is_initialized and i > 0:
            predicted_polaris = polaris_kalman.predict()
            search_position = predicted_polaris
        else:
            search_position = current_polaris
        
        # Track Polaris
        polaris_result = track_star_in_frame(
            image,
            search_position,
            previous_polaris,
            search_window_size=search_window_size,
            max_jump_threshold=max_jump_threshold,
            star_threshold_percentile=star_threshold_percentile,
            min_blob_area=min_blob_area,
            max_blob_area=max_blob_area,
        )
        
        # Handle tracking based on result status
        if polaris_result.status == TrackingStatus.SUCCESS:
            raw_centroid = polaris_result.centroid
            
            # Apply Kalman filter if enabled
            if use_kalman:
                # Check if measurement is an outlier using Mahalanobis distance
                innovation = polaris_kalman.get_innovation(raw_centroid)
                
                if innovation > 15.0:  # Chi-squared threshold for 2 DOF
                    # Outlier detected - possible cloud or satellite
                    if VERBOSE:
                        print(f"  Frame {i}: Outlier detected (innovation={innovation:.1f}), using prediction")
                    filtered_centroid = (polaris_kalman.X[0], polaris_kalman.X[1])
                    polaris_result = TrackingResult(
                        status=TrackingStatus.USING_FALLBACK,
                        centroid=filtered_centroid,
                        confidence=polaris_result.confidence * 0.7,
                        blob_area=polaris_result.blob_area,
                        max_brightness=polaris_result.max_brightness,
                        message="Kalman outlier rejection applied"
                    )
                else:
                    # Normal update
                    filtered_centroid = polaris_kalman.update(raw_centroid)
                    polaris_result = TrackingResult(
                        status=TrackingStatus.SUCCESS,
                        centroid=filtered_centroid,
                        confidence=polaris_result.confidence,
                        blob_area=polaris_result.blob_area,
                        max_brightness=polaris_result.max_brightness,
                        message="Kalman filtered"
                    )
                
                current_polaris = filtered_centroid
            else:
                current_polaris = raw_centroid
            
            last_good_polaris = current_polaris
            
        elif polaris_result.status == TrackingStatus.JUMP_TOO_LARGE:
            # Large jump - may be real or tracking error
            if use_kalman:
                # Use Kalman prediction instead
                if VERBOSE:
                    print(f"  Frame {i}: Large jump detected, using Kalman prediction")
                current_polaris = (polaris_kalman.X[0], polaris_kalman.X[1])
                polaris_result = TrackingResult(
                    status=TrackingStatus.USING_FALLBACK,
                    centroid=current_polaris,
                    confidence=0.6,
                    message="Using Kalman prediction due to large jump"
                )
            else:
                if VERBOSE:
                    print(f"  Frame {i}: Large jump detected, using with caution")
                current_polaris = polaris_result.centroid
        else:
            # Star not found or low brightness
            if use_kalman:
                # Use Kalman prediction
                current_polaris = (polaris_kalman.X[0], polaris_kalman.X[1])
                if VERBOSE:
                    print(f"  Frame {i}: {polaris_result.status.value} - using Kalman prediction")
            else:
                current_polaris = last_good_polaris
                if VERBOSE:
                    print(f"  Frame {i}: {polaris_result.status.value} - using fallback")
            
            polaris_result = TrackingResult(
                status=TrackingStatus.USING_FALLBACK,
                centroid=current_polaris,
                confidence=0.5,
                message=f"Using fallback due to: {polaris_result.message}"
            )
        
        previous_polaris = current_polaris
        
        # Track second star if provided
        second_star_result = None
        if initial_second_star is not None:
            # Get predicted position from Kalman if available
            if use_kalman and second_star_kalman.is_initialized and i > 0:
                predicted_second = second_star_kalman.predict()
                search_second = predicted_second
            else:
                search_second = current_second_star
            
            second_star_result = track_star_in_frame(
                image,
                search_second,
                previous_second_star,
                search_window_size=search_window_size,
                max_jump_threshold=max_jump_threshold,
                star_threshold_percentile=star_threshold_percentile,
                min_blob_area=min_blob_area,
                max_blob_area=max_blob_area,
            )
            
            if second_star_result.status == TrackingStatus.SUCCESS:
                raw_second = second_star_result.centroid
                
                if use_kalman:
                    filtered_second = second_star_kalman.update(raw_second)
                    second_star_result = TrackingResult(
                        status=TrackingStatus.SUCCESS,
                        centroid=filtered_second,
                        confidence=second_star_result.confidence,
                        blob_area=second_star_result.blob_area,
                        max_brightness=second_star_result.max_brightness,
                        message="Kalman filtered"
                    )
                    current_second_star = filtered_second
                else:
                    current_second_star = raw_second
                
                last_good_second_star = current_second_star
            else:
                if use_kalman:
                    current_second_star = (second_star_kalman.X[0], second_star_kalman.X[1])
                else:
                    current_second_star = last_good_second_star
                
                second_star_result = TrackingResult(
                    status=TrackingStatus.USING_FALLBACK,
                    centroid=current_second_star,
                    confidence=0.5,
                    message=f"Using fallback: {second_star_result.message}"
                )
            
            previous_second_star = current_second_star
        
        results.append(FrameTracking(
            frame_index=i,
            polaris=polaris_result,
            second_star=second_star_result
        ))
    
    return results


def get_tracking_summary(tracking_results: List[FrameTracking]) -> Dict:
    """
    Generate a summary of tracking results.
    
    Args:
        tracking_results: List of FrameTracking objects
        
    Returns:
        Dict with statistics about tracking success, failures, etc.
    """
    total = len(tracking_results)
    success_count = sum(
        1 for r in tracking_results
        if r.polaris.status == TrackingStatus.SUCCESS
    )
    fallback_count = sum(
        1 for r in tracking_results
        if r.polaris.status == TrackingStatus.USING_FALLBACK
    )
    
    # Calculate drift statistics
    centroids = [r.polaris.centroid for r in tracking_results if r.polaris.centroid]
    if len(centroids) >= 2:
        xs = [c[0] for c in centroids]
        ys = [c[1] for c in centroids]
        total_drift_x = max(xs) - min(xs)
        total_drift_y = max(ys) - min(ys)
    else:
        total_drift_x = 0
        total_drift_y = 0
    
    return {
        'total_frames': total,
        'successful_tracks': success_count,
        'fallback_used': fallback_count,
        'success_rate': success_count / total if total > 0 else 0,
        'total_drift_x': total_drift_x,
        'total_drift_y': total_drift_y,
        'max_drift': np.sqrt(total_drift_x**2 + total_drift_y**2)
    }
