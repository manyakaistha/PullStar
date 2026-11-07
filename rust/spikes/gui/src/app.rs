//! Main PullStar desktop spike application implementing `eframe::App`.

use crate::filmstrip::Filmstrip;
use crate::fixtures;
use crate::header::{render_studio_header, WorkspaceView};
use crate::settings::{ParameterBaysState, SettingsAction};
use crate::telemetry::{PipelineStage, TelemetryState};
use crate::theme::{apply_studio_theme, colors};
use crate::viewfinder::CelestialViewfinder;
use eframe::egui::{
    self, vec2, ColorImage, CornerRadius, Key, Stroke, StrokeKind, TextureHandle, Ui,
};
use std::path::{Path, PathBuf};
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::Arc;
use std::time::{Duration, Instant};

/// Configuration options passed from CLI.
#[derive(Clone, Debug)]
pub struct AppConfig {
    pub screenshot_path: Option<PathBuf>,
    pub scaled_screenshot_path: Option<PathBuf>,
    pub scale_factor: Option<f32>,
    pub idle_benchmark_seconds: Option<u64>,
    pub fixture_dir: Option<PathBuf>,
    pub auto_exit_after_frames: Option<u32>,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            screenshot_path: None,
            scaled_screenshot_path: None,
            scale_factor: None,
            idle_benchmark_seconds: None,
            fixture_dir: None,
            auto_exit_after_frames: None,
        }
    }
}

/// Main Spike App state.
pub struct PullStarSpikeApp {
    config: AppConfig,
    start_instant: Instant,
    first_frame_rendered: bool,
    frame_counter: u64,

    // Header & Workspace
    active_view: WorkspaceView,
    status_text: String,
    icon_image: Option<ColorImage>,
    icon_texture: Option<TextureHandle>,

    // Subcomponents
    viewfinder: CelestialViewfinder,
    filmstrip: Filmstrip,
    settings: ParameterBaysState,
    telemetry: TelemetryState,

    // Image buffers & textures
    current_image: ColorImage,
    viewfinder_texture: Option<TextureHandle>,

    // Native file dialog asynchronous channel
    folder_rx: Receiver<Option<PathBuf>>,
    folder_tx: Sender<Option<PathBuf>>,

    // Simulated processing job
    is_processing: bool,
    job_start_time: Option<Instant>,

    // Benchmark tracking
    benchmark_start: Option<Instant>,
}

impl PullStarSpikeApp {
    pub fn new(cc: &eframe::CreationContext<'_>, config: AppConfig) -> Self {
        apply_studio_theme(&cc.egui_ctx);

        if let Some(scale) = config.scale_factor {
            cc.egui_ctx.set_pixels_per_point(scale);
        }

        let (folder_tx, folder_rx) = channel();

        // 1. Try loading app icon from frontend assets
        let icon_path = Path::new("frontend/public/app-icon.png");
        let alt_icon_path = Path::new("../../frontend/public/app-icon.png");
        let icon_image = fixtures::load_image_from_path(icon_path)
            .or_else(|_| fixtures::load_image_from_path(alt_icon_path))
            .ok();

        // 2. Initial synthetic star field or sample image
        let initial_image = fixtures::generate_synthetic_starfield(1920, 1080);

        let mut app = Self {
            config,
            start_instant: Instant::now(),
            first_frame_rendered: false,
            frame_counter: 0,

            active_view: WorkspaceView::Workspace,
            status_text: "Local workspace".to_string(),
            icon_image,
            icon_texture: None,

            viewfinder: CelestialViewfinder::default(),
            filmstrip: Filmstrip::default(),
            settings: ParameterBaysState::default(),
            telemetry: TelemetryState::default(),

            current_image: initial_image,
            viewfinder_texture: None,

            folder_rx,
            folder_tx,

            is_processing: false,
            job_start_time: None,

            benchmark_start: None,
        };

        // 3. Scan default folder or fixture folder if specified
        let scan_target = app
            .config
            .fixture_dir
            .clone()
            .unwrap_or_else(|| PathBuf::from("corr_to_jpeg"));
        let alt_target = PathBuf::from("../../corr_to_jpeg");

        let target_dir = if scan_target.exists() {
            scan_target
        } else if alt_target.exists() {
            alt_target
        } else {
            PathBuf::from(".")
        };

        app.load_directory(&target_dir);

        app
    }

    fn load_directory(&mut self, dir: &Path) {
        let files = fixtures::scan_directory(dir);
        if files.is_empty() {
            self.settings.scan_error =
                Some("No supported images found in this folder.".to_string());
            self.settings.frame_count = 0;
            self.filmstrip.set_files(&[]);
        } else {
            self.settings.folder_path = dir.display().to_string();
            self.settings.frame_count = files.len();
            self.settings.scan_error = None;
            self.telemetry.add_log(format!(
                "Loaded directory: {} ({} frames)",
                dir.display(),
                files.len()
            ));

            // Load first image as viewfinder image
            if let Ok(loaded) = fixtures::load_image_from_path(&files[0]) {
                self.current_image = loaded;
                self.viewfinder_texture = None; // Force texture rebuild
            }

            self.filmstrip.set_files(&files);
        }
    }

    fn open_native_folder_picker(&self) {
        let tx = self.folder_tx.clone();
        std::thread::spawn(move || {
            let picked = rfd::FileDialog::new()
                .set_title("Choose the folder containing your photos")
                .pick_folder();
            let _ = tx.send(picked);
        });
    }

    fn update_simulated_processing(&mut self) {
        if !self.is_processing {
            return;
        }

        if let Some(start) = self.job_start_time {
            let elapsed = start.elapsed().as_secs_f32();
            let total_sim_time = 4.0; // 4 second demo alignment pipeline
            let progress = (elapsed / total_sim_time).clamp(0.0, 1.0);
            self.telemetry.overall_progress = progress;

            if progress < 0.20 {
                self.telemetry.current_stage = PipelineStage::Prepare;
                self.status_text = "Aligning · Prepare 15%".to_string();
            } else if progress < 0.45 {
                self.telemetry.current_stage = PipelineStage::Convert;
                self.status_text = "Aligning · Convert 35%".to_string();
            } else if progress < 0.70 {
                self.telemetry.current_stage = PipelineStage::TrackStars;
                self.status_text = "Aligning · Tracking stars 60%".to_string();
            } else if progress < 0.85 {
                self.telemetry.current_stage = PipelineStage::CalculateCrop;
                self.status_text = "Aligning · Calculate crop 78%".to_string();
            } else if progress < 1.0 {
                self.telemetry.current_stage = PipelineStage::StackFrames;
                self.status_text = "Aligning · Stacking 92%".to_string();
            } else {
                self.telemetry.current_stage = PipelineStage::Completed;
                self.status_text = "Alignment complete".to_string();
                self.is_processing = false;
                self.telemetry.add_log("Star alignment run finished successfully. Output written.");
            }
        }
    }
}

impl eframe::App for PullStarSpikeApp {
    fn ui(&mut self, ui: &mut Ui, _frame: &mut eframe::Frame) {
        self.frame_counter += 1;

        // Record first frame timing
        if !self.first_frame_rendered {
            let duration = self.start_instant.elapsed();
            println!(
                "First window frame rendered in: {:.2} ms ({} µs)",
                duration.as_secs_f64() * 1000.0,
                duration.as_micros()
            );
            self.first_frame_rendered = true;
        }

        // Check if asynchronous folder picker sent a result
        if let Ok(Some(picked_folder)) = self.folder_rx.try_recv() {
            self.load_directory(&picked_folder);
        }

        // Advance simulated job if running
        self.update_simulated_processing();

        // Check keyboard shortcuts
        let input = ui.input(|i| i.clone());
        if input.key_pressed(Key::Tab) {
            // Tab key navigation handled natively by egui's focus cycling
        }

        // Top Studio Header
        render_studio_header(
            ui,
            &mut self.active_view,
            self.telemetry.current_stage == PipelineStage::Completed,
            &self.status_text,
            self.is_processing,
            self.icon_image.as_ref(),
            &mut self.icon_texture,
        );

        ui.add_space(8.0);

        // Main Studio Layout: Left Viewfinder & Filmstrip, Right Settings Bay
        let right_panel_w = 360.0;
        let left_panel_w = (ui.available_width() - right_panel_w - 12.0).max(400.0);

        ui.horizontal(|ui| {
            // LEFT COLUMN: Viewfinder + Filmstrip + Telemetry
            ui.allocate_ui(vec2(left_panel_w, ui.available_height()), |ui| {
                ui.vertical(|ui| {
                    // Viewfinder area (takes most of the height)
                    let telemetry_h = if self.telemetry.is_collapsed { 36.0 } else { 120.0 };
                    let filmstrip_h = 96.0;
                    let vf_height = (ui.available_height() - telemetry_h - filmstrip_h - 24.0).max(250.0);

                    ui.allocate_ui(vec2(ui.available_width(), vf_height), |ui| {
                        self.viewfinder.show(
                            ui,
                            &self.current_image,
                            &mut self.viewfinder_texture,
                        );
                    });

                    ui.add_space(8.0);

                    // Filmstrip area
                    if let Some(selected_idx) = self.filmstrip.show(ui) {
                        if let Some(frame) = self.filmstrip.frames.get(selected_idx) {
                            if let Ok(img) = fixtures::load_image_from_path(&frame.path) {
                                self.current_image = img;
                                self.viewfinder_texture = None;
                            }
                        }
                    }

                    ui.add_space(8.0);

                    // Telemetry & progress area
                    self.telemetry.show(ui);
                });
            });

            ui.add_space(8.0);

            // RIGHT COLUMN: Parameter Bays (Settings)
            ui.allocate_ui(vec2(right_panel_w, ui.available_height()), |ui| {
                // Background panel for parameter bay
                let bay_rect = ui.available_rect_before_wrap();
                ui.painter().rect_filled(
                    bay_rect,
                    CornerRadius::same(12),
                    colors::SURFACE_SOLID,
                );
                ui.painter().rect_stroke(
                    bay_rect,
                    CornerRadius::same(12),
                    Stroke::new(1.0, colors::GLASS_LINE),
                    StrokeKind::Inside,
                );

                ui.scope(|ui| {
                    ui.spacing_mut().window_margin = egui::Margin::same(12);
                    if let Some(action) = self.settings.show(ui, self.is_processing) {
                        match action {
                            SettingsAction::BrowseFolderRequested => {
                                self.open_native_folder_picker();
                            }
                            SettingsAction::DetectStarsRequested => {
                                self.telemetry.add_log("Astrometric auto-detection: found Polaris (960.0, 540.0) and Ref Star 2 (1280.0, 360.0).");
                                self.viewfinder.polaris = Some(crate::viewfinder::StarMarker {
                                    x: 960.0,
                                    y: 540.0,
                                });
                                self.viewfinder.ref_star_2 = Some(crate::viewfinder::StarMarker {
                                    x: 1280.0,
                                    y: 360.0,
                                });
                            }
                            SettingsAction::StartAlignmentRequested => {
                                self.is_processing = true;
                                self.job_start_time = Some(Instant::now());
                                self.telemetry.current_stage = PipelineStage::Prepare;
                                self.telemetry.add_log("Starting alignment job with Apple Metal backend.");
                            }
                            SettingsAction::CancelAlignmentRequested => {
                                self.is_processing = false;
                                self.telemetry.current_stage = PipelineStage::Idle;
                                self.status_text = "Alignment cancelled".to_string();
                                self.telemetry.add_log("Alignment cancelled by user.");
                            }
                        }
                    }
                });
            });
        });

        // Screenshot capture support for automated evidence
        if self.frame_counter == 5 {
            if let Some(path) = &self.config.screenshot_path {
                let save_path = path.clone();
                let ctx = ui.ctx().clone();
                let auto_exit = self.config.auto_exit_after_frames.is_some()
                    || self.config.idle_benchmark_seconds.is_none();
                ctx.clone().request_screenshot(move |image: Arc<ColorImage>| {
                    let w = image.width() as u32;
                    let h = image.height() as u32;
                    let mut rgba = Vec::with_capacity((w * h * 4) as usize);
                    for px in &image.pixels {
                        rgba.extend_from_slice(&px.to_array());
                    }
                    if let Some(buf) = image::RgbaImage::from_raw(w, h, rgba) {
                        let _ = buf.save(&save_path);
                        println!("Saved spike screenshot to: {}", save_path.display());
                    }
                    if auto_exit {
                        ctx.send_viewport_cmd(egui::ViewportCommand::Close);
                    }
                });
            }
        }

        // Idle benchmark handling
        if let Some(target_secs) = self.config.idle_benchmark_seconds {
            let start = *self.benchmark_start.get_or_insert_with(Instant::now);
            let elapsed = start.elapsed();
            if elapsed >= Duration::from_secs(target_secs) {
                println!(
                    "Idle benchmark completed: {} frames rendered over {:.2} seconds ({:.2} FPS average during idle test)",
                    self.frame_counter,
                    elapsed.as_secs_f64(),
                    self.frame_counter as f64 / elapsed.as_secs_f64()
                );
                ui.ctx().send_viewport_cmd(egui::ViewportCommand::Close);
            }
        }

        // Repaint policy:
        // Only request a continuous repaint while an active animation/job is progressing.
        // When IDLE: DO NOT CALL request_repaint()! The app stays asleep until OS input events arrive!
        if self.is_processing {
            ui.ctx().request_repaint_after(Duration::from_millis(30));
        }
    }
}
