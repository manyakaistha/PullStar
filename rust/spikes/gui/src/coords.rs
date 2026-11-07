//! Mathematical coordinate transformations between screen space and image space.
//!
//! Follows the PullStar coordinate convention:
//! - Pixel coordinates are f64 and refer to pixel centers.
//! - The first pixel center is (0.0, 0.0), matching OpenCV and pullstar-domain.
//! - Screen positions are logical points in egui coordinates.

use egui::{Pos2, Rect, Vec2};

/// Transform state representing zoom and pan in the viewfinder.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ViewportTransform {
    /// Zoom factor (1.0 = 1 image pixel per logical point).
    pub zoom: f32,
    /// Offset of the image top-left (pixel -0.5, -0.5) from the viewport top-left.
    pub pan: Vec2,
}

impl Default for ViewportTransform {
    fn default() -> Self {
        Self {
            zoom: 1.0,
            pan: Vec2::ZERO,
        }
    }
}

impl ViewportTransform {
    /// Calculate the transform that fits an image of size `(img_w, img_h)` nicely
    /// inside a viewport `rect` with padding.
    pub fn fit_inside(rect: Rect, img_w: f32, img_h: f32, padding: f32) -> Self {
        if img_w <= 0.0 || img_h <= 0.0 || rect.width() <= 0.0 || rect.height() <= 0.0 {
            return Self::default();
        }
        let avail_w = (rect.width() - padding * 2.0).max(10.0);
        let avail_h = (rect.height() - padding * 2.0).max(10.0);

        let scale_x = avail_w / img_w;
        let scale_y = avail_h / img_h;
        let zoom = scale_x.min(scale_y).clamp(0.01, 100.0);

        let centered_x = padding + (avail_w - img_w * zoom) * 0.5;
        let centered_y = padding + (avail_h - img_h * zoom) * 0.5;

        Self {
            zoom,
            pan: Vec2::new(centered_x, centered_y),
        }
    }

    /// Zoom in or out centered at a specific screen cursor position.
    /// Invariant: the image pixel under `cursor` remains at `cursor` after zooming.
    pub fn zoom_at_cursor(&mut self, factor: f32, cursor: Pos2, viewport_min: Pos2) {
        let old_zoom = self.zoom;
        let new_zoom = (old_zoom * factor).clamp(0.05, 50.0);
        if (new_zoom - old_zoom).abs() < f32::EPSILON {
            return;
        }

        let cursor_rel = cursor - viewport_min;
        // Invariant: pan_new = cursor_rel - (cursor_rel - pan_old) * (new_zoom / old_zoom)
        self.pan = cursor_rel - (cursor_rel - self.pan) * (new_zoom / old_zoom);
        self.zoom = new_zoom;
    }

    /// Map screen position (logical points) to image pixel coordinate.
    pub fn screen_to_image(&self, screen_pos: Pos2, viewport_min: Pos2) -> (f64, f64) {
        let rel_x = screen_pos.x - viewport_min.x - self.pan.x;
        let rel_y = screen_pos.y - viewport_min.y - self.pan.y;

        let img_x = (rel_x / self.zoom) as f64;
        let img_y = (rel_y / self.zoom) as f64;

        (img_x, img_y)
    }

    /// Map image pixel coordinate to screen position (logical points).
    pub fn image_to_screen(&self, img_x: f64, img_y: f64, viewport_min: Pos2) -> Pos2 {
        let sx = viewport_min.x + self.pan.x + (img_x as f32) * self.zoom;
        let sy = viewport_min.y + self.pan.y + (img_y as f32) * self.zoom;
        Pos2::new(sx, sy)
    }

    /// Check whether an image coordinate is within the image bounds `(0..img_w, 0..img_h)`.
    pub fn is_inside_image(img_x: f64, img_y: f64, img_w: u32, img_h: u32) -> bool {
        img_x >= 0.0 && img_y >= 0.0 && img_x < (img_w as f64) && img_y < (img_h as f64)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_roundtrip_coordinate_mapping() {
        let transform = ViewportTransform {
            zoom: 2.35,
            pan: Vec2::new(145.2, -32.8),
        };
        let viewport_min = Pos2::new(200.0, 100.0);

        let test_points = [
            (0.0, 0.0),
            (1920.0, 1080.0),
            (960.5, 540.25),
            (123.456, 789.012),
        ];

        for &(ix, iy) in &test_points {
            let screen = transform.image_to_screen(ix, iy, viewport_min);
            let (back_x, back_y) = transform.screen_to_image(screen, viewport_min);

            assert!(
                (back_x - ix).abs() < 1e-4,
                "X roundtrip mismatch: expected {ix}, got {back_x}"
            );
            assert!(
                (back_y - iy).abs() < 1e-4,
                "Y roundtrip mismatch: expected {iy}, got {back_y}"
            );
        }
    }

    #[test]
    fn test_zoom_at_cursor_preserves_anchor() {
        let mut transform = ViewportTransform {
            zoom: 1.0,
            pan: Vec2::new(50.0, 50.0),
        };
        let viewport_min = Pos2::new(100.0, 100.0);
        let cursor = Pos2::new(350.0, 280.0);

        let (before_x, before_y) = transform.screen_to_image(cursor, viewport_min);

        // Zoom in by 1.5x
        transform.zoom_at_cursor(1.5, cursor, viewport_min);

        let (after_x, after_y) = transform.screen_to_image(cursor, viewport_min);

        assert!(
            (after_x - before_x).abs() < 1e-4,
            "Anchor X drifted: before {before_x}, after {after_x}"
        );
        assert!(
            (after_y - before_y).abs() < 1e-4,
            "Anchor Y drifted: before {before_y}, after {after_y}"
        );
    }
}
