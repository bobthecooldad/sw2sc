//! Converts one part as the plugin does (solidcraft-cli standing in for the host) and prints the
//! import report: convert_one PART.SLDPRT
use sw2sc_core::cli::CliEvaluator;
use sw2sc_core::convert::convert_part;
use sw2sc_core::swfile::SwFile;

fn main() {
    let p = std::env::args().nth(1).expect("a part");
    let path = std::path::Path::new(&p);
    let name = path.file_stem().unwrap().to_string_lossy().to_string();
    let file = path.file_name().unwrap().to_string_lossy().to_string();
    let mut ev = CliEvaluator::find().expect("solidcraft-cli");
    let sw = SwFile::open(path).unwrap();
    match convert_part(&sw, &name, &file, &mut ev) {
        Ok((_d, rep)) => println!("{}", serde_json::to_string_pretty(&rep.to_json()).unwrap()),
        Err(e) => println!("error: {e}"),
    }
}
