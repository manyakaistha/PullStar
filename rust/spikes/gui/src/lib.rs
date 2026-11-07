//! PullStar macOS egui/eframe GUI foundation spike.
//!
//! Demonstrates the adoption gate for a native Rust desktop GUI on macOS:
//! - Dark studio styling matching current product visual language
//! - Native macOS folder picker (`rfd`)
//! - Viewfinder with high-DPI texture rendering, zoom, pan, pixel coordinate readout,
//!   and 1/2-star reference picking overlay
//! - Filmstrip with lazy thumbnail loading
//! - Settings panel (Parameter bays) with toggles, sliders, disabled states, and validation
//! - Telemetry pipeline progress bar and event stream
//! - Zero idle CPU repaint loop (event-driven)
//! - AccessKit accessibility support

#![deny(unsafe_code)]

pub mod app;
pub mod coords;
pub mod filmstrip;
pub mod fixtures;
pub mod header;
pub mod settings;
pub mod telemetry;
pub mod theme;
pub mod viewfinder;

pub use app::{AppConfig, PullStarSpikeApp};
