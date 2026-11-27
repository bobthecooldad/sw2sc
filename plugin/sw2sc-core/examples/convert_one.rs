//! Converts one part as the plugin does (solidcraft-cli standing in for the host) and prints the
//! import report: convert_one PART.SLDPRT [--design-out DESIGN.solidcraft]
use sw2sc_core::cli::CliEvaluator;
use sw2sc_core::convert::convert_part;
use sw2sc_core::swfile::SwFile;

fn main() {
    let mut args = std::env::args().skip(1);
    let p = args.next().expect("a part");
    let mut design_out = None;
    while let Some(arg) = args.next() {
        if arg == "--design-out" {
            design_out = args.next();
        }
    }
    let path = std::path::Path::new(&p);
    let name = path.file_stem().unwrap().to_string_lossy().to_string();
    let file = path.file_name().unwrap().to_string_lossy().to_string();
    let mut ev = CliEvaluator::find().expect("solidcraft-cli");
    let sw = SwFile::open(path).unwrap();
    match convert_part(&sw, &name, &file, &mut ev) {
        Ok((d, rep)) => {
            if let Some(out) = design_out {
                std::fs::write(out, serde_json::to_vec(&d).unwrap()).unwrap();
            }
            println!("{}", serde_json::to_string_pretty(&rep.to_json()).unwrap());
        }
        Err(e) => println!("error: {e}"),
    }
}
