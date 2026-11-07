//! Settings panel (Parameter Bays) matching the PullStar React controls,
//! including toggles, sliders, disabled states, and validation banners.

use crate::theme::colors;
use egui::{
    vec2, Color32, CornerRadius, Rect, ScrollArea, Slider, Stroke, StrokeKind, TextEdit, Ui,
};

/// Active export mode.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ExportMode {
    StarTrails,
    Video,
    Frames,
}

/// Image export format.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ImageFormat {
    Tiff16,
    Jpeg,
    Png,
}

/// Compute backend target.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ComputeBackend {
    Auto,
    AppleMetal,
    CpuMultithreaded,
}

/// Settings and parameter bays state.
pub struct ParameterBaysState {
    // Bay 1: Input Sequence
    pub folder_path: String,
    pub sort_by_time: bool,
    pub frame_count: usize,
    pub scan_error: Option<String>,

    // Bay 2: Astrometric Detection & Alignment
    pub kalman_filter: bool,
    pub track_rotation: bool,
    pub extension_factor: f32,
    pub tail_taper: f32,
    pub ghosts: i32,

    // Bay 3: Foreground & Composite
    pub foreground_mask: bool,
    pub chrono_gap_fill: bool,
    pub synthetic_fade: f32,

    // Bay 4: Export & Output
    pub export_mode: ExportMode,
    pub image_format: ImageFormat,
    pub output_filename: String,
    pub use_checkpoint: bool,
    pub resume_from_checkpoint: bool,
    pub has_existing_checkpoint: bool,

    // Bay 5: Hardware & Performance
    pub compute_backend: ComputeBackend,
    pub raw_noise_reduction: bool,
    pub hardware_summary: String,

    // Section collapse states
    pub bay1_open: bool,
    pub bay2_open: bool,
    pub bay3_open: bool,
    pub bay4_open: bool,
    pub bay5_open: bool,
}

impl Default for ParameterBaysState {
    fn default() -> Self {
        Self {
            folder_path: "/Volumes/1700 APFS/PERSONAL_PROGRAMMING_PROJECTS/StarAligner/corr_to_jpeg".to_string(),
            sort_by_time: true,
            frame_count: 5,
            scan_error: None,

            kalman_filter: true,
            track_rotation: false,
            extension_factor: 1.0,
            tail_taper: 0.0,
            ghosts: 10,

            foreground_mask: true,
            chrono_gap_fill: false,
            synthetic_fade: 0.20,

            export_mode: ExportMode::StarTrails,
            image_format: ImageFormat::Tiff16,
            output_filename: "aligned_star_trails.tiff".to_string(),
            use_checkpoint: true,
            resume_from_checkpoint: false,
            has_existing_checkpoint: false,

            compute_backend: ComputeBackend::AppleMetal,
            raw_noise_reduction: true,
            hardware_summary: "Apple Metal 3 GPU · 8 performance cores · Unified memory".to_string(),

            bay1_open: true,
            bay2_open: true,
            bay3_open: true,
            bay4_open: true,
            bay5_open: true,
        }
    }
}

/// Actions emitted by the settings panel.
pub enum SettingsAction {
    BrowseFolderRequested,
    DetectStarsRequested,
    StartAlignmentRequested,
    CancelAlignmentRequested,
}

impl ParameterBaysState {
    pub fn show(&mut self, ui: &mut Ui, is_processing: bool) -> Option<SettingsAction> {
        let mut action = None;

        ScrollArea::vertical()
            .auto_shrink([false, false])
            .show(ui, |ui| {
                ui.add_space(4.0);

                // Action Bar (Start / Auto-detect buttons)
                if let Some(act) = self.render_primary_actions(ui, is_processing) {
                    action = Some(act);
                }

                ui.add_space(8.0);

                // Inline validation error if any
                if let Some(err) = &self.scan_error {
                    self.render_error_banner(ui, err);
                    ui.add_space(8.0);
                }

                // Bay 1: Input Sequence
                if let Some(act) = self.render_bay_1(ui, is_processing) {
                    action = Some(act);
                }
                ui.add_space(8.0);

                // Bay 2: Astrometric Detection & Alignment
                self.render_bay_2(ui, is_processing);
                ui.add_space(8.0);

                // Bay 3: Foreground & Composite
                self.render_bay_3(ui, is_processing);
                ui.add_space(8.0);

                // Bay 4: Export & Output
                self.render_bay_4(ui, is_processing);
                ui.add_space(8.0);

                // Bay 5: Hardware & Performance
                self.render_bay_5(ui, is_processing);
                ui.add_space(16.0);
            });

        action
    }

    fn render_primary_actions(&mut self, ui: &mut Ui, is_processing: bool) -> Option<SettingsAction> {
        let mut action = None;

        ui.horizontal(|ui| {
            if is_processing {
                if ui
                    .add(
                        egui::Button::new(
                            egui::RichText::new("⏹ Cancel Alignment")
                                .color(colors::STATUS_DANGER)
                                .size(12.0)
                                .strong(),
                        )
                        .min_size(vec2(130.0, 32.0)),
                    )
                    .clicked()
                {
                    action = Some(SettingsAction::CancelAlignmentRequested);
                }
            } else {
                let start_btn = ui.add_enabled(
                    self.frame_count > 0,
                    egui::Button::new(
                        egui::RichText::new("▶ Start Alignment")
                            .color(Color32::BLACK)
                            .size(12.0)
                            .strong(),
                    )
                    .fill(colors::ACCENT)
                    .min_size(vec2(140.0, 32.0)),
                );
                if start_btn.clicked() {
                    action = Some(SettingsAction::StartAlignmentRequested);
                }

                let detect_btn = ui.add_enabled(
                    self.frame_count > 0,
                    egui::Button::new(
                        egui::RichText::new("✨ Auto-Detect Stars")
                            .color(colors::TEXT_PRIMARY)
                            .size(12.0),
                    )
                    .min_size(vec2(130.0, 32.0)),
                );
                if detect_btn.clicked() {
                    action = Some(SettingsAction::DetectStarsRequested);
                }
            }
        });

        action
    }

    fn render_error_banner(&self, ui: &mut Ui, err_text: &str) {
        let (rect, _) = ui.allocate_exact_size(vec2(ui.available_width(), 32.0), egui::Sense::hover());
        let painter = ui.painter_at(rect);
        painter.rect_filled(
            rect,
            CornerRadius::same(6),
            Color32::from_rgba_premultiplied(239, 167, 167, 30),
        );
        painter.rect_stroke(
            rect,
            CornerRadius::same(6),
            Stroke::new(1.0, colors::STATUS_DANGER),
            StrokeKind::Inside,
        );
        painter.text(
            rect.min + vec2(10.0, 8.0),
            egui::Align2::LEFT_TOP,
            format!("⚠ {err_text}"),
            egui::FontId::proportional(11.5),
            colors::STATUS_DANGER,
        );
    }

    fn render_bay_1(&mut self, ui: &mut Ui, is_processing: bool) -> Option<SettingsAction> {
        let mut action = None;
        egui::CollapsingHeader::new(
            egui::RichText::new("1. INPUT SEQUENCE")
                .color(colors::TEXT_PRIMARY)
                .size(12.0)
                .strong(),
        )
        .default_open(self.bay1_open)
        .show(ui, |ui| {
            ui.add_space(4.0);
            ui.label(
                egui::RichText::new("Select folder containing photographic series:")
                    .size(11.0)
                    .color(colors::TEXT_SECONDARY),
            );

            ui.horizontal(|ui| {
                ui.add_enabled(
                    !is_processing,
                    TextEdit::singleline(&mut self.folder_path)
                        .hint_text("Directory path...")
                        .desired_width(ui.available_width() - 85.0),
                );

                if ui
                    .add_enabled(!is_processing, egui::Button::new("Browse…"))
                    .on_hover_text("Open native macOS folder picker")
                    .clicked()
                {
                    action = Some(SettingsAction::BrowseFolderRequested);
                }
            });

            ui.horizontal(|ui| {
                ui.label(
                    egui::RichText::new(format!("Loaded: {} frames", self.frame_count))
                        .size(11.0)
                        .color(colors::ACCENT),
                );
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    ui.add_enabled(
                        !is_processing,
                        egui::Checkbox::new(&mut self.sort_by_time, "Sort by EXIF time"),
                    );
                });
            });
        });
        action
    }

    fn render_bay_2(&mut self, ui: &mut Ui, is_processing: bool) {
        egui::CollapsingHeader::new(
            egui::RichText::new("2. ASTROMETRIC ALIGNMENT")
                .color(colors::TEXT_PRIMARY)
                .size(12.0)
                .strong(),
        )
        .default_open(self.bay2_open)
        .show(ui, |ui| {
            ui.add_space(4.0);
            ui.add_enabled(
                !is_processing,
                egui::Checkbox::new(&mut self.kalman_filter, "Kalman trajectory filtering"),
            );
            ui.add_enabled(
                !is_processing,
                egui::Checkbox::new(&mut self.track_rotation, "Field rotation tracking (2 stars)"),
            );

            ui.add_space(4.0);
            ui.label(
                egui::RichText::new(format!("Extension factor: {:.1}×", self.extension_factor))
                    .size(11.0)
                    .color(colors::TEXT_SECONDARY),
            );
            ui.add_enabled(
                !is_processing,
                Slider::new(&mut self.extension_factor, 1.0..=5.0).step_by(0.1),
            );

            ui.label(
                egui::RichText::new(format!("Tail taper: {:.2}", self.tail_taper))
                    .size(11.0)
                    .color(colors::TEXT_SECONDARY),
            );
            ui.add_enabled(
                !is_processing,
                Slider::new(&mut self.tail_taper, 0.0..=1.0).step_by(0.05),
            );

            ui.label(
                egui::RichText::new(format!("Ghost trail segments: {}", self.ghosts))
                    .size(11.0)
                    .color(colors::TEXT_SECONDARY),
            );
            ui.add_enabled(
                !is_processing,
                Slider::new(&mut self.ghosts, 0..=50),
            );
        });
    }

    fn render_bay_3(&mut self, ui: &mut Ui, is_processing: bool) {
        egui::CollapsingHeader::new(
            egui::RichText::new("3. FOREGROUND & COMPOSITE")
                .color(colors::TEXT_PRIMARY)
                .size(12.0)
                .strong(),
        )
        .default_open(self.bay3_open)
        .show(ui, |ui| {
            ui.add_space(4.0);
            ui.add_enabled(
                !is_processing,
                egui::Checkbox::new(&mut self.foreground_mask, "Static foreground mask protection"),
            );
            ui.add_enabled(
                !is_processing,
                egui::Checkbox::new(&mut self.chrono_gap_fill, "Chronological gap infilling"),
            );

            ui.label(
                egui::RichText::new(format!("Synthetic star fade: {:.2}", self.synthetic_fade))
                    .size(11.0)
                    .color(colors::TEXT_SECONDARY),
            );
            ui.add_enabled(
                !is_processing,
                Slider::new(&mut self.synthetic_fade, 0.0..=1.0).step_by(0.05),
            );
        });
    }

    fn render_bay_4(&mut self, ui: &mut Ui, is_processing: bool) {
        egui::CollapsingHeader::new(
            egui::RichText::new("4. EXPORT & OUTPUT")
                .color(colors::TEXT_PRIMARY)
                .size(12.0)
                .strong(),
        )
        .default_open(self.bay4_open)
        .show(ui, |ui| {
            ui.add_space(4.0);
            ui.horizontal(|ui| {
                ui.label(egui::RichText::new("Export:").size(11.0).color(colors::TEXT_SECONDARY));
                ui.selectable_value(&mut self.export_mode, ExportMode::StarTrails, "Trails");
                ui.selectable_value(&mut self.export_mode, ExportMode::Video, "Video");
                ui.selectable_value(&mut self.export_mode, ExportMode::Frames, "Frames");
            });

            ui.horizontal(|ui| {
                ui.label(egui::RichText::new("Format:").size(11.0).color(colors::TEXT_SECONDARY));
                ui.selectable_value(&mut self.image_format, ImageFormat::Tiff16, "TIFF 16-bit");
                ui.selectable_value(&mut self.image_format, ImageFormat::Jpeg, "JPEG");
                ui.selectable_value(&mut self.image_format, ImageFormat::Png, "PNG");
            });

            ui.horizontal(|ui| {
                ui.label(egui::RichText::new("Output file:").size(11.0).color(colors::TEXT_SECONDARY));
                ui.add_enabled(
                    !is_processing,
                    TextEdit::singleline(&mut self.output_filename),
                );
            });

            ui.add_enabled(
                !is_processing,
                egui::Checkbox::new(&mut self.use_checkpoint, "Save state checkpoint"),
            );

            // Disabled state demonstration: resume is disabled when no checkpoint exists
            ui.add_enabled(
                !is_processing && self.has_existing_checkpoint,
                egui::Checkbox::new(
                    &mut self.resume_from_checkpoint,
                    "Resume from previous checkpoint (none found)",
                ),
            );
        });
    }

    fn render_bay_5(&mut self, ui: &mut Ui, is_processing: bool) {
        egui::CollapsingHeader::new(
            egui::RichText::new("5. HARDWARE & PERFORMANCE")
                .color(colors::TEXT_PRIMARY)
                .size(12.0)
                .strong(),
        )
        .default_open(self.bay5_open)
        .show(ui, |ui| {
            ui.add_space(4.0);
            ui.horizontal(|ui| {
                ui.label(egui::RichText::new("Backend:").size(11.0).color(colors::TEXT_SECONDARY));
                ui.selectable_value(&mut self.compute_backend, ComputeBackend::AppleMetal, "Apple Metal (GPU)");
                ui.selectable_value(&mut self.compute_backend, ComputeBackend::CpuMultithreaded, "CPU");
            });

            ui.add_enabled(
                !is_processing,
                egui::Checkbox::new(&mut self.raw_noise_reduction, "RAW sensor noise reduction"),
            );

            ui.add_space(2.0);
            ui.label(
                egui::RichText::new(&self.hardware_summary)
                    .size(10.5)
                    .color(colors::TEXT_MUTED),
            );
        });
    }
}
