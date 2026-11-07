//! Large celestial viewfinder component with zoom, pan, high-DPI texture rendering,
//! pixel coordinate readout, and reference star overlay reticles.

use crate::coords::ViewportTransform;
use crate::theme::colors;
use egui::{
    pos2, vec2, Color32, ColorImage, CornerRadius, Key, PointerButton, Pos2, Rect, Response,
    Sense, Stroke, StrokeKind, TextureHandle, TextureOptions, Ui,
};
use std::f32::consts::PI;

/// Reference star target in image coordinates.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct StarMarker {
    pub x: f64,
    pub y: f64,
}

/// Selection mode for manual star placement.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ReticleMode {
    Polaris,
    RefStar2,
}

/// State of the celestial viewfinder.
pub struct CelestialViewfinder {
    pub transform: ViewportTransform,
    pub polaris: Option<StarMarker>,
    pub ref_star_2: Option<StarMarker>,
    pub mode: ReticleMode,
    pub cursor_img_coords: Option<(f64, f64)>,
    pub is_dragging: bool,
    drag_start: Pos2,
    initial_fit_done: bool,
}

impl Default for CelestialViewfinder {
    fn default() -> Self {
        Self {
            transform: ViewportTransform::default(),
            polaris: Some(StarMarker { x: 960.0, y: 540.0 }),
            ref_star_2: Some(StarMarker {
                x: 1280.0,
                y: 360.0,
            }),
            mode: ReticleMode::Polaris,
            cursor_img_coords: None,
            is_dragging: false,
            drag_start: Pos2::ZERO,
            initial_fit_done: false,
        }
    }
}

impl CelestialViewfinder {
    pub fn show(
        &mut self,
        ui: &mut Ui,
        image_data: &ColorImage,
        texture: &mut Option<TextureHandle>,
    ) -> Response {
        let (img_w, img_h) = (image_data.width() as f32, image_data.height() as f32);

        // Upload or update texture if needed
        let texture_handle = texture.get_or_insert_with(|| {
            ui.ctx().load_texture(
                "viewfinder_image",
                image_data.clone(),
                TextureOptions::LINEAR,
            )
        });

        // Top toolbar of the viewfinder
        self.render_toolbar(ui, img_w, img_h);

        // Canvas viewport area
        let available_size = ui.available_size();
        let (rect, response) =
            ui.allocate_exact_size(available_size, Sense::click_and_drag());

        // Perform initial auto-fit to container once
        if !self.initial_fit_done && rect.width() > 50.0 && rect.height() > 50.0 {
            self.transform = ViewportTransform::fit_inside(rect, img_w, img_h, 16.0);
            self.initial_fit_done = true;
        }

        // Pointer interactions: Wheel zoom, drag pan, click reticle placement
        self.handle_interactions(&response, ui, rect, img_w, img_h);

        // Painter rendering
        let painter = ui.painter_at(rect);

        // 1. Viewport background
        painter.rect_filled(rect, CornerRadius::same(12), colors::WORKSPACE_BG);
        painter.rect_stroke(rect, CornerRadius::same(12), Stroke::new(1.0, colors::GLASS_LINE), StrokeKind::Inside);

        // 2. Subtle coordinate grid
        let grid_spacing = 80.0;
        let mut gx = rect.min.x;
        while gx <= rect.max.x {
            painter.line_segment(
                [pos2(gx, rect.min.y), pos2(gx, rect.max.y)],
                Stroke::new(1.0, Color32::from_rgba_premultiplied(255, 255, 255, 9)),
            );
            gx += grid_spacing;
        }
        let mut gy = rect.min.y;
        while gy <= rect.max.y {
            painter.line_segment(
                [pos2(rect.min.x, gy), pos2(rect.max.x, gy)],
                Stroke::new(1.0, Color32::from_rgba_premultiplied(255, 255, 255, 9)),
            );
            gy += grid_spacing;
        }

        // 3. Render the image with clipping to the canvas rect
        let image_rect = Rect::from_min_size(
            pos2(
                rect.min.x + self.transform.pan.x,
                rect.min.y + self.transform.pan.y,
            ),
            vec2(img_w * self.transform.zoom, img_h * self.transform.zoom),
        );

        let image_painter = painter.with_clip_rect(rect);
        image_painter.image(
            texture_handle.id(),
            image_rect,
            Rect::from_min_max(pos2(0.0, 0.0), pos2(1.0, 1.0)),
            Color32::WHITE,
        );

        // 4. Connecting line between Polaris and Ref Star 2
        if let (Some(p1), Some(p2)) = (self.polaris, self.ref_star_2) {
            let s1 = self.transform.image_to_screen(p1.x, p1.y, rect.min);
            let s2 = self.transform.image_to_screen(p2.x, p2.y, rect.min);

            // Draw connecting dashed / translucent vector line
            image_painter.line_segment(
                [s1, s2],
                Stroke::new(1.5, Color32::from_rgba_premultiplied(255, 255, 255, 140)),
            );

            // Angle readout
            let dx = (p2.x - p1.x) as f32;
            let dy = (p2.y - p1.y) as f32;
            let angle_deg = ((dy.atan2(dx) * 180.0 / PI) + 360.0) % 360.0;
            let mid = pos2((s1.x + s2.x) * 0.5 + 12.0, (s1.y + s2.y) * 0.5 - 12.0);

            image_painter.rect_filled(
                Rect::from_min_size(mid - vec2(4.0, 2.0), vec2(60.0, 16.0)),
                CornerRadius::same(4),
                Color32::from_rgba_premultiplied(5, 5, 5, 200),
            );
            image_painter.text(
                mid,
                egui::Align2::LEFT_TOP,
                format!("{angle_deg:.2}°"),
                egui::FontId::monospace(11.0),
                Color32::WHITE,
            );
        }

        // 5. Reticles for reference stars
        if let Some(p) = self.polaris {
            self.draw_reticle(&image_painter, p, rect.min, colors::RETICLE_POLARIS, "POLARIS");
        }
        if let Some(p) = self.ref_star_2 {
            self.draw_reticle(&image_painter, p, rect.min, colors::RETICLE_REF2, "REF STAR 2");
        }

        // 6. HUD overlay badges inside canvas: Pixel readout and Zoom level
        self.render_hud_readouts(&painter, rect, img_w, img_h);

        response
    }

    fn render_toolbar(&mut self, ui: &mut Ui, img_w: f32, img_h: f32) {
        ui.horizontal(|ui| {
            ui.label(
                egui::RichText::new("VIEWFINDER")
                    .color(colors::TEXT_MUTED)
                    .size(11.0)
                    .strong(),
            );

            ui.separator();

            // Placement Mode Selector
            ui.label(egui::RichText::new("Place:").size(11.0).color(colors::TEXT_SECONDARY));
            if ui
                .selectable_label(
                    self.mode == ReticleMode::Polaris,
                    egui::RichText::new("● Polaris (Primary)").color(colors::RETICLE_POLARIS),
                )
                .clicked()
            {
                self.mode = ReticleMode::Polaris;
            }

            if ui
                .selectable_label(
                    self.mode == ReticleMode::RefStar2,
                    egui::RichText::new("● Ref Star 2 (Secondary)").color(colors::RETICLE_REF2),
                )
                .clicked()
            {
                self.mode = ReticleMode::RefStar2;
            }

            ui.separator();

            // Quick Zoom & Reset Buttons
            if ui.button("➖").on_hover_text("Zoom out").clicked() {
                self.transform.zoom = (self.transform.zoom * 0.8).clamp(0.05, 50.0);
            }
            if ui.button("➕").on_hover_text("Zoom in").clicked() {
                self.transform.zoom = (self.transform.zoom * 1.25).clamp(0.05, 50.0);
            }
            if ui.button("1:1").on_hover_text("Actual 100% size").clicked() {
                self.transform.zoom = 1.0;
            }
            if ui.button("Fit").on_hover_text("Fit frame to window").clicked() {
                self.initial_fit_done = false;
            }
            if ui.button("Reset View").clicked() {
                self.transform = ViewportTransform::default();
                self.initial_fit_done = false;
            }

            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                ui.label(
                    egui::RichText::new(format!("Frame size: {:.0} × {:.0} px", img_w, img_h))
                        .color(colors::TEXT_MUTED)
                        .size(11.0),
                );
            });
        });
    }

    fn handle_interactions(
        &mut self,
        response: &Response,
        ui: &mut Ui,
        rect: Rect,
        img_w: f32,
        img_h: f32,
    ) {
        // Track mouse position and compute image pixel coordinate
        if let Some(hover_pos) = response.hover_pos() {
            let (ix, iy) = self.transform.screen_to_image(hover_pos, rect.min);
            if ix >= 0.0 && iy >= 0.0 && ix < img_w as f64 && iy < img_h as f64 {
                self.cursor_img_coords = Some((ix, iy));
            } else {
                self.cursor_img_coords = None;
            }

            // Mouse wheel zoom centered at cursor
            let scroll_delta = ui.input(|i| i.smooth_scroll_delta.y);
            if scroll_delta.abs() > 0.0 {
                let zoom_factor = (1.0 + scroll_delta * 0.005).clamp(0.5, 2.0);
                self.transform.zoom_at_cursor(zoom_factor, hover_pos, rect.min);
            }
        } else {
            self.cursor_img_coords = None;
        }

        // Panning: Middle mouse drag, right mouse drag, or Shift+Left drag
        let input = ui.input(|i| i.clone());
        let middle_down = input.pointer.button_down(PointerButton::Middle);
        let secondary_down = input.pointer.button_down(PointerButton::Secondary);
        let shift_down = input.modifiers.shift;

        if response.dragged() && (middle_down || secondary_down || shift_down) {
            self.transform.pan += response.drag_delta();
        } else if response.clicked() {
            // Left click to place reticle at exact image coordinate
            if let Some(pos) = response.interact_pointer_pos() {
                let (ix, iy) = self.transform.screen_to_image(pos, rect.min);
                if ix >= 0.0 && iy >= 0.0 && ix < img_w as f64 && iy < img_h as f64 {
                    match self.mode {
                        ReticleMode::Polaris => {
                            self.polaris = Some(StarMarker { x: ix, y: iy });
                        }
                        ReticleMode::RefStar2 => {
                            self.ref_star_2 = Some(StarMarker { x: ix, y: iy });
                        }
                    }
                }
            }
        }

        // Keyboard hotkeys for accessibility & power users
        if input.key_pressed(Key::Num1) {
            self.mode = ReticleMode::Polaris;
        }
        if input.key_pressed(Key::Num2) {
            self.mode = ReticleMode::RefStar2;
        }
        if input.key_pressed(Key::R) {
            self.initial_fit_done = false;
        }
    }

    fn draw_reticle(
        &self,
        painter: &egui::Painter,
        marker: StarMarker,
        viewport_min: Pos2,
        color: Color32,
        label: &str,
    ) {
        let center = self.transform.image_to_screen(marker.x, marker.y, viewport_min);
        let size = 26.0;
        let inner_size = 8.0;

        // Crosshairs with inner gap
        painter.line_segment(
            [pos2(center.x - size, center.y), pos2(center.x - inner_size, center.y)],
            Stroke::new(1.8, color),
        );
        painter.line_segment(
            [pos2(center.x + inner_size, center.y), pos2(center.x + size, center.y)],
            Stroke::new(1.8, color),
        );
        painter.line_segment(
            [pos2(center.x, center.y - size), pos2(center.x, center.y - inner_size)],
            Stroke::new(1.8, color),
        );
        painter.line_segment(
            [pos2(center.x, center.y + inner_size), pos2(center.x, center.y + size)],
            Stroke::new(1.8, color),
        );

        // Center dot
        painter.circle_filled(center, 2.5, color);

        // Outer Target Ring
        painter.circle_stroke(center, size * 0.72, Stroke::new(1.5, color));

        // Coordinate readout pill badge
        let text = format!("{label} [{:.1}, {:.1}]", marker.x, marker.y);
        let pill_min = pos2(center.x + size + 6.0, center.y - 10.0);
        let text_size = 10.5;

        painter.rect_filled(
            Rect::from_min_size(pill_min, vec2((text.len() as f32) * 6.8 + 10.0, 18.0)),
            CornerRadius::same(4),
            Color32::from_rgba_premultiplied(5, 5, 5, 210),
        );
        painter.rect_stroke(
            Rect::from_min_size(pill_min, vec2((text.len() as f32) * 6.8 + 10.0, 18.0)),
            CornerRadius::same(4),
            Stroke::new(1.0, color),
            StrokeKind::Inside,
        );
        painter.text(
            pill_min + vec2(5.0, 2.0),
            egui::Align2::LEFT_TOP,
            text,
            egui::FontId::monospace(text_size),
            color,
        );
    }

    fn render_hud_readouts(&self, painter: &egui::Painter, rect: Rect, _img_w: f32, _img_h: f32) {
        // Bottom-left: Live cursor pixel readout
        let cursor_text = if let Some((cx, cy)) = self.cursor_img_coords {
            format!("PIXEL: X: {:.1}  Y: {:.1}", cx, cy)
        } else {
            "PIXEL: ---".to_string()
        };

        let badge_rect = Rect::from_min_size(
            pos2(rect.min.x + 12.0, rect.max.y - 32.0),
            vec2(190.0, 22.0),
        );
        painter.rect_filled(
            badge_rect,
            CornerRadius::same(4),
            Color32::from_rgba_premultiplied(10, 10, 12, 220),
        );
        painter.rect_stroke(
            badge_rect,
            CornerRadius::same(4),
            Stroke::new(1.0, colors::GLASS_LINE),
            StrokeKind::Inside,
        );
        painter.text(
            badge_rect.min + vec2(8.0, 4.0),
            egui::Align2::LEFT_TOP,
            cursor_text,
            egui::FontId::monospace(11.0),
            colors::TEXT_PRIMARY,
        );

        // Bottom-right: Zoom percentage badge
        let zoom_pct = (self.transform.zoom * 100.0).round() as i32;
        let zoom_text = format!("ZOOM: {zoom_pct}%");
        let zoom_rect = Rect::from_min_size(
            pos2(rect.max.x - 90.0, rect.max.y - 32.0),
            vec2(78.0, 22.0),
        );
        painter.rect_filled(
            zoom_rect,
            CornerRadius::same(4),
            Color32::from_rgba_premultiplied(10, 10, 12, 220),
        );
        painter.rect_stroke(
            zoom_rect,
            CornerRadius::same(4),
            Stroke::new(1.0, colors::GLASS_LINE),
            StrokeKind::Inside,
        );
        painter.text(
            zoom_rect.min + vec2(8.0, 4.0),
            egui::Align2::LEFT_TOP,
            zoom_text,
            egui::FontId::monospace(11.0),
            colors::ACCENT,
        );
    }
}
