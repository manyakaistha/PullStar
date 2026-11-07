//! Studio header with branding, navigation pills, and global status.

use crate::theme::colors;
use egui::{
    pos2, vec2, Color32, ColorImage, CornerRadius, Rect, Stroke, StrokeKind, TextureHandle,
    TextureOptions, Ui,
};

/// Active workspace view.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum WorkspaceView {
    Workspace,
    Results,
}

/// Render the PullStar studio header.
pub fn render_studio_header(
    ui: &mut Ui,
    active_view: &mut WorkspaceView,
    has_results: bool,
    status_text: &str,
    is_busy: bool,
    icon_image: Option<&ColorImage>,
    icon_texture: &mut Option<TextureHandle>,
) {
    let header_height = 44.0;
    let (rect, _) = ui.allocate_exact_size(vec2(ui.available_width(), header_height), egui::Sense::hover());
    let painter = ui.painter_at(rect);

    // Subtle bottom glass line
    painter.line_segment(
        [pos2(rect.min.x, rect.max.y), pos2(rect.max.x, rect.max.y)],
        Stroke::new(1.0, colors::GLASS_LINE),
    );

    // Left: Brand block (Icon + PullStar. + THE NIGHT, IN FOCUS)
    let icon_rect = Rect::from_min_size(rect.min + vec2(4.0, 6.0), vec2(32.0, 32.0));
    if let Some(img) = icon_image {
        let texture = icon_texture.get_or_insert_with(|| {
            ui.ctx().load_texture("app_icon", img.clone(), TextureOptions::LINEAR)
        });
        painter.image(
            texture.id(),
            icon_rect,
            Rect::from_min_max(pos2(0.0, 0.0), pos2(1.0, 1.0)),
            Color32::WHITE,
        );
    } else {
        // Fallback procedural app icon
        painter.rect_filled(icon_rect, CornerRadius::same(6), colors::SURFACE_SOLID);
        painter.circle_filled(icon_rect.center(), 6.0, colors::RETICLE_POLARIS);
    }

    // Title: PullStar.
    let title_pos = icon_rect.max.x + 10.0;
    painter.text(
        pos2(title_pos, rect.min.y + 7.0),
        egui::Align2::LEFT_TOP,
        "PullStar",
        egui::FontId::proportional(17.0),
        colors::TEXT_PRIMARY,
    );
    // Distinct cyan period
    painter.text(
        pos2(title_pos + 68.0, rect.min.y + 7.0),
        egui::Align2::LEFT_TOP,
        ".",
        egui::FontId::proportional(17.0),
        colors::RETICLE_POLARIS,
    );

    // Subtitle: THE NIGHT, IN FOCUS
    painter.text(
        pos2(title_pos, rect.min.y + 27.0),
        egui::Align2::LEFT_TOP,
        "THE NIGHT, IN FOCUS",
        egui::FontId::monospace(8.5),
        colors::TEXT_MUTED,
    );

    // Center: Workspace Navigation (if results exist)
    if has_results {
        let nav_w = 190.0;
        let nav_rect = Rect::from_center_size(
            pos2(rect.center().x, rect.center().y),
            vec2(nav_w, 28.0),
        );
        painter.rect_filled(nav_rect, CornerRadius::same(14), colors::SURFACE_SOLID);
        painter.rect_stroke(nav_rect, CornerRadius::same(14), Stroke::new(1.0, colors::GLASS_LINE), StrokeKind::Inside);

        let pill_w = (nav_w - 4.0) / 2.0;
        let ws_rect = Rect::from_min_size(nav_rect.min + vec2(2.0, 2.0), vec2(pill_w, 24.0));
        let res_rect = Rect::from_min_size(nav_rect.min + vec2(2.0 + pill_w, 2.0), vec2(pill_w, 24.0));

        let ws_active = *active_view == WorkspaceView::Workspace;
        if ws_active {
            painter.rect_filled(ws_rect, CornerRadius::same(12), colors::SURFACE_ELEVATED);
        } else {
            painter.rect_filled(res_rect, CornerRadius::same(12), colors::SURFACE_ELEVATED);
        }

        painter.text(
            ws_rect.center(),
            egui::Align2::CENTER_CENTER,
            "◫ Workspace",
            egui::FontId::proportional(11.0),
            if ws_active { colors::TEXT_PRIMARY } else { colors::TEXT_MUTED },
        );
        painter.text(
            res_rect.center(),
            egui::Align2::CENTER_CENTER,
            "✓ Results",
            egui::FontId::proportional(11.0),
            if !ws_active { colors::TEXT_PRIMARY } else { colors::TEXT_MUTED },
        );
    }

    // Right: Status badge
    let dot_color = if is_busy {
        colors::RETICLE_POLARIS
    } else {
        colors::STATUS_SUCCESS
    };

    let status_badge_rect = Rect::from_min_size(
        pos2(rect.max.x - 160.0, rect.min.y + 10.0),
        vec2(150.0, 24.0),
    );
    painter.rect_filled(
        status_badge_rect,
        CornerRadius::same(12),
        Color32::from_rgba_premultiplied(22, 22, 23, 200),
    );
    painter.rect_stroke(
        status_badge_rect,
        CornerRadius::same(12),
        Stroke::new(1.0, colors::GLASS_LINE),
        StrokeKind::Inside,
    );

    // Glowing status dot
    let dot_center = pos2(status_badge_rect.min.x + 14.0, status_badge_rect.center().y);
    painter.circle_filled(dot_center, 3.5, dot_color);

    painter.text(
        pos2(status_badge_rect.min.x + 24.0, status_badge_rect.center().y),
        egui::Align2::LEFT_CENTER,
        status_text,
        egui::FontId::proportional(11.0),
        colors::TEXT_PRIMARY,
    );
}
