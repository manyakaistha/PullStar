"""
Star Trail Aligner - Video Encoder

Creates trail-lapse videos by streaming processed frames to a video file.
Uses OpenCV's VideoWriter which is cross-platform compatible 
(Mac, Linux, Windows) without requiring CUDA.

Features:
- Streaming encoder (memory-efficient)
- Tone mapping for night sky visualization
- Support for 8-bit and 16-bit sources
"""

import cv2
import numpy as np
from pathlib import Path
from typing import Optional, Union
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import VIDEO_FPS, VIDEO_CODEC, TONE_MAP_GAMMA


def tone_map_for_display(
    image: np.ndarray,
    gamma: float = TONE_MAP_GAMMA,
    black_point: float = 0.0,
    white_point: float = 1.0
) -> np.ndarray:
    """
    Apply tone mapping to an HDR/high-bit-depth image for display.
    
    Night sky images often have most detail in the shadows.
    This function enhances visibility of faint stars while
    preserving bright highlights.
    
    Args:
        image: Input image (any dtype)
        gamma: Gamma correction value (< 1.0 brightens shadows)
        black_point: Input value to map to black (0.0-1.0)
        white_point: Input value to map to white (0.0-1.0)
        
    Returns:
        8-bit tone-mapped image suitable for video encoding
    """
    # Convert to float [0, 1]
    if image.dtype == np.uint8:
        img_float = image.astype(np.float32) / 255.0
    elif image.dtype == np.uint16:
        img_float = image.astype(np.float32) / 65535.0
    else:
        img_float = np.clip(image.astype(np.float32), 0, 1)
    
    # Apply levels adjustment
    img_float = (img_float - black_point) / (white_point - black_point)
    img_float = np.clip(img_float, 0, 1)
    
    # Apply gamma correction
    img_gamma = np.power(img_float, gamma)
    
    # Convert to 8-bit
    img_8bit = (np.clip(img_gamma, 0, 1) * 255).astype(np.uint8)
    
    return img_8bit


def tone_map_for_export(
    image: np.ndarray,
    gamma: float = TONE_MAP_GAMMA,
    output_bits: int = 16
) -> np.ndarray:
    """
    Apply tone mapping for high-quality export (TIFF, etc.)
    
    Args:
        image: Input image (any dtype)
        gamma: Gamma correction value
        output_bits: Output bit depth (8 or 16)
        
    Returns:
        Tone-mapped image in specified bit depth
    """
    # Convert to float [0, 1]
    if image.dtype == np.uint8:
        img_float = image.astype(np.float32) / 255.0
    elif image.dtype == np.uint16:
        img_float = image.astype(np.float32) / 65535.0
    else:
        img_float = np.clip(image.astype(np.float32), 0, 1)
    
    # Apply gamma correction
    img_gamma = np.power(img_float, gamma)
    
    # Convert to output bit depth
    if output_bits == 8:
        return (np.clip(img_gamma, 0, 1) * 255).astype(np.uint8)
    else:
        return (np.clip(img_gamma, 0, 1) * 65535).astype(np.uint16)


class TrailLapseEncoder:
    """
    Streaming video encoder for trail-lapse creation.
    
    Writes frames progressively to avoid loading all frames in memory.
    Uses a memory-efficient approach suitable for processing
    hundreds or thousands of frames.
    
    Example:
        >>> encoder = TrailLapseEncoder("output.mp4", (1920, 1080))
        >>> encoder.open()
        >>> for frame in frames:
        ...     encoder.write_frame(frame)
        >>> encoder.close()
    """
    
    def __init__(
        self,
        output_path: Union[str, Path],
        frame_size: tuple,
        fps: int = VIDEO_FPS,
        codec: str = VIDEO_CODEC
    ):
        """
        Initialize the encoder.
        
        Args:
            output_path: Path to output video file
            frame_size: (width, height) of video frames
            fps: Frames per second
            codec: FourCC codec code (e.g., 'mp4v', 'XVID')
        """
        self.output_path = Path(output_path)
        self.frame_size = frame_size
        self.fps = fps
        self.codec = codec
        
        self.writer = None
        self.frame_count = 0
        self._is_open = False
    
    def open(self) -> bool:
        """
        Open the video writer.
        
        Returns:
            True if successfully opened, False otherwise
        """
        if self._is_open:
            return True
        
        # Ensure parent directory exists
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Create FourCC code
        fourcc = cv2.VideoWriter_fourcc(*self.codec)
        
        # Create VideoWriter
        self.writer = cv2.VideoWriter(
            str(self.output_path),
            fourcc,
            self.fps,
            self.frame_size,
            isColor=True
        )
        
        if not self.writer.isOpened():
            print(f"Warning: Failed to open video writer with codec {self.codec}")
            # Try fallback codecs
            fallback_codecs = ['MJPG', 'XVID', 'DIVX']
            for fallback in fallback_codecs:
                if fallback == self.codec:
                    continue
                print(f"Trying fallback codec: {fallback}")
                fourcc = cv2.VideoWriter_fourcc(*fallback)
                self.writer = cv2.VideoWriter(
                    str(self.output_path),
                    fourcc,
                    self.fps,
                    self.frame_size,
                    isColor=True
                )
                if self.writer.isOpened():
                    self.codec = fallback
                    break
        
        self._is_open = self.writer.isOpened()
        return self._is_open
    
    def write_frame(
        self,
        frame: np.ndarray,
        apply_tone_mapping: bool = True,
        gamma: Optional[float] = None
    ):
        """
        Write a single frame to the video.
        
        Args:
            frame: Image frame (BGR format, any dtype)
            apply_tone_mapping: Whether to apply tone mapping
            gamma: Custom gamma value (None = use default)
        """
        if not self._is_open:
            raise RuntimeError("Encoder not open. Call open() first.")
        
        # Prepare frame for video (must be 8-bit BGR)
        if apply_tone_mapping:
            g = gamma if gamma is not None else TONE_MAP_GAMMA
            frame_8bit = tone_map_for_display(frame, gamma=g)
        else:
            if frame.dtype == np.uint16:
                frame_8bit = (frame / 256).astype(np.uint8)
            elif frame.dtype != np.uint8:
                frame_8bit = (np.clip(frame, 0, 255)).astype(np.uint8)
            else:
                frame_8bit = frame
        
        # Ensure correct size
        h, w = frame_8bit.shape[:2]
        if (w, h) != self.frame_size:
            frame_8bit = cv2.resize(frame_8bit, self.frame_size, interpolation=cv2.INTER_LANCZOS4)
        
        # Ensure color (3 channels)
        if len(frame_8bit.shape) == 2:
            frame_8bit = cv2.cvtColor(frame_8bit, cv2.COLOR_GRAY2BGR)
        
        self.writer.write(frame_8bit)
        self.frame_count += 1
    
    def write_accumulator_snapshot(
        self,
        accumulator: np.ndarray,
        apply_tone_mapping: bool = True,
        gamma: Optional[float] = None
    ):
        """
        Write the current state of an accumulator as a video frame.
        
        Useful for creating "growing trail" animations where each frame
        shows the cumulative trails up to that point.
        
        Args:
            accumulator: Float accumulator array (32 or 64 bit)
            apply_tone_mapping: Whether to apply tone mapping
            gamma: Custom gamma value
        """
        # Normalize accumulator to 0-1 float range (preserving full precision)
        max_val = accumulator.max()
        if max_val > 0:
            normalized = (accumulator / max_val).astype(np.float32)
        else:
            normalized = accumulator.astype(np.float32)
        
        # Apply tone mapping on full-precision float data, then convert to 8-bit
        if apply_tone_mapping:
            g = gamma if gamma is not None else TONE_MAP_GAMMA
            frame = tone_map_for_display(normalized, gamma=g)
        else:
            frame = (np.clip(normalized, 0, 1) * 255).astype(np.uint8)
        
        self.write_frame(frame, apply_tone_mapping=False)
    
    def abort(self):
        self.close()

    def close(self, cancel_check=None):
        """Close the video writer and finalize the file."""
        if self.writer is not None:
            self.writer.release()
            self.writer = None
        self._is_open = False
        if cancel_check:
            cancel_check()
    
    def __enter__(self):
        """Context manager entry."""
        self.open()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False
    
    @property
    def is_open(self) -> bool:
        """Check if the encoder is open."""
        return self._is_open
    
    @property
    def frames_written(self) -> int:
        """Get the number of frames written."""
        return self.frame_count


def get_available_codecs() -> list:
    """
    Get a list of available video codecs on this system.
    
    Returns:
        List of codec names that should work
    """
    # These are common codecs that work on most systems
    common_codecs = ['mp4v', 'XVID', 'MJPG', 'DIVX']
    available = []
    
    for codec in common_codecs:
        try:
            fourcc = cv2.VideoWriter_fourcc(*codec)
            # Try creating a test writer
            test_path = Path('/tmp/codec_test.mp4')
            writer = cv2.VideoWriter(str(test_path), fourcc, 30, (640, 480))
            if writer.isOpened():
                available.append(codec)
            writer.release()
            if test_path.exists():
                test_path.unlink()
        except Exception:
            continue
    
    return available if available else common_codecs
