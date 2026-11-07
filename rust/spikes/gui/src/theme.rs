//! Dark studio theme and styling matching the PullStar React application.
//!
//! Colors and layout tokens derived from `frontend/src/index.css`.

use egui::{
    epaint::Shadow, Color32, CornerRadius, Margin, Stroke, Visuals,
};

/// Studio color palette constants.
pub mod colors {
    use super::Color32;

    pub const WORKSPACE_BG: Color32 = Color32::from_rgb(5, 5, 5);
    pub const SURFACE_SOLID: Color32 = Color32::from_rgb(22, 22, 23);
    pub const SURFACE_ELEVATED: Color32 = Color32::from_rgb(30, 30, 32);
    pub const GLASS_LINE: Color32 = Color32::from_rgba_premultiplied(255, 255, 255, 23);
    pub const GLASS_LINE_STRONG: Color32 = Color32::from_rgba_premultiplied(255, 255, 255, 55);

    pub const TEXT_PRIMARY: Color32 = Color32::from_rgb(242, 242, 243);
    pub const TEXT_SECONDARY: Color32 = Color32::from_rgb(186, 186, 190);
    pub const TEXT_MUTED: Color32 = Color32::from_rgb(146, 146, 153);

    pub const ACCENT: Color32 = Color32::from_rgb(216, 229, 231);
    pub const ACCENT_FILL: Color32 = Color32::from_rgba_premultiplied(255, 255, 255, 18);
    pub const ACCENT_LINE: Color32 = Color32::from_rgba_premultiplied(255, 255, 255, 53);

    pub const RETICLE_POLARIS: Color32 = Color32::from_rgb(56, 189, 248); // Cyan-400
    pub const RETICLE_REF2: Color32 = Color32::from_rgb(245, 158, 11);    // Amber-500
    pub const STAR_DETECTED: Color32 = Color32::from_rgb(52, 211, 153);   // Emerald-400

    pub const STATUS_SUCCESS: Color32 = Color32::from_rgb(164, 203, 185);
    pub const STATUS_WARNING: Color32 = Color32::from_rgb(206, 183, 145);
    pub const STATUS_DANGER: Color32 = Color32::from_rgb(239, 167, 167);
}

/// Apply the PullStar dark studio styling to an egui Context.
pub fn apply_studio_theme(ctx: &egui::Context) {
    let mut visuals = Visuals::dark();

    // Dark workspace surfaces
    visuals.panel_fill = colors::WORKSPACE_BG;
    visuals.window_fill = colors::SURFACE_SOLID;
    visuals.window_stroke = Stroke::new(1.0, colors::GLASS_LINE);
    visuals.window_corner_radius = CornerRadius::same(12);
    visuals.window_shadow = Shadow::NONE;

    // Widget non-interactive styling
    visuals.widgets.noninteractive.bg_fill = colors::SURFACE_SOLID;
    visuals.widgets.noninteractive.weak_bg_fill = colors::SURFACE_SOLID;
    visuals.widgets.noninteractive.bg_stroke = Stroke::new(1.0, colors::GLASS_LINE);
    visuals.widgets.noninteractive.fg_stroke = Stroke::new(1.0, colors::TEXT_PRIMARY);
    visuals.widgets.noninteractive.corner_radius = CornerRadius::same(8);

    // Inactive / default interactive widgets
    visuals.widgets.inactive.bg_fill = colors::ACCENT_FILL;
    visuals.widgets.inactive.weak_bg_fill = Color32::from_rgba_premultiplied(255, 255, 255, 10);
    visuals.widgets.inactive.bg_stroke = Stroke::new(1.0, colors::GLASS_LINE);
    visuals.widgets.inactive.fg_stroke = Stroke::new(1.0, colors::TEXT_PRIMARY);
    visuals.widgets.inactive.corner_radius = CornerRadius::same(6);

    // Hovered widgets
    visuals.widgets.hovered.bg_fill = Color32::from_rgba_premultiplied(255, 255, 255, 28);
    visuals.widgets.hovered.weak_bg_fill = Color32::from_rgba_premultiplied(255, 255, 255, 20);
    visuals.widgets.hovered.bg_stroke = Stroke::new(1.0, colors::GLASS_LINE_STRONG);
    visuals.widgets.hovered.fg_stroke = Stroke::new(1.0, Color32::WHITE);
    visuals.widgets.hovered.corner_radius = CornerRadius::same(6);

    // Active / pressed widgets
    visuals.widgets.active.bg_fill = Color32::from_rgba_premultiplied(255, 255, 255, 45);
    visuals.widgets.active.weak_bg_fill = Color32::from_rgba_premultiplied(255, 255, 255, 35);
    visuals.widgets.active.bg_stroke = Stroke::new(1.5, colors::ACCENT);
    visuals.widgets.active.fg_stroke = Stroke::new(1.0, Color32::WHITE);
    visuals.widgets.active.corner_radius = CornerRadius::same(6);

    // Open menus / comboboxes
    visuals.widgets.open.bg_fill = colors::SURFACE_ELEVATED;
    visuals.widgets.open.bg_stroke = Stroke::new(1.0, colors::ACCENT_LINE);
    visuals.widgets.open.corner_radius = CornerRadius::same(8);

    // Selection
    visuals.selection.bg_fill = Color32::from_rgba_premultiplied(56, 189, 248, 60);
    visuals.selection.stroke = Stroke::new(1.0, colors::RETICLE_POLARIS);

    ctx.set_visuals(visuals);
}

/// Helper for drawing section headers with subtle styling.
pub fn section_header(ui: &mut egui::Ui, title: &str, subtitle: Option<&str>) {
    ui.vertical(|ui| {
        ui.label(
            egui::RichText::new(title)
                .color(colors::TEXT_PRIMARY)
                .size(13.0)
                .strong(),
        );
        if let Some(sub) = subtitle {
            ui.label(
                egui::RichText::new(sub)
                    .color(colors::TEXT_MUTED)
                    .size(10.0),
            );
        }
    });
}
