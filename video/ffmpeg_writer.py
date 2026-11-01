"""
Star Trail Aligner - FFmpeg Video Writer

Pro-grade video encoding via direct pipe to FFmpeg subprocess.
Supports high-quality codecs (ProRes, H.264) that OpenCV can't access directly.

Benefits over cv2.VideoWriter:
- ProRes 422 HQ for professional color grading
- True lossless H.264 encoding
- 10-bit color depth support
- Proper gamma handling
"""

import subprocess
import shutil
import cv2
import numpy as np
from pathlib import Path
from typing import Optional, Literal
from dataclasses import dataclass


@dataclass
class EncoderStats:
    """Statistics about video encoding."""
    frames_written: int
    output_path: Path
    codec: str
    quality_preset: str


# Check if FFmpeg is available
def is_ffmpeg_available() -> bool:
    """Check if FFmpeg is installed and accessible."""
    executable = shutil.which('ffmpeg')
    if executable is None:
        return False
    try:
        return subprocess.run([executable, '-version'], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


class FFmpegPipe:
    """
    Stream frames directly to FFmpeg for high-quality encoding.
    
    This bypasses OpenCV's limited codec support and enables
    professional-grade encoding options.
    
    Example:
        pipe = FFmpegPipe('output.mov', 1920, 1080, 30, quality='prores')
        for frame in frames:
            pipe.write(frame)
        pipe.close()
    """
    
    # Codec presets
    PRESETS = {
        'prores': {
            'ext': '.mov',
            'args': ['-c:v', 'prores_ks', '-profile:v', '3', '-pix_fmt', 'yuv422p10le'],
            'description': 'ProRes 422 HQ (10-bit, ideal for Mac grading)'
        },
        'prores4444': {
            'ext': '.mov',
            'args': ['-c:v', 'prores_ks', '-profile:v', '4', '-pix_fmt', 'yuva444p10le'],
            'description': 'ProRes 4444 (12-bit with alpha, highest quality)'
        },
        'lossless': {
            'ext': '.mp4',
            'args': ['-c:v', 'libx264', '-crf', '0', '-preset', 'ultrafast', '-pix_fmt', 'yuv444p'],
            'description': 'H.264 Lossless (large files)'
        },
        'high': {
            'ext': '.mp4',
            'args': ['-c:v', 'libx264', '-crf', '17', '-preset', 'slow', '-pix_fmt', 'yuv420p'],
            'description': 'H.264 High Quality (visually lossless, good size)'
        },
        'medium': {
            'ext': '.mp4',
            'args': ['-c:v', 'libx264', '-crf', '23', '-preset', 'medium', '-pix_fmt', 'yuv420p'],
            'description': 'H.264 Medium Quality (balanced)'
        },
        'hevc': {
            'ext': '.mp4',
            'args': ['-c:v', 'libx265', '-crf', '20', '-preset', 'slow', '-pix_fmt', 'yuv420p',
                     '-tag:v', 'hvc1'],
            'description': 'H.265/HEVC (better compression, modern delivery)'
        },
        'hevc_toolbox': {
            'ext': '.mp4',
            'args': ['-c:v', 'hevc_videotoolbox', '-q:v', '65', '-tag:v', 'hvc1'],
            'description': 'H.265 via macOS VideoToolbox (hardware-accelerated)'
        }
    }
    
    def __init__(
        self,
        output_path: Path,
        width: int,
        height: int,
        fps: int = 30,
        quality: Literal['prores', 'lossless', 'high', 'medium'] = 'high',
        container: str = 'auto'
    ):
        """
        Initialize FFmpeg pipe.
        
        Args:
            output_path: Output video file path (extension will be adjusted)
            width: Frame width in pixels
            height: Frame height in pixels
            fps: Frames per second
            quality: Quality preset ('prores', 'lossless', 'high', 'medium')
        """
        self.width = width
        self.height = height
        self.fps = fps
        self.quality = quality
        self.frame_count = 0
        self._snapshot_work = None
        self._snapshot_frame = None
        
        # Get preset configuration
        if quality not in self.PRESETS:
            raise ValueError(f"Unknown quality preset: {quality}. Use one of: {list(self.PRESETS.keys())}")
        
        preset = self.PRESETS[quality]
        
        # Ensure correct extension for codec
        if container not in {'auto', 'mp4', 'mov'} or (quality.startswith('prores') and container == 'mp4'):
            raise ValueError("Unsupported video container for the selected codec")
        self.output_path = Path(output_path).with_suffix(preset['ext'] if container == 'auto' else '.' + container)
        
        # Build FFmpeg command
        self.cmd = [
            'ffmpeg',
            '-y',  # Overwrite output
            '-f', 'rawvideo',
            '-vcodec', 'rawvideo',
            '-s', f'{width}x{height}',
            '-pix_fmt', 'bgr24',  # OpenCV uses BGR
            '-r', str(fps),
            '-i', '-',  # Read from stdin
            *preset['args'],
            str(self.output_path)
        ]
        
        # Start FFmpeg subprocess
        self.pipe = subprocess.Popen(
            self.cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    
    def write(self, frame: np.ndarray) -> None:
        """
        Write a frame to the video.
        
        Args:
            frame: BGR numpy array (uint8 or will be converted)
        """
        if self.pipe is None or self.pipe.stdin is None:
            raise RuntimeError("FFmpeg pipe is not open")
        
        # Ensure correct shape
        if frame.shape[:2] != (self.height, self.width):
            raise ValueError(f"Frame size {frame.shape[:2]} doesn't match expected ({self.height}, {self.width})")
        
        # Convert to uint8 if needed
        if frame.dtype != np.uint8:
            if frame.dtype in (np.float32, np.float64):
                # Normalize float to 0-255
                frame_max = frame.max()
                if frame_max > 0:
                    frame = (frame / frame_max * 255).astype(np.uint8)
                else:
                    frame = np.zeros_like(frame, dtype=np.uint8)
            elif frame.dtype == np.uint16:
                # Convert 16-bit to 8-bit
                frame = (frame / 257).astype(np.uint8)
            else:
                frame = frame.astype(np.uint8)
        
        # Ensure 3 channels
        if len(frame.shape) == 2:
            frame = np.stack([frame, frame, frame], axis=-1)
        elif frame.shape[2] == 4:
            frame = frame[:, :, :3]
        
        frame = np.ascontiguousarray(frame)
        self.pipe.stdin.write(memoryview(frame))
        self.frame_count += 1

    def _snapshot_buffers(self, shape):
        if self._snapshot_work is None or self._snapshot_work.shape != shape:
            self._snapshot_work = np.empty(shape, np.float32)
            self._snapshot_frame = np.empty(shape, np.uint8)
        return self._snapshot_work, self._snapshot_frame
    
    def write_accumulator_snapshot(self, accumulator: np.ndarray, gamma: float = 0.5) -> None:
        """
        Write a tone-mapped snapshot of the accumulator.
        
        Applies gamma correction to enhance faint trails.
        
        Args:
            accumulator: Float32 accumulator array
            gamma: Gamma correction value (< 1.0 brightens dark areas)
        """
        # A lower video resolution can be selected independently of the TIFF
        # stack. Resize before tone mapping so FFmpeg receives the requested
        # dimensions and the encoder does less work per frame.
        source = accumulator
        if source.shape[:2] != (self.height, self.width):
            source = cv2.resize(source, (self.width, self.height),
                                interpolation=cv2.INTER_AREA)
        work, frame = self._snapshot_buffers(source.shape)
        acc_min, acc_max = float(source.min()), float(source.max())
        if acc_max > acc_min:
            np.subtract(source, acc_min, out=work)
            np.divide(work, acc_max - acc_min, out=work)
        else:
            work.fill(0)
        np.power(work, gamma, out=work)
        np.multiply(work, 255, out=work)
        np.clip(work, 0, 255, out=work)
        np.copyto(frame, work, casting="unsafe")
        self.write(frame)
    
    def abort(self):
        """Stop the subprocess without waiting for buffered frames to encode."""
        if self.pipe:
            if self.pipe.poll() is None:
                self.pipe.terminate()
                try:
                    self.pipe.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.pipe.kill()
                    self.pipe.wait(timeout=2)
            if self.pipe.stdin and not self.pipe.stdin.closed:
                try:
                    self.pipe.stdin.close()
                except (BrokenPipeError, OSError):
                    pass

    def close(self, cancel_check=None) -> EncoderStats:
        """
        Close the video file and return statistics.
        
        Returns:
            EncoderStats with encoding information
        """
        try:
            if self.pipe and self.pipe.stdin:
                if not self.pipe.stdin.closed:
                    self.pipe.stdin.close()
                while True:
                    if cancel_check:
                        cancel_check()
                    try:
                        self.pipe.wait(timeout=0.1)
                        break
                    except subprocess.TimeoutExpired:
                        continue
        except BaseException:
            self.abort()
            raise
        
        if self.pipe.returncode != 0:
            raise RuntimeError(f"Video encoding failed (FFmpeg exit {self.pipe.returncode}). Check the selected codec and available disk space.")
        return EncoderStats(
            frames_written=self.frame_count,
            output_path=self.output_path,
            codec=self.PRESETS[self.quality]['args'][1],
            quality_preset=self.quality
        )
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


class FallbackVideoWriter:
    """
    Fallback video writer using OpenCV when FFmpeg is not available.
    
    Uses the same interface as FFmpegPipe for drop-in replacement.
    """
    
    def __init__(
        self,
        output_path: Path,
        width: int,
        height: int,
        fps: int = 30,
        quality: str = 'high'
    ):
        import cv2
        
        self.output_path = Path(output_path).with_suffix('.mp4')
        self.width = width
        self.height = height
        self.fps = fps
        self.quality = quality
        self.frame_count = 0
        self._snapshot_work = None
        self._snapshot_frame = None
        
        # Try codecs in order of preference
        codecs = ['mp4v', 'XVID', 'MJPG']
        self.writer = None
        
        for codec in codecs:
            fourcc = cv2.VideoWriter_fourcc(*codec)
            self.writer = cv2.VideoWriter(
                str(self.output_path),
                fourcc,
                fps,
                (width, height)
            )
            if self.writer.isOpened():
                break
        
        if not self.writer or not self.writer.isOpened():
            raise RuntimeError("Failed to initialize video writer with any codec")
    
    def write(self, frame: np.ndarray) -> None:
        """Write a frame to the video."""
        import cv2

        if frame.shape[:2] != (self.height, self.width):
            frame = cv2.resize(frame, (self.width, self.height),
                               interpolation=cv2.INTER_AREA)
        
        # Convert to uint8 if needed
        if frame.dtype != np.uint8:
            if frame.dtype in (np.float32, np.float64):
                frame_max = frame.max()
                if frame_max > 0:
                    frame = (frame / frame_max * 255).astype(np.uint8)
                else:
                    frame = np.zeros_like(frame, dtype=np.uint8)
            elif frame.dtype == np.uint16:
                frame = (frame / 257).astype(np.uint8)
        
        self.writer.write(np.ascontiguousarray(frame))
        self.frame_count += 1

    def _snapshot_buffers(self, shape):
        if self._snapshot_work is None or self._snapshot_work.shape != shape:
            self._snapshot_work = np.empty(shape, np.float32)
            self._snapshot_frame = np.empty(shape, np.uint8)
        return self._snapshot_work, self._snapshot_frame
    
    def write_accumulator_snapshot(self, accumulator: np.ndarray, gamma: float = 0.5) -> None:
        """Write tone-mapped snapshot."""
        work, frame = self._snapshot_buffers(accumulator.shape)
        acc_min, acc_max = float(accumulator.min()), float(accumulator.max())
        if acc_max > acc_min:
            np.subtract(accumulator, acc_min, out=work)
            np.divide(work, acc_max - acc_min, out=work)
        else:
            work.fill(0)
        np.power(work, gamma, out=work)
        np.multiply(work, 255, out=work)
        np.clip(work, 0, 255, out=work)
        np.copyto(frame, work, casting="unsafe")
        self.write(frame)
    
    def abort(self):
        self.close()

    def close(self, cancel_check=None) -> EncoderStats:
        """Close video file."""
        if self.writer:
            self.writer.release()
            self.writer = None
        if cancel_check:
            cancel_check()
        
        return EncoderStats(
            frames_written=self.frame_count,
            output_path=self.output_path,
            codec='mp4v (OpenCV fallback)',
            quality_preset=self.quality
        )
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


def create_video_writer(
    output_path: Path,
    width: int,
    height: int,
    fps: int = 30,
    quality: str = 'high',
    container: str = 'auto'
):
    """
    Factory function to create the best available video writer.
    
    Uses FFmpegPipe if FFmpeg is available, otherwise falls back to OpenCV.
    
    Args:
        output_path: Output video path
        width: Frame width
        height: Frame height
        fps: Frames per second
        quality: Quality preset
        
    Returns:
        Video writer instance (FFmpegPipe or FallbackVideoWriter)
    """
    if is_ffmpeg_available():
        return FFmpegPipe(output_path, width, height, fps, quality, container=container)
    else:
        if quality != 'high' or container == 'mov':
            raise RuntimeError("FFmpeg is required for the selected video format and quality. Install FFmpeg or choose MP4 with high quality.")
        print("Note: FFmpeg not found, using OpenCV MP4 fallback")
        return FallbackVideoWriter(output_path, width, height, fps, quality)
