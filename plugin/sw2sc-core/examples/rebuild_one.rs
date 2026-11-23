//! Rebuilds one part's tree against a reference design (the part's own solid, as the Python
//! writes it) and prints the result as one JSON line: rebuild_one PART.SLDPRT REF.json
use serde_json::json;
use sw2sc_core::cli::CliEvaluator;
use sw2sc_core::features::read;
use sw2sc_core::search::rebuild;
use sw2sc_core::swfile::SwFile;

fn main() {
    let a: Vec<String> = std::env::args().collect();
    let path = std::path::Path::new(&a[1]);
    let reference: serde_json::Value = serde_json::from_slice(&std::fs::read(&a[2]).unwrap()).unwrap();
    let name = path.file_stem().unwrap().to_string_lossy().to_string();
    let mut ev = CliEvaluator::find().expect("solidcraft-cli");
    let t = std::time::Instant::now();
    let mut feats = read(&SwFile::open(path).unwrap()).unwrap_or_default();
    let (got, out) = rebuild(&mut feats, &reference, &name, &mut ev);
    let r = json!({"file": a[1], "matched": got.is_some(), "tries": out.tries, "timed_out": out.timed_out,
                   "seconds": t.elapsed().as_secs_f64(), "design": got});
    println!("{r}");
}
