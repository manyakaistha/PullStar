//! Safe LibRaw wrapper, signed Bayer analysis, and preview extraction.

use std::ffi::CString;
use std::path::Path;

use crate::ffi;

/// Error type for RAW operations.
#[derive(Debug, thiserror::Error)]
pub enum RawError {
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),

    #[error("Nul byte in file path: {0}")]
    Nul(#[from] std::ffi::NulError),

    #[error("LibRaw open error: code {0} ({1})")]
    OpenFailed(i32, String),

    #[error("LibRaw unpack error: code {0} ({1})")]
    UnpackFailed(i32, String),

    #[error("LibRaw unpack thumbnail error: code {0} ({1})")]
    UnpackThumbFailed(i32, String),

    #[error("LibRaw process error: code {0} ({1})")]
    ProcessFailed(i32, String),

    #[error("LibRaw memory image creation failed: code {0}")]
    MemImageFailed(i32),

    #[error("LibRaw memory thumbnail creation failed: code {0}")]
    MemThumbFailed(i32),

    #[error("Unsupported RAW layout or pattern")]
    UnsupportedLayout,

    #[error("Image decode error: {0}")]
    ImageDecode(String),
}

fn libraw_err_str(code: i32) -> String {
    unsafe {
        let ptr = ffi::libraw_strerror(code);
        if ptr.is_null() {
            "Unknown LibRaw error".to_string()
        } else {
            std::ffi::CStr::from_ptr(ptr)
                .to_string_lossy()
                .into_owned()
        }
    }
}

/// Image sizes and orientation metadata reported by LibRaw.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ImageSizes {
    pub raw_width: u16,
    pub raw_height: u16,
    pub width: u16,
    pub height: u16,
    pub top_margin: u16,
    pub left_margin: u16,
    pub flip: i32,
    pub pixel_aspect: f64,
}

/// A 2D single-channel float32 plane (e.g. signed Bayer analysis).
#[derive(Clone, Debug)]
pub struct SensorPlane {
    pub width: usize,
    pub height: usize,
    pub data: Vec<f32>,
}

impl SensorPlane {
    #[must_use]
    pub fn get(&self, x: usize, y: usize) -> f32 {
        self.data[y * self.width + x]
    }

    #[must_use]
    pub fn min(&self) -> f32 {
        self.data.iter().copied().fold(f32::INFINITY, f32::min)
    }

    #[must_use]
    pub fn max(&self) -> f32 {
        self.data.iter().copied().fold(f32::NEG_INFINITY, f32::max)
    }

    #[must_use]
    pub fn mean(&self) -> f32 {
        if self.data.is_empty() {
            return 0.0;
        }
        let sum: f64 = self.data.iter().map(|&v| v as f64).sum();
        (sum / self.data.len() as f64) as f32
    }

    #[must_use]
    pub fn median(&self) -> f32 {
        if self.data.is_empty() {
            return 0.0;
        }
        let mut sorted = self.data.clone();
        sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        let mid = sorted.len() / 2;
        if sorted.len() % 2 == 0 {
            (sorted[mid - 1] + sorted[mid]) * 0.5
        } else {
            sorted[mid]
        }
    }
}

/// Developed 16-bit RGB image buffer.
#[derive(Clone, Debug)]
pub struct Rgb16Image {
    pub width: usize,
    pub height: usize,
    pub data: Vec<u16>, // row-major [R, G, B, R, G, B, ...]
}

impl Rgb16Image {
    #[must_use]
    pub fn min(&self) -> u16 {
        self.data.iter().copied().min().unwrap_or(0)
    }

    #[must_use]
    pub fn max(&self) -> u16 {
        self.data.iter().copied().max().unwrap_or(0)
    }

    #[must_use]
    pub fn median(&self) -> f64 {
        if self.data.is_empty() {
            return 0.0;
        }
        let mut sorted = self.data.clone();
        sorted.sort_unstable();
        let mid = sorted.len() / 2;
        if sorted.len() % 2 == 0 {
            (sorted[mid - 1] as f64 + sorted[mid] as f64) * 0.5
        } else {
            sorted[mid] as f64
        }
    }
}

/// Developed 8-bit RGB image buffer.
#[derive(Clone, Debug)]
pub struct Rgb8Image {
    pub width: usize,
    pub height: usize,
    pub data: Vec<u8>, // row-major [R, G, B, ...]
}

impl Rgb8Image {
    #[must_use]
    pub fn mean(&self) -> f64 {
        if self.data.is_empty() {
            return 0.0;
        }
        let sum: u64 = self.data.iter().map(|&v| v as u64).sum();
        sum as f64 / self.data.len() as f64
    }

    #[must_use]
    pub fn std(&self) -> f64 {
        if self.data.is_empty() {
            return 0.0;
        }
        let m = self.mean();
        let variance: f64 = self
            .data
            .iter()
            .map(|&v| {
                let d = v as f64 - m;
                d * d
            })
            .sum::<f64>()
            / self.data.len() as f64;
        variance.sqrt()
    }
}

/// Embedded thumbnail extracted from RAW container.
#[derive(Clone, Debug)]
pub enum Thumbnail {
    Jpeg(Vec<u8>),
    Bitmap {
        width: usize,
        height: usize,
        data: Vec<u8>,
    },
}

/// RAII wrapper around a LibRaw context.
pub struct RawDecoder {
    handle: *mut ffi::libraw_data_t,
    opened: bool,
    unpacked: bool,
}

// LibRaw handles can be moved between threads when not concurrently accessed.
unsafe impl Send for RawDecoder {}

impl Drop for RawDecoder {
    fn drop(&mut self) {
        if !self.handle.is_null() {
            unsafe {
                ffi::libraw_close(self.handle);
            }
        }
    }
}

impl RawDecoder {
    /// Creates a new uninitialized LibRaw context.
    pub fn new() -> Result<Self, RawError> {
        let handle = unsafe { ffi::libraw_init(0) };
        if handle.is_null() {
            return Err(RawError::OpenFailed(-1, "libraw_init returned null".into()));
        }
        Ok(Self {
            handle,
            opened: false,
            unpacked: false,
        })
    }

    /// Opens an image file and parses metadata/EXIF tags without unpacking pixels.
    pub fn open_file<P: AsRef<Path>>(&mut self, path: P) -> Result<(), RawError> {
        let path_ref = path.as_ref();
        let c_path = CString::new(path_ref.to_str().ok_or_else(|| {
            std::io::Error::new(std::io::ErrorKind::InvalidInput, "non-utf8 path")
        })?)?;

        let ret = unsafe { ffi::libraw_open_file(self.handle, c_path.as_ptr()) };
        if ret != 0 {
            return Err(RawError::OpenFailed(ret, libraw_err_str(ret)));
        }
        self.opened = true;
        Ok(())
    }

    /// Unpacks raw pixel data into memory.
    pub fn unpack(&mut self) -> Result<(), RawError> {
        let ret = unsafe { ffi::libraw_unpack(self.handle) };
        if ret != 0 {
            return Err(RawError::UnpackFailed(ret, libraw_err_str(ret)));
        }
        self.unpacked = true;
        Ok(())
    }

    /// Unpacks the embedded thumbnail into memory without unpacking full raw pixels.
    pub fn unpack_thumb(&mut self) -> Result<(), RawError> {
        let ret = unsafe { ffi::libraw_unpack_thumb(self.handle) };
        if ret != 0 {
            return Err(RawError::UnpackThumbFailed(ret, libraw_err_str(ret)));
        }
        Ok(())
    }

    /// Returns LibRaw's version string.
    #[must_use]
    pub fn libraw_version() -> String {
        unsafe {
            std::ffi::CStr::from_ptr(ffi::libraw_version())
                .to_string_lossy()
                .into_owned()
        }
    }

    /// Returns the image dimensions and orientation flags.
    #[must_use]
    pub fn sizes(&self) -> ImageSizes {
        unsafe {
            let s = &(*self.handle).sizes;
            ImageSizes {
                raw_width: s.raw_width,
                raw_height: s.raw_height,
                width: s.width,
                height: s.height,
                top_margin: s.top_margin,
                left_margin: s.left_margin,
                flip: s.flip,
                pixel_aspect: s.pixel_aspect,
            }
        }
    }

    /// Returns the per-channel black levels adjusted from DNG repeating black tables.
    ///
    /// Matches `rawpy.black_level_per_channel` via `LibRaw::adjust_bl()`.
    #[must_use]
    pub fn black_level_per_channel(&self) -> [f32; 4] {
        unsafe {
            let rc = &(*self.handle).rawdata.color;
            let mut cblack = rc.cblack;
            let mut black = rc.black;
            let filters = (*self.handle).idata.filters;

            // Add common part to cblack[] early (LibRaw adjust_bl)
            if filters > 1000 && (cblack[4] + 1) / 2 == 1 && (cblack[5] + 1) / 2 == 1 {
                let mut clrs = [0i32; 4];
                let mut gcnt = 0;
                let mut lastg = -1;
                for c in 0..4 {
                    clrs[c] = ffi::libraw_COLOR(self.handle, (c / 2) as i32, (c % 2) as i32);
                    if clrs[c] == 1 {
                        gcnt += 1;
                        lastg = c as i32;
                    }
                }
                if gcnt > 1 && lastg >= 0 {
                    clrs[lastg as usize] = 3;
                }
                for c in 0..4 {
                    let r_idx = ((c / 2) as u32 % cblack[4]) as usize;
                    let c_idx = ((c % 2) as u32 % cblack[5]) as usize;
                    let bl_idx = 6 + r_idx * (cblack[5] as usize) + c_idx;
                    cblack[clrs[c] as usize] += cblack[bl_idx];
                }
                cblack[4] = 0;
                cblack[5] = 0;
            } else if filters <= 1000 && cblack[4] == 1 && cblack[5] == 1 {
                for c in 0..4 {
                    cblack[c] += cblack[6];
                }
                cblack[4] = 0;
                cblack[5] = 0;
            }

            // Remove common part from cblack[]
            let mut min_val = cblack[3];
            for c in 0..3 {
                if min_val > cblack[c] {
                    min_val = cblack[c];
                }
            }
            for c in 0..4 {
                cblack[c] -= min_val;
            }
            black += min_val;

            // Common part for cblack[6+] part
            if cblack[4] != 0 && cblack[5] != 0 {
                let mut min_val = cblack[6];
                let count = (cblack[4] * cblack[5]) as usize;
                for c in 1..count {
                    if min_val > cblack[6 + c] {
                        min_val = cblack[6 + c];
                    }
                }
                let mut nonz = 0;
                for c in 0..count {
                    cblack[6 + c] -= min_val;
                    if cblack[6 + c] != 0 {
                        nonz += 1;
                    }
                }
                black += min_val;
                if nonz == 0 {
                    cblack[4] = 0;
                    cblack[5] = 0;
                }
            }

            [
                (black + cblack[0]) as f32,
                (black + cblack[1]) as f32,
                (black + cblack[2]) as f32,
                (black + cblack[3]) as f32,
            ]
        }
    }

    /// Returns the 2x2 Bayer pattern color indices.
    #[must_use]
    pub fn raw_pattern(&self) -> [[u8; 2]; 2] {
        unsafe {
            let p00 = ffi::libraw_COLOR(self.handle, 0, 0) as u8;
            let p01 = ffi::libraw_COLOR(self.handle, 0, 1) as u8;
            let p10 = ffi::libraw_COLOR(self.handle, 1, 0) as u8;
            let p11 = ffi::libraw_COLOR(self.handle, 1, 1) as u8;
            [[p00, p01], [p10, p11]]
        }
    }

    /// Returns a slice of the visible raw Bayer mosaic pixels.
    pub fn raw_image_visible(&self) -> Result<&[u16], RawError> {
        if !self.unpacked {
            return Err(RawError::UnpackFailed(-1, "Raw data not unpacked".into()));
        }
        unsafe {
            let raw_data = &(*self.handle).rawdata;
            if raw_data.raw_image.is_null() {
                return Err(RawError::UnsupportedLayout);
            }
            let sizes = self.sizes();
            let total = sizes.raw_width as usize * sizes.raw_height as usize;
            Ok(std::slice::from_raw_parts(raw_data.raw_image, total))
        }
    }

    /// Computes the signed black-subtracted 2x2 binned Bayer sensor plane.
    ///
    /// Preserves sensor-domain signal and camera black levels without clipping negative
    /// noise excursions. Pixel centers map according to `(2*x + 0.5, 2*y + 0.5)`.
    pub fn sensor_plane(&mut self) -> Result<SensorPlane, RawError> {
        if !self.unpacked {
            self.unpack()?;
        }
        let sizes = self.sizes();
        if sizes.pixel_aspect != 1.0 {
            return Err(RawError::UnsupportedLayout);
        }
        let width = sizes.width as usize;
        let height = sizes.height as usize;
        if width % 2 != 0 || height % 2 != 0 {
            return Err(RawError::UnsupportedLayout);
        }

        let raw_width = sizes.raw_width as usize;
        let top = sizes.top_margin as usize;
        let left = sizes.left_margin as usize;

        let raw_pixels = self.raw_image_visible()?;
        let black = self.black_level_per_channel();
        let pattern = self.raw_pattern();

        let out_w = width / 2;
        let out_h = height / 2;
        let mut plane = vec![0.0_f32; out_w * out_h];

        for y in 0..out_h {
            for x in 0..out_w {
                let mut sum = 0.0_f32;
                for dy in 0..2 {
                    for dx in 0..2 {
                        let row = top + y * 2 + dy;
                        let col = left + x * 2 + dx;
                        let raw_val = raw_pixels[row * raw_width + col] as f32;
                        let channel = pattern[dy][dx] as usize;
                        let black_val = black[channel % 4];
                        sum += raw_val - black_val;
                    }
                }
                plane[y * out_w + x] = sum * 0.25;
            }
        }

        // Apply orientation flip
        let oriented = orient_f32(plane, out_w, out_h, sizes.flip);
        Ok(oriented)
    }

    /// Develops raw pixels for tracking (linear light, 16-bit, no auto-brightening).
    pub fn develop_for_tracking(&mut self) -> Result<Rgb16Image, RawError> {
        if !self.unpacked {
            self.unpack()?;
        }
        unsafe {
            let p = &mut (*self.handle).params;
            p.use_camera_wb = 1;
            p.no_auto_bright = 1;
            p.output_bps = 16;
            p.gamm[0] = 1.0;
            p.gamm[1] = 1.0;
            p.user_qual = 3; // AHD demosaicing
            p.user_black = -1; // compute black from camera metadata

            let ret = ffi::libraw_dcraw_process(self.handle);
            if ret != 0 {
                return Err(RawError::ProcessFailed(ret, libraw_err_str(ret)));
            }

            let mut err = 0;
            let mem = ffi::libraw_dcraw_make_mem_image(self.handle, &mut err);
            if mem.is_null() {
                return Err(RawError::MemImageFailed(err));
            }

            let img = &*mem;
            let w = img.width as usize;
            let h = img.height as usize;
            let len = w * h * 3;
            let slice = std::slice::from_raw_parts(img.data.as_ptr() as *const u16, len);
            let data = slice.to_vec();

            ffi::libraw_dcraw_clear_mem(mem);
            Ok(Rgb16Image {
                width: w,
                height: h,
                data,
            })
        }
    }

    /// Develops raw pixels for 16-bit export (sRGB gamma, optional exposure EV shift, no auto-brightening).
    pub fn develop_for_export(&mut self, exposure_ev: f64) -> Result<Rgb16Image, RawError> {
        if !self.unpacked {
            self.unpack()?;
        }
        unsafe {
            let p = &mut (*self.handle).params;
            p.use_camera_wb = 1;
            p.no_auto_bright = 1;
            p.output_bps = 16;
            p.gamm[0] = 1.0 / 2.222;
            p.gamm[1] = 4.5;
            p.output_color = 1; // sRGB
            p.user_qual = 3; // AHD demosaicing
            p.user_black = -1; // compute black from camera metadata
            p.exp_shift = (2.0_f64.powf(exposure_ev)) as f32;

            let ret = ffi::libraw_dcraw_process(self.handle);
            if ret != 0 {
                return Err(RawError::ProcessFailed(ret, libraw_err_str(ret)));
            }

            let mut err = 0;
            let mem = ffi::libraw_dcraw_make_mem_image(self.handle, &mut err);
            if mem.is_null() {
                return Err(RawError::MemImageFailed(err));
            }

            let img = &*mem;
            let w = img.width as usize;
            let h = img.height as usize;
            let len = w * h * 3;
            let slice = std::slice::from_raw_parts(img.data.as_ptr() as *const u16, len);
            let data = slice.to_vec();

            ffi::libraw_dcraw_clear_mem(mem);
            Ok(Rgb16Image {
                width: w,
                height: h,
                data,
            })
        }
    }

    /// Extracts embedded thumbnail bytes without running full demosaicing.
    pub fn extract_thumb(&mut self) -> Result<Thumbnail, RawError> {
        self.unpack_thumb()?;
        unsafe {
            let mut err = 0;
            let mem = ffi::libraw_dcraw_make_mem_thumb(self.handle, &mut err);
            if mem.is_null() {
                return Err(RawError::MemThumbFailed(err));
            }

            let img = &*mem;
            let data_len = img.data_size as usize;
            let data_slice = std::slice::from_raw_parts(img.data.as_ptr(), data_len);
            let bytes = data_slice.to_vec();
            let thumb = if img.type_ == ffi::LibRaw_image_formats_LIBRAW_IMAGE_JPEG {
                Thumbnail::Jpeg(bytes)
            } else {
                Thumbnail::Bitmap {
                    width: img.width as usize,
                    height: img.height as usize,
                    data: bytes,
                }
            };

            ffi::libraw_dcraw_clear_mem(mem);
            Ok(thumb)
        }
    }

    /// Loads display preview. Extracts embedded JPEG thumbnail when available and rotates once,
    /// or falls back to fast 8-bit demosaicing.
    pub fn load_preview(&mut self) -> Result<Rgb8Image, RawError> {
        let sizes = self.sizes();

        // Attempt embedded preview first
        let embedded_thumb = self.extract_thumb().ok();
        if let Some(Thumbnail::Jpeg(jpeg_bytes)) = embedded_thumb {
            if let Ok(dyn_img) = image::load_from_memory(&jpeg_bytes) {
                let rgb = dyn_img.to_rgb8();
                let oriented = orient_rgb8(
                    rgb.into_raw(),
                    dyn_img.width() as usize,
                    dyn_img.height() as usize,
                    sizes.flip,
                );
                return Ok(oriented);
            }
        }

        // Fall back to 8-bit LibRaw development
        if !self.unpacked {
            self.unpack()?;
        }
        unsafe {
            let p = &mut (*self.handle).params;
            p.use_camera_wb = 1;
            p.output_bps = 8;
            p.output_color = 1;
            p.gamm[0] = 1.0 / 2.222;
            p.gamm[1] = 4.5;
            p.no_auto_bright = 0;
            p.user_qual = 3;

            let ret = ffi::libraw_dcraw_process(self.handle);
            if ret != 0 {
                return Err(RawError::ProcessFailed(ret, libraw_err_str(ret)));
            }

            let mut err = 0;
            let mem = ffi::libraw_dcraw_make_mem_image(self.handle, &mut err);
            if mem.is_null() {
                return Err(RawError::MemImageFailed(err));
            }

            let img = &*mem;
            let w = img.width as usize;
            let h = img.height as usize;
            let len = w * h * 3;
            let slice = std::slice::from_raw_parts(img.data.as_ptr(), len);
            let data = slice.to_vec();

            ffi::libraw_dcraw_clear_mem(mem);
            Ok(Rgb8Image {
                width: w,
                height: h,
                data,
            })
        }
    }
}

/// Applies LibRaw flip orientation to a 2D float32 image.
fn orient_f32(src: Vec<f32>, width: usize, height: usize, flip: i32) -> SensorPlane {
    match flip {
        3 => {
            // 180 degrees (np.rot90 2)
            let mut out = vec![0.0_f32; width * height];
            for y in 0..height {
                for x in 0..width {
                    out[(height - 1 - y) * width + (width - 1 - x)] = src[y * width + x];
                }
            }
            SensorPlane {
                width,
                height,
                data: out,
            }
        }
        5 => {
            // LibRaw flip 5 = EXIF 8 (90 deg CCW / 270 deg CW, rot90 1)
            let mut out = vec![0.0_f32; width * height];
            for y in 0..height {
                for x in 0..width {
                    let new_x = y;
                    let new_y = width - 1 - x;
                    out[new_y * height + new_x] = src[y * width + x];
                }
            }
            SensorPlane {
                width: height,
                height: width,
                data: out,
            }
        }
        6 => {
            // LibRaw flip 6 = EXIF 6 (90 deg CW, rot90 -1)
            let mut out = vec![0.0_f32; width * height];
            for y in 0..height {
                for x in 0..width {
                    let new_x = height - 1 - y;
                    let new_y = x;
                    out[new_y * height + new_x] = src[y * width + x];
                }
            }
            SensorPlane {
                width: height,
                height: width,
                data: out,
            }
        }
        _ => SensorPlane {
            width,
            height,
            data: src,
        },
    }
}

/// Applies LibRaw flip orientation to an 8-bit RGB image.
fn orient_rgb8(src: Vec<u8>, width: usize, height: usize, flip: i32) -> Rgb8Image {
    match flip {
        3 => {
            // 180 deg
            let mut out = vec![0_u8; width * height * 3];
            for y in 0..height {
                for x in 0..width {
                    let src_idx = (y * width + x) * 3;
                    let dst_idx = ((height - 1 - y) * width + (width - 1 - x)) * 3;
                    out[dst_idx..dst_idx + 3].copy_from_slice(&src[src_idx..src_idx + 3]);
                }
            }
            Rgb8Image {
                width,
                height,
                data: out,
            }
        }
        5 => {
            // LibRaw flip 5 = EXIF 8 (90 deg CCW)
            let mut out = vec![0_u8; width * height * 3];
            for y in 0..height {
                for x in 0..width {
                    let src_idx = (y * width + x) * 3;
                    let new_x = y;
                    let new_y = width - 1 - x;
                    let dst_idx = (new_y * height + new_x) * 3;
                    out[dst_idx..dst_idx + 3].copy_from_slice(&src[src_idx..src_idx + 3]);
                }
            }
            Rgb8Image {
                width: height,
                height: width,
                data: out,
            }
        }
        6 => {
            // LibRaw flip 6 = EXIF 6 (90 deg CW)
            let mut out = vec![0_u8; width * height * 3];
            for y in 0..height {
                for x in 0..width {
                    let src_idx = (y * width + x) * 3;
                    let new_x = height - 1 - y;
                    let new_y = x;
                    let dst_idx = (new_y * height + new_x) * 3;
                    out[dst_idx..dst_idx + 3].copy_from_slice(&src[src_idx..src_idx + 3]);
                }
            }
            Rgb8Image {
                width: height,
                height: width,
                data: out,
            }
        }
        _ => Rgb8Image {
            width,
            height,
            data: src,
        },
    }
}
