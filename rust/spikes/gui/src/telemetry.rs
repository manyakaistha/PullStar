//! Telemetry and progress area displaying stage pipeline, progress bar, and log messages.

use crate::theme::colors;
use egui::{
    pos2, vec2, Color32, CornerRadius, ProgressBar, Rect, ScrollArea, Stroke, StrokeKind, Ui,
};

/// Processing pipeline stages.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PipelineStage {
    Idle,
    Prepare,
    Convert,
    TrackStars,
    CalculateCrop,
    StackFrames,
    Completed,
    Failed,
}

/// Telemetry state.
pub struct TelemetryState {
    pub current_stage: PipelineStage,
    pub stage_progress: f32,
    pub overall_progress: f32,
    pub is_collapsed: bool,
    pub event_log: Vec<String>,
}

impl Default for TelemetryState {
    fn default() -> Self {
        Self {
            current_stage: PipelineStage::Idle,
            stage_progress: 0.0,
            overall_progress: 0.0,
            is_collapsed: false,
            event_log: vec![
                "PullStar studio engine initialized.".to_string(),
                "Metal 3 device: Apple M-series GPU discovered.".to_string(),
                "Display: High-DPI Retina session active.".to_string(),
                "Ready for sequence selection.".to_string(),
            ],
        }
    }
}

impl TelemetryState {
    pub fn add_log(&mut self, msg: impl Into<String>) {
        self.event_log.push(msg.into());
    }

    pub fn show(&mut self, ui: &mut Ui) {
        ui.horizontal(|ui| {
            ui.label(
                egui::RichText::new("TELEMETRY & STAGES")
                    .color(colors::TEXT_MUTED)
                    .size(11.0)
                    .strong(),
            );

            let toggle_label = if self.is_collapsed { "Expand ▲" } else { "Collapse ▼" };
            if ui.small_button(toggle_label).clicked() {
                self.is_collapsed = !self.is_collapsed;
            }

            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                let status_text = match self.current_stage {
                    PipelineStage::Idle => "Status: Idle",
                    PipelineStage::Prepare => "Status: Preparing frames...",
                    PipelineStage::Convert => "Status: Converting RAW buffers...",
                    PipelineStage::TrackStars => "Status: Tracking stars...",
                    PipelineStage::CalculateCrop => "Status: Computing crop bounds...",
                    PipelineStage::StackFrames => "Status: Stacking star trails...",
                    PipelineStage::Completed => "Status: Alignment complete",
                    PipelineStage::Failed => "Status: Needs attention",
                };
                ui.label(
                    egui::RichText::new(status_text)
                        .color(match self.current_stage {
                            PipelineStage::Completed => colors::STATUS_SUCCESS,
                            PipelineStage::Failed => colors::STATUS_DANGER,
                            PipelineStage::Idle => colors::TEXT_MUTED,
                            _ => colors::RETICLE_POLARIS,
                        })
                        .size(11.0),
                );
            });
        });

        if self.is_collapsed {
            return;
        }

        ui.add_space(4.0);

        // Stages pipeline bar
        self.render_stage_pipeline(ui);

        ui.add_space(6.0);

        // Progress bar
        let progress = if self.current_stage == PipelineStage::Completed {
            1.0
        } else if self.current_stage == PipelineStage::Idle {
            0.0
        } else {
            self.overall_progress
        };

        ui.add(
            ProgressBar::new(progress)
                .show_percentage()
                .fill(colors::RETICLE_POLARIS)
                .animate(self.current_stage != PipelineStage::Idle && self.current_stage != PipelineStage::Completed),
        );

        ui.add_space(4.0);

        // Event log stream
        let log_height = 54.0;
        ScrollArea::vertical()
            .max_height(log_height)
            .stick_to_bottom(true)
            .show(ui, |ui| {
                for line in &self.event_log {
                    ui.label(
                        egui::RichText::new(format!("❯ {line}"))
                            .font(egui::FontId::monospace(10.0))
                            .color(colors::TEXT_MUTED),
                    );
                }
            });
    }

    fn render_stage_pipeline(&self, ui: &mut Ui) {
        let stages = [
            (PipelineStage::Prepare, "1. Prepare"),
            (PipelineStage::Convert, "2. Convert"),
            (PipelineStage::TrackStars, "3. Track"),
            (PipelineStage::CalculateCrop, "4. Crop"),
            (PipelineStage::StackFrames, "5. Stack"),
        ];

        let total_w = ui.available_width();
        let step_w = (total_w / stages.len() as f32).max(60.0);
        let h = 20.0;

        let (rect, _) = ui.allocate_exact_size(vec2(total_w, h), egui::Sense::hover());
        let painter = ui.painter_at(rect);

        for (i, &(stage, label)) in stages.iter().enumerate() {
            let seg_rect = Rect::from_min_size(
                pos2(rect.min.x + (i as f32) * step_w, rect.min.y),
                vec2(step_w - 4.0, h),
            );

            let is_active = self.current_stage == stage;
            let is_passed = match self.current_stage {
                PipelineStage::Completed => true,
                PipelineStage::StackFrames => i < 4,
                PipelineStage::CalculateCrop => i < 3,
                PipelineStage::TrackStars => i < 2,
                PipelineStage::Convert => i < 1,
                _ => false,
            };

            let bg = if is_active {
                Color32::from_rgba_premultiplied(56, 189, 248, 40)
            } else if is_passed {
                Color32::from_rgba_premultiplied(52, 211, 153, 30)
            } else {
                colors::SURFACE_SOLID
            };

            let stroke = if is_active {
                Stroke::new(1.2, colors::RETICLE_POLARIS)
            } else if is_passed {
                Stroke::new(1.0, colors::STAR_DETECTED)
            } else {
                Stroke::new(1.0, colors::GLASS_LINE)
            };

            painter.rect_filled(seg_rect, CornerRadius::same(4), bg);
            painter.rect_stroke(seg_rect, CornerRadius::same(4), stroke, StrokeKind::Inside);

            let text_color = if is_active {
                colors::RETICLE_POLARIS
            } else if is_passed {
                colors::STAR_DETECTED
            } else {
                colors::TEXT_MUTED
            };

            painter.text(
                seg_rect.center(),
                egui::Align2::CENTER_CENTER,
                label,
                egui::FontId::proportional(10.0),
                text_color,
            );
        }
    }
}
