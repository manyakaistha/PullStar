//! Image fixtures, test star fields, and asset loaders for the spike.

use egui::ColorImage;
use std::path::{Path, PathBuf};

/// Generate a high-DPI synthetic star field image (1920 x 1080).
/// Includes Polaris at (960.0, 540.0) and reference stars to demonstrate overlays.
pub fn generate_synthetic_starfield(width: u32, height: u32) -> ColorImage {
    let mut pixels = vec![egui::Color32::from_rgb(4, 5, 8); (width * height) as usize];

    // Seeded pseudo-random stars
    let mut seed: u64 = 0x5741525F53544152;
    let mut next_rand = || {
        seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1);
        ((seed >> 33) & 0xFFFF) as f32 / 65535.0
    };

    // Faint night sky background noise and gradient
    for y in 0..height {
        let grad = (y as f32 / height as f32) * 10.0;
        for x in 0..width {
            let idx = (y * width + x) as usize;
            let n = (next_rand() * 4.0) as u8;
            let b = (grad as u8).saturating_add(n).saturating_add(6);
            pixels[idx] = egui::Color32::from_rgb(b / 2, b / 2, b);
        }
    }

    // Draw point stars
    for _ in 0..450 {
        let sx = (next_rand() * (width as f32 - 10.0) + 5.0) as u32;
        let sy = (next_rand() * (height as f32 - 10.0) + 5.0) as u32;
        let brightness = (next_rand() * 180.0 + 75.0) as u8;
        let warm = next_rand() > 0.6;
        let (r, g, b) = if warm {
            (brightness, brightness.saturating_sub(15), brightness.saturating_sub(40))
        } else {
            (brightness.saturating_sub(20), brightness.saturating_sub(10), brightness)
        };
        let idx = (sy * width + sx) as usize;
        pixels[idx] = egui::Color32::from_rgb(r, g, b);

        // Subpixel glow for brighter stars
        if brightness > 180 {
            let glow = brightness / 3;
            for (dx, dy) in [(-1, 0), (1, 0), (0, -1), (0, 1)] {
                let gx = (sx as i32 + dx) as u32;
                let gy = (sy as i32 + dy) as u32;
                if gx < width && gy < height {
                    let g_idx = (gy * width + gx) as usize;
                    pixels[g_idx] = egui::Color32::from_rgb(
                        pixels[g_idx].r().saturating_add(glow),
                        pixels[g_idx].g().saturating_add(glow),
                        pixels[g_idx].b().saturating_add(glow),
                    );
                }
            }
        }
    }

    // Prominent Polaris star at (960, 540)
    let px = (width / 2).min(width - 1);
    let py = (height / 2).min(height - 1);
    draw_star_burst(&mut pixels, width, height, px, py, 255, 250, 240, 5);

    // Prominent Ref Star 2 at (1280, 360)
    let rx = (width * 2 / 3).min(width - 1);
    let ry = (height / 3).min(height - 1);
    draw_star_burst(&mut pixels, width, height, rx, ry, 255, 230, 170, 4);

    ColorImage::new([width as usize, height as usize], pixels)
}

fn draw_star_burst(
    pixels: &mut [egui::Color32],
    w: u32,
    h: u32,
    cx: u32,
    cy: u32,
    r: u8,
    g: u8,
    b: u8,
    radius: i32,
) {
    for dy in -radius..=radius {
        for dx in -radius..=radius {
            let dist_sq = dx * dx + dy * dy;
            if dist_sq <= radius * radius {
                let x = cx as i32 + dx;
                let y = cy as i32 + dy;
                if x >= 0 && x < w as i32 && y >= 0 && y < h as i32 {
                    let factor = 1.0 - (dist_sq as f32).sqrt() / (radius as f32 + 0.1);
                    let pr = (r as f32 * factor) as u8;
                    let pg = (g as f32 * factor) as u8;
                    let pb = (b as f32 * factor) as u8;
                    let idx = (y as u32 * w + x as u32) as usize;
                    pixels[idx] = egui::Color32::from_rgb(
                        pixels[idx].r().max(pr),
                        pixels[idx].g().max(pg),
                        pixels[idx].b().max(pb),
                    );
                }
            }
        }
    }
}

/// Try to load a real image file into ColorImage.
pub fn load_image_from_path(path: &Path) -> Result<ColorImage, String> {
    let img = image::open(path).map_err(|e| format!("Failed to open {}: {e}", path.display()))?;
    let rgba = img.to_rgba8();
    let size = [rgba.width() as usize, rgba.height() as usize];
    let pixels = rgba
        .pixels()
        .map(|p| egui::Color32::from_rgba_unmultiplied(p[0], p[1], p[2], p[3]))
        .collect();
    Ok(ColorImage::new(size, pixels))
}

/// Create a thumbnail sized ColorImage from an image path.
pub fn create_thumbnail(path: &Path, max_w: u32, max_h: u32) -> Result<ColorImage, String> {
    let img = image::open(path).map_err(|e| format!("Thumbnail read failed: {e}"))?;
    let thumb = img.thumbnail(max_w, max_h).to_rgba8();
    let size = [thumb.width() as usize, thumb.height() as usize];
    let pixels = thumb
        .pixels()
        .map(|p| egui::Color32::from_rgba_unmultiplied(p[0], p[1], p[2], p[3]))
        .collect();
    Ok(ColorImage::new(size, pixels))
}

/// Scan a directory for image files, sorted by name or timestamp.
pub fn scan_directory(dir: &Path) -> Vec<PathBuf> {
    let mut entries = Vec::new();
    if let Ok(read_dir) = std::fs::read_dir(dir) {
        for entry in read_dir.flatten() {
            let path = entry.path();
            if let Some(ext) = path.extension().and_then(|s| s.to_str()) {
                let ext_lower = ext.to_lowercase();
                if matches!(
                    ext_lower.as_str(),
                    "jpg" | "jpeg" | "png" | "tiff" | "tif" | "cr2" | "nef" | "arw" | "dng"
                ) {
                    entries.push(path);
                }
            }
        }
    }
    entries.sort();
    entries
}
