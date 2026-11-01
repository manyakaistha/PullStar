"""
Star Trail Aligner - Modules Package

This package contains the core modules for star trail alignment:
- io_utils: Image loading and saving utilities
- gui: Interactive star selection interface
- tracker: Star centroiding and tracking algorithm
- transform: Affine transformation and crop calculations
"""

from . import io_utils
from . import gui
from . import tracker
from . import transform

__all__ = ['io_utils', 'gui', 'tracker', 'transform']
