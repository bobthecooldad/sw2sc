//! Writes each part's STEP text next to a temp folder and prints a JSON line per file.
use sw2sc_core::step::part_to_step;
use sw2sc_core::swfile::SwFile;

fn main() {
    let mut args = std::env::args().skip(1);
    let out_dir = std::path::PathBuf::from(args.next().unwrap());
    for (i, p) in args.enumerate() {
        let path = std::path::Path::new(&p);
        let name = path.file_stem().unwrap().to_string_lossy().to_string();
        let line = match SwFile::open(path) {
            Ok(sw) => {
                let (text, warnings, _) = part_to_step(&sw, &name);
                let f = out_dir.join(format!("{i}.step"));
                if let Some(t) = &text {
                    std::fs::write(&f, t).unwrap();
                }
                serde_json::json!({"file": p, "step": text.as_ref().map(|_| f.display().to_string()), "warnings": warnings})
            }
            Err(e) => serde_json::json!({"file": p, "error": e.0}),
        };
        println!("{line}");
    }
}
