fn main() {
    // Proto types are hand-written in src/generated/ to match prost format.
    // To regenerate from .proto files, uncomment below and run:
    //   cargo build --features regenerate-protos
    //
    // let proto_files: Vec<String> = std::fs::read_dir("proto")
    //     .expect("proto directory not found")
    //     .filter_map(|entry| {
    //         let entry = entry.ok()?;
    //         let path = entry.path();
    //         if path.extension().map_or(false, |ext| ext == "proto") {
    //             Some(path.to_string_lossy().into_owned())
    //         } else {
    //             None
    //         }
    //     })
    //     .collect();
    //
    // prost_build::Config::new()
    //     .out_dir("src/generated")
    //     .compile_protos(&proto_files, &["proto/"])
    //     .expect("Failed to compile protos");
}
