//! Prints each file's streams (name, length, CRC-32) as JSON lines, to compare with the Python.
use sw2sc_core::swfile::SwFile;

fn main() {
    for p in std::env::args().skip(1) {
        let path = std::path::Path::new(&p);
        let line = match SwFile::open(path) {
            Ok(f) => {
                let streams: serde_json::Map<String, serde_json::Value> = f
                    .streams
                    .iter()
                    .map(|(k, v)| (k.clone(), serde_json::json!([v.len(), crc32fast::hash(v)])))
                    .collect();
                serde_json::json!({"file": p, "container": f.container, "streams": streams})
            }
            Err(e) => serde_json::json!({"file": p, "error": e.0}),
        };
        println!("{line}");
    }
}
