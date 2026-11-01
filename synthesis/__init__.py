"""
Star Trail Aligner - Synthesis Module

This package contains modules for synthetic trail generation:
- Foreground masking (sky/ground segmentation)
- Phase-based rotation engine
- Ghost frame generator for trail extension
"""

from .foreground_mask import segment_sky_ground
from .rotation_engine import rotate_image, rotate_via_phase
from .synthetic_generator import generate_ghost_frames
