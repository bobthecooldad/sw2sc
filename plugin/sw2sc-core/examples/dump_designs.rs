//! Prints each fully decoded file's default design (first plane, positive directions, no picks)
//! as JSON lines, to compare with the Python's `features.design`.
use std::collections::HashMap;

use serde_json::json;
use sw2sc_core::design::{design, Choices, Picks};
use sw2sc_core::features::read;
use sw2sc_core::swfile::SwFile;

fn main() {
    for p in std::env::args().skip(1) {
        let path = std::path::Path::new(&p);
        let name = path.file_stem().unwrap().to_string_lossy().to_string();
        let line = match SwFile::open(path).ok().and_then(|sw| read(&sw)) {
            Some(mut fs) if sw2sc_core::verify::fully_decoded(&fs) => {
                let d = design(&name, &mut fs, &Choices::new(), &HashMap::new(), true, &Picks::new(), None);
                json!({"file": p, "design": d})
            }
            _ => json!({"file": p, "design": null}),
        };
        println!("{line}");
    }
}
