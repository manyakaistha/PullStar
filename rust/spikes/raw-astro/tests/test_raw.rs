use std::fs;
use std::path::PathBuf;
use sha2::{Digest, Sha256};

use raw_astro_spike::raw::{RawDecoder, Thumbnail};

fn fixture_path(name: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("fixtures")
        .join(name)
}

fn file_sha256(path: &std::path::Path) -> String {
    let bytes = fs::read(path).expect("read file for hashing");
    let mut hasher = Sha256::new();
    hasher.update(&bytes);
    let result = hasher.finalize();
    result.iter().map(|b| format!("{b:02x}")).collect()
}

#[test]
fn test_libraw_version_reported() {
    let ver = RawDecoder::libraw_version();
    assert!(ver.starts_with("0.22"), "Expected LibRaw 0.22.x, got: {ver}");
}

#[test]
fn test_tracking_preserves_camera_black_levels_in_a_dark_dng() {
    let path = fixture_path("dark.dng");
    assert!(path.exists(), "dark.dng fixture must exist");

    let before_hash = file_sha256(&path);

    let mut decoder = RawDecoder::new().expect("create decoder");
    decoder.open_file(&path).expect("open dark.dng");
    decoder.unpack().expect("unpack dark.dng");

    let sizes = decoder.sizes();
    assert_eq!(sizes.width, 512);
    assert_eq!(sizes.height, 384);

    let black = decoder.black_level_per_channel();
    assert_eq!(black, [64.0, 64.0, 64.0, 64.0]);

    // Develop with tracking parameters (linear light, 16-bit, no auto-brightening)
    let developed = decoder.develop_for_tracking().expect("develop for tracking");
    assert_eq!(developed.width, 512);
    assert_eq!(developed.height, 384);

    // Parity gates: median < 1000, max > 5000
    let median = developed.median();
    let max = developed.max();
    println!("Rust dark.dng developed tracking median: {median}, max: {max}");
    assert!(median < 1000.0, "Median was {median}, expected < 1000.0");
    assert!(max > 5000, "Max was {max}, expected > 5000");

    let after_hash = file_sha256(&path);
    assert_eq!(before_hash, after_hash, "Source file must remain byte-identical");
}

#[test]
fn test_signed_bayer_sensor_plane_preserves_black_levels_and_oracle_parity() {
    let path = fixture_path("dark.dng");
    let mut decoder = RawDecoder::new().expect("create decoder");
    decoder.open_file(&path).expect("open dark.dng");

    let plane = decoder.sensor_plane().expect("sensor plane");
    assert_eq!(plane.width, 256);
    assert_eq!(plane.height, 192);

    let min = plane.min();
    let max = plane.max();
    let median = plane.median();
    let mean = plane.mean();
    println!("Rust dark.dng sensor plane min: {min}, max: {max}, median: {median}, mean: {mean}");

    // Load oracle data
    let oracle_file = fixture_path("oracle_data.json");
    let oracle_str = fs::read_to_string(oracle_file).expect("read oracle json");
    let oracle: serde_json::Value = serde_json::from_str(&oracle_str).expect("parse oracle json");

    let oracle_min = oracle["dark_dng_sensor_plane"]["min"].as_f64().unwrap() as f32;
    let oracle_max = oracle["dark_dng_sensor_plane"]["max"].as_f64().unwrap() as f32;
    let oracle_median = oracle["dark_dng_sensor_plane"]["median"].as_f64().unwrap() as f32;

    assert!((min - oracle_min).abs() < 1e-2, "min diff: {min} vs {oracle_min}");
    assert!((max - oracle_max).abs() < 1e-2, "max diff: {max} vs {oracle_max}");
    assert!((median - oracle_median).abs() < 0.5, "median diff: {median} vs {oracle_median}");
}

#[test]
fn test_embedded_preview_vs_raw_decode_failure_on_undecodable_raw_strip() {
    let path = fixture_path("undecodable_rot6.dng");
    assert!(path.exists(), "undecodable_rot6.dng fixture must exist");

    let before_hash = file_sha256(&path);

    // 1. Embedded thumbnail extraction succeeds on undecodable strip
    {
        let mut decoder = RawDecoder::new().expect("create decoder");
        decoder.open_file(&path).expect("open undecodable_rot6.dng");
        let thumb = decoder.extract_thumb().expect("extract thumb");
        match thumb {
            Thumbnail::Jpeg(bytes) => {
                assert!(!bytes.is_empty());
                assert_eq!(&bytes[0..2], &[0xFF, 0xD8], "Must be valid JPEG SOI");
            }
            Thumbnail::Bitmap { .. } => panic!("Expected JPEG thumbnail"),
        }
    }

    // 2. Full raw pixel unpack MUST fail on undecodable compression
    {
        let mut decoder = RawDecoder::new().expect("create decoder");
        decoder.open_file(&path).expect("open undecodable_rot6.dng");
        let unpack_result = decoder.unpack();
        assert!(
            unpack_result.is_err(),
            "Raw unpacking of unsupported strip must return an error"
        );
    }

    // 3. Load preview succeeds using the embedded preview and rotates
    {
        let mut decoder = RawDecoder::new().expect("create decoder");
        decoder.open_file(&path).expect("open undecodable_rot6.dng");
        let preview = decoder.load_preview().expect("load preview");
        // Original preview is 128x96, orientation 6 rotates 90 deg -> 96x128
        assert_eq!(preview.width, 96);
        assert_eq!(preview.height, 128);
        assert!(preview.std() > 10.0);
    }

    let after_hash = file_sha256(&path);
    assert_eq!(before_hash, after_hash, "Source file must remain byte-identical");
}

#[test]
fn test_orientation_rotations() {
    for rot in [3, 6, 8] {
        let name = format!("undecodable_rot{rot}.dng");
        let path = fixture_path(&name);
        let mut decoder = RawDecoder::new().expect("create decoder");
        decoder.open_file(&path).expect("open file");
        let preview = decoder.load_preview().expect("load preview");

        let (expected_w, expected_h) = match rot {
            3 => (128, 96),
            6 | 8 => (96, 128),
            _ => unreachable!(),
        };
        assert_eq!(preview.width, expected_w, "rot{rot} width mismatch");
        assert_eq!(preview.height, expected_h, "rot{rot} height mismatch");
    }
}
