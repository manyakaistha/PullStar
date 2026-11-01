"""
Star Trail Aligner - Video Module

This package contains video encoding functionality:
- Pro-grade FFmpeg encoding (ProRes, H.264)
- Trail-lapse video generation
- Streaming encoder for memory efficiency
- Tone mapping for display
"""

from .encoder import TrailLapseEncoder, tone_map_for_display, tone_map_for_export
from .ffmpeg_writer import (
    FFmpegPipe,
    FallbackVideoWriter,
    create_video_writer,
    is_ffmpeg_available,
    EncoderStats
)

