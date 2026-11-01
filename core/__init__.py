"""
Star Trail Aligner - Core Module

This package contains the core algorithms for star trail alignment:
- Timeline scheduler for render scheduling
- Kalman filter for centroid tracking
- Ephemeris calculations (optional)
- Checkpoint/resume system
- Input validation
"""

from .checkpoint import save_checkpoint, load_checkpoint
from .validator import validate_inputs
from .scheduler import (
    RenderAction,
    RenderActionType,
    ScheduleStats,
    generate_schedule,
    print_schedule_summary
)

# Optional ephemeris import
try:
    from .ephemeris import get_polaris_position, is_ephemeris_available
except ImportError:
    def get_polaris_position(*args, **kwargs):
        return None
    def is_ephemeris_available():
        return False

