//! Prints each file's features (every field) as JSON lines, to compare with the Python.
use serde_json::{json, Value};
use sw2sc_core::features::{read, Edge, FaceRef, Feature, Frame};
use sw2sc_core::swfile::SwFile;

fn face(f: &FaceRef) -> Value {
    json!([f.kind(), f.fid, f.v])
}
fn edge(e: &Edge) -> Value {
    json!([face(&e.0), face(&e.1)])
}
fn frame(f: &Frame) -> Value {
    json!([f.0, f.1])
}

fn feature(f: &Feature) -> Value {
    let sk = f.sketch.as_ref().map(|s| {
        json!({
            "name": s.name, "offset": s.offset, "end": s.end,
            "points": s.points.iter().map(|(k, v)| json!([k, v.0, v.1])).collect::<Vec<_>>(),
            "lines": s.lines, "construction": s.construction.iter().collect::<Vec<_>>(),
            "alt_centres": s.alt_centres.iter().map(|(k, v)| json!([k, v.0, v.1])).collect::<Vec<_>>(),
            "dropped": s.dropped, "point_flags": s.point_flags.iter().map(|(k, v)| json!([k, v])).collect::<Vec<_>>(),
            "region": s.region, "chain": s.chain, "arcs": s.arcs, "circles": s.circles,
            "planes": s.planes.iter().map(|(f, h)| json!([frame(f), h])).collect::<Vec<_>>(),
            "problems": s.problems,
            "curve_of": s.curve_of.iter().map(|(k, v)| json!([k.0, k.1, v])).collect::<Vec<_>>(),
            "dims": s.dims.iter().map(|d| json!([d.name, d.cls, d.value, d.handles.iter().map(|h| json!([h.cls, h.id])).collect::<Vec<_>>()])).collect::<Vec<_>>(),
            "relations": s.relations.iter().map(|r| json!([r.kind, r.groups.iter().map(|g| g.iter().map(|h| json!([h.cls, h.id])).collect::<Vec<_>>()).collect::<Vec<_>>()])).collect::<Vec<_>>(),
            "used": s.used,
        })
    });
    json!({
        "kind": f.kind, "name": f.name, "offset": f.offset, "cls": f.cls, "sketch": sk,
        "depth_mm": f.depth_mm, "profile": f.profile, "reason": f.reason, "frame": f.frame.as_ref().map(frame),
        "through_all": f.through_all, "angle_deg": f.angle_deg, "fid": f.fid, "radius_mm": f.radius_mm,
        "chamfer_deg": f.chamfer_deg, "chamfer_mm2": f.chamfer_mm2, "hole": f.hole, "alt_kind": f.alt_kind, "from_face": f.from_face,
        "edge_lines": f.edge_lines, "round_axes": f.round_axes.iter().map(|(p, a, r)| json!([p, a, r])).collect::<Vec<_>>(),
        "mirror_face": f.mirror_face.as_ref().map(face), "mirror_planes": f.mirror_planes.iter().map(frame).collect::<Vec<_>>(),
        "thread": f.thread, "pattern": f.pattern, "thin_mm": f.thin_mm, "dome_mm": f.dome_mm, "path": f.path, "translate": f.translate, "rib": f.rib.as_ref().map(|(o, x, y, c)| json!([o, x, y, c])), "scale": f.scale,
        "draft_deg": f.draft_deg, "move_mm": f.move_mm,
        "edges": f.edges.iter().map(edge).collect::<Vec<_>>(), "edge_ends": f.edge_ends.iter().map(edge).collect::<Vec<_>>(),
    })
}

fn main() {
    for p in std::env::args().skip(1) {
        let line = match SwFile::open(std::path::Path::new(&p)) {
            Ok(sw) => match read(&sw) {
                Some(fs) => json!({"file": p, "features": fs.iter().map(feature).collect::<Vec<_>>()}),
                None => json!({"file": p, "features": null}),
            },
            Err(e) => json!({"file": p, "error": e.0}),
        };
        println!("{line}");
    }
}
