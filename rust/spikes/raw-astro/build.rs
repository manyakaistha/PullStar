use std::env;
use std::path::PathBuf;

fn main() {
    let libraw_include = if let Ok(dir) = env::var("LIBRAW_INCLUDE_DIR") {
        PathBuf::from(dir)
    } else if std::path::Path::new("/opt/homebrew/opt/libraw/include").exists() {
        PathBuf::from("/opt/homebrew/opt/libraw/include")
    } else {
        PathBuf::from("/usr/local/include")
    };

    let libraw_lib = if let Ok(dir) = env::var("LIBRAW_LIB_DIR") {
        PathBuf::from(dir)
    } else if std::path::Path::new("/opt/homebrew/opt/libraw/lib").exists() {
        PathBuf::from("/opt/homebrew/opt/libraw/lib")
    } else {
        PathBuf::from("/usr/local/lib")
    };

    println!("cargo:rustc-link-search=native={}", libraw_lib.display());
    println!("cargo:rustc-link-lib=raw");
    println!("cargo:rerun-if-env-changed=LIBRAW_INCLUDE_DIR");
    println!("cargo:rerun-if-env-changed=LIBRAW_LIB_DIR");

    let header = libraw_include.join("libraw/libraw.h");
    println!("cargo:rerun-if-changed={}", header.display());

    let bindings = bindgen::Builder::default()
        .header(header.to_str().expect("valid utf-8 header path"))
        .clang_arg(format!("-I{}", libraw_include.display()))
        .allowlist_function("libraw_.*")
        .allowlist_type("libraw_.*")
        .allowlist_var("LIBRAW_.*")
        .allowlist_var("LibRaw_.*")
        .generate()
        .expect("Unable to generate bindings for LibRaw");

    let out_path = PathBuf::from(env::var("OUT_DIR").expect("OUT_DIR set by cargo"));
    bindings
        .write_to_file(out_path.join("libraw_bindings.rs"))
        .expect("Couldn't write libraw bindings");
}
