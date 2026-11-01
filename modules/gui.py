"""
Star Trail Aligner - GUI Module

This module provides an interactive interface for selecting stars in the reference image.
Features:
- Mouse-wheel zoom for precise star selection
- Click-to-select Polaris position
- Optional second star selection for rotation correction
- Visual feedback with crosshairs at selected positions
"""

import cv2
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
from matplotlib.lines import Line2D
from matplotlib.backend_bases import MouseButton
from pathlib import Path
from typing import Tuple, Optional, List
from dataclasses import dataclass

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import VERBOSE


@dataclass
class StarSelection:
    """Container for star selection results."""
    polaris: Tuple[float, float]  # (x, y) coordinates of Polaris
    second_star: Optional[Tuple[float, float]] = None  # Optional second star


class ZoomableStarSelector:
    """
    Interactive matplotlib-based star selector with zoom capability.
    
    Controls:
    - Scroll wheel: Zoom in/out centered on cursor
    - Left click: Select star (first click = Polaris, second = optional star)
    - Right click: Undo last selection
    - Enter/Return: Confirm selection and exit
    - Escape: Cancel and exit without selection
    """
    
    def __init__(self, image: np.ndarray, title: str = "Star Selection"):
        """
        Initialize the star selector.
        
        Args:
            image: BGR image as numpy array
            title: Window title
        """
        # Convert BGR to RGB for matplotlib display
        if len(image.shape) == 3 and image.shape[2] == 3:
            self.image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        else:
            self.image_rgb = image
        
        # Normalize for display if needed
        if self.image_rgb.dtype == np.uint16:
            # Convert 16-bit to 8-bit for display
            self.display_image = (self.image_rgb / 256).astype(np.uint8)
        elif self.image_rgb.dtype == np.float32 or self.image_rgb.dtype == np.float64:
            max_val = self.image_rgb.max()
            if max_val > 0:
                self.display_image = (self.image_rgb / max_val * 255).astype(np.uint8)
            else:
                self.display_image = self.image_rgb.astype(np.uint8)
        else:
            self.display_image = self.image_rgb
        
        self.title = title
        self.height, self.width = self.display_image.shape[:2]
        
        # Selection state
        self.polaris_pos: Optional[Tuple[float, float]] = None
        self.second_star_pos: Optional[Tuple[float, float]] = None
        self.selection_complete = False
        self.cancelled = False
        
        # Visual elements
        self.polaris_marker = None
        self.star2_marker = None
        self.crosshairs = []
        
        # Zoom state
        self.zoom_factor = 1.0
        self.base_xlim = (0, self.width)
        self.base_ylim = (self.height, 0)  # Inverted for image display
        
    def _draw_crosshair(self, ax, x: float, y: float, color: str, label: str) -> List:
        """Draw a crosshair at the specified position."""
        elements = []
        
        # Crosshair lines (extend across visible area)
        line_h = ax.axhline(y=y, color=color, linewidth=0.5, alpha=0.7)
        line_v = ax.axvline(x=x, color=color, linewidth=0.5, alpha=0.7)
        elements.extend([line_h, line_v])
        
        # Center circle
        circle = Circle((x, y), radius=15, fill=False, color=color, linewidth=2)
        ax.add_patch(circle)
        elements.append(circle)
        
        # Label
        text = ax.annotate(
            label,
            xy=(x, y),
            xytext=(10, 10),
            textcoords='offset points',
            color=color,
            fontsize=10,
            fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.3', facecolor='black', alpha=0.7)
        )
        elements.append(text)
        
        return elements
    
    def _update_display(self, ax):
        """Update the display with current selections."""
        # Clear old markers
        for elem in self.crosshairs:
            try:
                elem.remove()
            except:
                pass
        self.crosshairs = []
        
        # Draw Polaris marker if selected
        if self.polaris_pos is not None:
            elements = self._draw_crosshair(
                ax, self.polaris_pos[0], self.polaris_pos[1],
                '#00FF00', 'Polaris'
            )
            self.crosshairs.extend(elements)
        
        # Draw second star marker if selected
        if self.second_star_pos is not None:
            elements = self._draw_crosshair(
                ax, self.second_star_pos[0], self.second_star_pos[1],
                '#FF6600', 'Star 2'
            )
            self.crosshairs.extend(elements)
        
        # Update title with instructions
        if self.polaris_pos is None:
            ax.set_title(f"{self.title}\nClick on Polaris (North Star)", fontsize=12)
        elif self.second_star_pos is None:
            ax.set_title(
                f"{self.title}\nPolaris selected. Click second star or press ENTER to continue.",
                fontsize=12
            )
        else:
            ax.set_title(
                f"{self.title}\nBoth stars selected. Press ENTER to confirm or right-click to undo.",
                fontsize=12
            )
        
        ax.figure.canvas.draw_idle()
    
    def _on_scroll(self, event, ax):
        """Handle mouse wheel zoom."""
        if event.inaxes != ax:
            return
        
        # Zoom factor per scroll step
        base_scale = 1.2
        
        if event.button == 'up':
            scale_factor = 1 / base_scale
        elif event.button == 'down':
            scale_factor = base_scale
        else:
            return
        
        # Get current limits
        xlim = ax.get_xlim()
        ylim = ax.get_ylim()
        
        # Get cursor position in data coordinates
        xdata = event.xdata
        ydata = event.ydata
        
        # Calculate new limits centered on cursor
        new_width = (xlim[1] - xlim[0]) * scale_factor
        new_height = (ylim[0] - ylim[1]) * scale_factor  # Note: ylim is inverted
        
        # Maintain cursor position relative to view
        rel_x = (xdata - xlim[0]) / (xlim[1] - xlim[0])
        rel_y = (ydata - ylim[1]) / (ylim[0] - ylim[1])
        
        new_xlim = (
            xdata - new_width * rel_x,
            xdata + new_width * (1 - rel_x)
        )
        new_ylim = (
            ydata + new_height * (1 - rel_y),
            ydata - new_height * rel_y
        )
        
        # Clamp to image bounds
        new_xlim = (max(0, new_xlim[0]), min(self.width, new_xlim[1]))
        new_ylim = (min(self.height, new_ylim[0]), max(0, new_ylim[1]))
        
        # Apply new limits
        ax.set_xlim(new_xlim)
        ax.set_ylim(new_ylim)
        
        self._update_display(ax)
    
    def _on_click(self, event, ax):
        """Handle mouse click for star selection."""
        if event.inaxes != ax:
            return
        
        if event.button == MouseButton.LEFT:
            x, y = event.xdata, event.ydata
            
            if self.polaris_pos is None:
                # First click: select Polaris
                self.polaris_pos = (x, y)
                if VERBOSE:
                    print(f"Polaris selected at ({x:.2f}, {y:.2f})")
            elif self.second_star_pos is None:
                # Second click: select optional second star
                self.second_star_pos = (x, y)
                if VERBOSE:
                    print(f"Second star selected at ({x:.2f}, {y:.2f})")
            
            self._update_display(ax)
            
        elif event.button == MouseButton.RIGHT:
            # Right click: undo last selection
            if self.second_star_pos is not None:
                self.second_star_pos = None
                if VERBOSE:
                    print("Second star selection removed")
            elif self.polaris_pos is not None:
                self.polaris_pos = None
                if VERBOSE:
                    print("Polaris selection removed")
            
            self._update_display(ax)
    
    def _on_key(self, event, fig):
        """Handle keyboard input."""
        if event.key == 'enter' or event.key == 'return':
            if self.polaris_pos is not None:
                self.selection_complete = True
                plt.close(fig)
        elif event.key == 'escape':
            self.cancelled = True
            plt.close(fig)
    
    def run(self) -> Optional[StarSelection]:
        """
        Launch the interactive star selector.
        
        Returns:
            StarSelection object with selected positions, or None if cancelled
        """
        # Create figure and axis
        fig, ax = plt.subplots(figsize=(14, 10))
        
        # Display image
        ax.imshow(self.display_image)
        ax.set_xlim(self.base_xlim)
        ax.set_ylim(self.base_ylim)
        
        # Initial instructions
        ax.set_title(f"{self.title}\nScroll to zoom, Click on Polaris (North Star)", fontsize=12)
        
        # Status bar at bottom
        fig.text(
            0.5, 0.02,
            "Controls: Scroll=Zoom | Left Click=Select | Right Click=Undo | Enter=Confirm | Esc=Cancel",
            ha='center', fontsize=9, color='gray'
        )
        
        # Connect event handlers
        fig.canvas.mpl_connect('scroll_event', lambda e: self._on_scroll(e, ax))
        fig.canvas.mpl_connect('button_press_event', lambda e: self._on_click(e, ax))
        fig.canvas.mpl_connect('key_press_event', lambda e: self._on_key(e, fig))
        
        # Show the window
        plt.tight_layout()
        plt.subplots_adjust(bottom=0.08)
        plt.show()
        
        # Return results
        if self.cancelled or self.polaris_pos is None:
            return None
        
        return StarSelection(
            polaris=self.polaris_pos,
            second_star=self.second_star_pos
        )


def select_stars(
    image: np.ndarray,
    title: str = "Star Trail Aligner - Select Stars"
) -> Optional[StarSelection]:
    """
    Open an interactive window for the user to select stars.
    
    This is the main entry point for the GUI module.
    
    Args:
        image: BGR image as numpy array (first frame of the sequence)
        title: Window title
        
    Returns:
        StarSelection object with:
        - polaris: (x, y) coordinates of Polaris
        - second_star: Optional (x, y) coordinates of second star for rotation correction
        
        Returns None if user cancels the selection.
    
    Example:
        >>> from modules import io_utils, gui
        >>> img = io_utils.load_image("frame_001.jpg")
        >>> selection = gui.select_stars(img)
        >>> if selection:
        ...     print(f"Polaris at: {selection.polaris}")
    """
    selector = ZoomableStarSelector(image, title)
    return selector.run()


def adjust_brightness_for_display(image: np.ndarray, percentile: float = 99.5) -> np.ndarray:
    """
    Adjust image brightness for better star visibility during selection.
    
    Applies a simple stretch to make dim stars more visible.
    
    Args:
        image: Input image (BGR)
        percentile: Clip highlights at this percentile
        
    Returns:
        Brightness-adjusted image for display
    """
    # Convert to float
    img_float = image.astype(np.float32)
    
    # Find the percentile value
    upper = np.percentile(img_float, percentile)
    lower = np.percentile(img_float, 100 - percentile)
    
    # Stretch
    if upper > lower:
        stretched = (img_float - lower) / (upper - lower)
        stretched = np.clip(stretched, 0, 1)
    else:
        stretched = img_float / img_float.max() if img_float.max() > 0 else img_float
    
    # Convert to 8-bit
    return (stretched * 255).astype(np.uint8)
