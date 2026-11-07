//! Ordered filmstrip component for sequence frames with lazy thumbnail placeholders.

use crate::theme::colors;
use egui::{
    pos2, vec2, Color32, ColorImage, CornerRadius, Rect, Response, ScrollArea, Stroke, StrokeKind,
    TextureHandle, TextureOptions, Ui,
};
use std::collections::HashMap;
use std::path::{Path, PathBuf};

/// Filmstrip frame descriptor.
#[derive(Clone, Debug)]
pub struct FilmstripFrame {
    pub index: usize,
    pub path: PathBuf,
    pub filename: String,
    pub loaded_thumbnail: Option<ColorImage>,
}

/// Filmstrip UI state.
pub struct Filmstrip {
    pub frames: Vec<FilmstripFrame>,
    pub selected_index: usize,
    thumbnail_textures: HashMap<usize, TextureHandle>,
}

impl Default for Filmstrip {
    fn default() -> Self {
        Self {
            frames: Vec::new(),
            selected_index: 0,
            thumbnail_textures: HashMap::new(),
        }
    }
}

impl Filmstrip {
    /// Populate filmstrip with real image paths from a directory or fixtures.
    pub fn set_files(&mut self, paths: &[PathBuf]) {
        self.frames = paths
            .iter()
            .enumerate()
            .map(|(i, p)| {
                let filename = p
                    .file_name()
                    .and_then(|s| s.to_str())
                    .unwrap_or("image.raw")
                    .to_string();
                FilmstripFrame {
                    index: i,
                    path: p.clone(),
                    filename,
                    loaded_thumbnail: None,
                }
            })
            .collect();
        self.selected_index = 0;
        self.thumbnail_textures.clear();
    }

    /// Render the horizontal filmstrip bar.
    pub fn show(&mut self, ui: &mut Ui) -> Option<usize> {
        let mut newly_selected = None;

        ui.horizontal(|ui| {
            ui.label(
                egui::RichText::new(format!("FILMSTRIP ({} frames)", self.frames.len()))
                    .color(colors::TEXT_MUTED)
                    .size(11.0)
                    .strong(),
            );

            if let Some(frame) = self.frames.get(self.selected_index) {
                ui.label(
                    egui::RichText::new(format!("— Active: {}", frame.filename))
                        .color(colors::TEXT_SECONDARY)
                        .size(11.0),
                );
            }
        });

        ui.add_space(4.0);

        ScrollArea::horizontal()
            .max_height(96.0)
            .auto_shrink([false, false])
            .show(ui, |ui| {
                ui.horizontal(|ui| {
                    for i in 0..self.frames.len() {
                        let is_selected = i == self.selected_index;
                        let response = self.render_frame_card(ui, i, is_selected);
                        if response.clicked() {
                            self.selected_index = i;
                            newly_selected = Some(i);
                        }
                    }
                });
            });

        newly_selected
    }

    fn render_frame_card(&mut self, ui: &mut Ui, index: usize, is_selected: bool) -> Response {
        let card_w = 90.0;
        let card_h = 74.0;
        let (rect, response) = ui.allocate_exact_size(vec2(card_w, card_h), egui::Sense::click());

        let painter = ui.painter_at(rect);

        // Background
        let bg_color = if is_selected {
            colors::SURFACE_ELEVATED
        } else if response.hovered() {
            colors::SURFACE_SOLID
        } else {
            colors::WORKSPACE_BG
        };
        painter.rect_filled(rect, CornerRadius::same(6), bg_color);

        // Border: Accent stroke if selected
        let stroke = if is_selected {
            Stroke::new(2.0, colors::RETICLE_POLARIS)
        } else if response.hovered() {
            Stroke::new(1.0, colors::ACCENT_LINE)
        } else {
            Stroke::new(1.0, colors::GLASS_LINE)
        };
        painter.rect_stroke(rect, CornerRadius::same(6), stroke, StrokeKind::Inside);

        // Lazy thumbnail loading / placeholder
        let frame = &mut self.frames[index];
        let thumb_rect = Rect::from_min_size(rect.min + vec2(4.0, 4.0), vec2(card_w - 8.0, 48.0));

        // Load thumbnail lazily if not already present
        if frame.loaded_thumbnail.is_none() {
            if let Ok(img) = crate::fixtures::create_thumbnail(&frame.path, 120, 80) {
                frame.loaded_thumbnail = Some(img);
            }
        }

        if let Some(thumb_data) = &frame.loaded_thumbnail {
            let texture = self
                .thumbnail_textures
                .entry(index)
                .or_insert_with(|| {
                    ui.ctx().load_texture(
                        format!("thumb_{index}"),
                        thumb_data.clone(),
                        TextureOptions::LINEAR,
                    )
                });
            painter.image(
                texture.id(),
                thumb_rect,
                Rect::from_min_max(pos2(0.0, 0.0), pos2(1.0, 1.0)),
                Color32::WHITE,
            );
        } else {
            // Placeholder: night sky gradient and "FRAME" badge
            painter.rect_filled(
                thumb_rect,
                CornerRadius::same(4),
                Color32::from_rgb(12, 14, 18),
            );
            painter.text(
                thumb_rect.center(),
                egui::Align2::CENTER_CENTER,
                format!("#{:03}", index + 1),
                egui::FontId::monospace(10.0),
                colors::TEXT_MUTED,
            );
        }

        // Card label at bottom
        let label_text = format!("#{:03}", index + 1);
        painter.text(
            rect.min + vec2(6.0, 56.0),
            egui::Align2::LEFT_TOP,
            label_text,
            egui::FontId::monospace(9.5),
            if is_selected {
                colors::RETICLE_POLARIS
            } else {
                colors::TEXT_SECONDARY
            },
        );

        response
    }
}
