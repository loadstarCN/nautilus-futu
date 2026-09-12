//! Build script.
//!
//! The prost-generated Rust types for the Futu OpenD protobuf schema are
//! checked in under `src/generated/` so a plain `cargo build` needs neither
//! `protoc` nor the `.proto` sources.
//!
//! To regenerate them from `proto/*.proto` (after updating the schema from
//! <https://github.com/FutunnOpen/py-futu-api/tree/master/futu/common/pb>):
//!
//! ```text
//! cargo build --features regenerate-protos
//! ```
//!
//! This requires `protoc` on `PATH` (or `PROTOC` set) and rewrites the files
//! in `src/generated/`; review the diff before committing.

fn main() {
    println!("cargo:rerun-if-changed=build.rs");

    #[cfg(feature = "regenerate-protos")]
    regenerate();
}

#[cfg(feature = "regenerate-protos")]
fn regenerate() {
    let proto_files: Vec<String> = std::fs::read_dir("proto")
        .expect("proto directory not found")
        .filter_map(|entry| {
            let entry = entry.ok()?;
            let path = entry.path();
            if path.extension().is_some_and(|ext| ext == "proto") {
                println!("cargo:rerun-if-changed={}", path.display());
                Some(path.to_string_lossy().into_owned())
            } else {
                None
            }
        })
        .collect();

    prost_build::Config::new()
        .out_dir("src/generated")
        .compile_protos(&proto_files, &["proto/"])
        .expect("Failed to compile protos (is `protoc` installed?)");
}
