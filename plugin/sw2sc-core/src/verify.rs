//! Check a part's rebuilt feature tree against the solid SolidWorks saved (port of
//! `sw2sc/verify.py`).
//!
//! The feature tree read by `features` is written as SolidCraft features and evaluated; it is
//! used only when its volume, surface area and bounding box match the part's own solid within
//! 0.1 %, followed by geometric evidence. Native checks require both boolean differences within
//! the same relative volume tolerance. The read-only plugin host instead compares every face's
//! exact surface, area and centre. What the file leaves open (an extrude's direction, which plane
//! a sketch uses, a fillet's edges …) is settled by trying candidates and keeping one that matches.
//! SolidCraft is reached through [`Evaluator`]: `solidcraft-cli` natively, or the plugin host's
//! `evaluate` interface inside the importer.

use serde_json::{json, Value};

use crate::features::Feature;

pub const REL: f64 = 1e-3;
pub const SAME: f64 = 1e-6;
pub const MAX_FILLET_CHOICES: usize = 10;
/// Seconds a part's rebuild search may take; past it the part keeps its solid.
pub const TIME_BUDGET: f64 = 300.0;

/// What an evaluation of a design says: its total volume and area, its box, and the timeline's
/// errors.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Eval {
    pub volume: Option<f64>,
    pub area: Option<f64>,
    pub lo: Option<[f64; 3]>,
    pub hi: Option<[f64; 3]>,
    pub errors: Vec<String>,
    /// The first body's centre of mass.
    pub com: Option<[f64; 3]>,
}

/// SolidCraft, as the rebuild check uses it.
pub trait Evaluator {
    /// The design's numbers, or None when it couldn't be evaluated at all.
    fn evaluate(&mut self, design: &Value) -> Option<Eval>;
    /// `model.edges` on the design: the edges with their names and mid points.
    fn edges(&mut self, design: &Value) -> Option<Value>;
    /// `model.faces` on the design.
    fn faces(&mut self, design: &Value) -> Option<Value>;
    /// Volume of target minus tool, or None when that difference cannot be checked.
    fn difference_volume(&mut self, target: &Value, tool: &Value) -> Option<f64>;
    /// Final geometric acceptance. A read-only host can replace boolean differences with
    /// position-sensitive face geometry; it must not fall back to volume and area alone.
    fn shape_matches(&mut self, reference: &Value, candidate: &Value) -> bool {
        same_shape(self, reference, candidate)
    }
    /// Seconds since some fixed start (for the time budget).
    fn now(&self) -> f64;
}

/// The numbers of `solidcraft-cli eval`'s reply (or the same shape): `total.volume_mm3`,
/// `total.area_mm2`, each body's `bbox`, the timeline's errors.
pub fn eval_from(d: &Value) -> Eval {
    let t = &d["total"];
    let boxes: Vec<&Value> = d["bodies"].as_array().map_or(vec![], |b| b.iter().filter_map(|x| x.get("bbox").filter(|v| !v.is_null())).collect());
    let side = |key: &str, pick: fn(f64, f64) -> f64| -> Option<[f64; 3]> {
        if boxes.is_empty() {
            return None;
        }
        let mut out = [0.0; 3];
        for (k, o) in out.iter_mut().enumerate() {
            *o = boxes.iter().filter_map(|bx| bx[key][k].as_f64()).reduce(pick)?;
        }
        Some(out)
    };
    let errors = d["timeline"].as_array().map_or(vec![], |tl| {
        tl.iter().filter_map(|s| s.get("error").filter(|e| !e.is_null() && e.as_str() != Some("")).map(|e| e.as_str().map_or(e.to_string(), String::from))).collect()
    });
    let com = boxes_com(d);
    Eval { volume: t["volume_mm3"].as_f64(), area: t["area_mm2"].as_f64(), lo: side("min", f64::min), hi: side("max", f64::max), errors, com }
}

fn boxes_com(d: &Value) -> Option<[f64; 3]> {
    let c = d["bodies"].as_array()?.iter().find_map(|b| b.get("center_of_mass").filter(|c| c.is_array()))?;
    Some([c[0].as_f64()?, c[1].as_f64()?, c[2].as_f64()?])
}

fn close(x: f64, y: f64) -> bool {
    (x - y).abs() <= REL * x.abs().max(y.abs()).max(1.0)
}

/// Whether `a` (a rebuild) is the same solid as `b` (the part's own).
pub fn same(a: Option<&Eval>, b: Option<&Eval>) -> bool {
    let (Some(a), Some(b)) = (a, b) else { return false };
    let nz = |v: Option<f64>| v.is_some_and(|x| x != 0.0);
    if !nz(a.volume) || !a.errors.is_empty() || !nz(a.area) || !nz(b.area) {
        return false;
    }
    // a reference imported as open faces has no volume: its area and box still say it all
    if nz(b.volume) && !close(a.volume.unwrap(), b.volume.unwrap()) {
        return false;
    }
    if !close(a.area.unwrap(), b.area.unwrap()) {
        return false;
    }
    if let (Some(alo), Some(ahi), Some(blo), Some(bhi)) = (a.lo, a.hi, b.lo, b.hi) {
        let size = (0..3).map(|k| bhi[k] - blo[k]).fold(f64::NEG_INFINITY, f64::max).max(1.0);
        return (0..3).all(|k| (alo[k] - blo[k]).abs() <= REL * size && (ahi[k] - bhi[k]).abs() <= REL * size);
    }
    true
}

/// Both directions must be checked and within the same relative volume tolerance.
pub fn shape_differences_within(extra: Option<f64>, missing: Option<f64>, reference_volume: f64) -> bool {
    let (Some(extra), Some(missing)) = (extra, missing) else { return false };
    let tolerance = REL * reference_volume.abs().max(1.0);
    extra.abs() <= tolerance && missing.abs() <= tolerance
}

/// Metric agreement followed by actual geometric difference in both directions.
pub fn same_shape<E: Evaluator + ?Sized>(ev: &mut E, reference: &Value, candidate: &Value) -> bool {
    let Some(volume) = ev.evaluate(reference).and_then(|r| r.volume).filter(|v| *v != 0.0) else { return false };
    let extra = ev.difference_volume(candidate, reference);
    let missing = ev.difference_volume(reference, candidate);
    shape_differences_within(extra, missing, volume)
}

fn axial_sign(value: &mut Value) {
    let Some(values) = value.as_array_mut().filter(|a| a.len() == 3) else { return };
    let negative = values.iter().filter_map(Value::as_f64).find(|v| v.abs() > 1e-12).is_some_and(|v| v < 0.0);
    if negative {
        for value in values {
            if let Some(v) = value.as_f64() {
                *value = json!(-v);
            }
        }
    }
}

fn canonical_face(face: &Value) -> Option<Value> {
    let mut face = face.as_object()?.clone();
    face.remove("name");
    face.remove("index");
    // A point anywhere on a face's infinite surface is not a stable boundary measurement.
    face.remove("point");
    if let Some(normal) = face.get_mut("plane_normal") {
        axial_sign(normal);
    }
    if let Some(cylinder) = face.get_mut("cylinder").and_then(Value::as_object_mut) {
        if let Some(axis) = cylinder.get_mut("axis") {
            axial_sign(axis);
        }
        // Moving a cylinder's origin along its axis describes the same infinite surface.
        let axis = cylinder.get("axis")?.as_array()?.iter().map(Value::as_f64).collect::<Option<Vec<_>>>()?;
        let origin = cylinder.get("origin")?.as_array()?.iter().map(Value::as_f64).collect::<Option<Vec<_>>>()?;
        if axis.len() != 3 || origin.len() != 3 {
            return None;
        }
        let along = axis.iter().zip(&origin).map(|(a, p)| a * p).sum::<f64>();
        cylinder["origin"] = json!(origin.iter().zip(&axis).map(|(p, a)| p - along * a).collect::<Vec<_>>());
    }
    Some(Value::Object(face))
}

fn geometry_close(a: &Value, b: &Value, key: &str, scale: f64) -> bool {
    match (a, b) {
        (Value::Number(a), Value::Number(b)) => {
            let (Some(a), Some(b)) = (a.as_f64(), b.as_f64()) else { return false };
            let tolerance = REL * if key == "area" { a.abs().max(b.abs()).max(1.0) } else { scale };
            (a - b).abs() <= tolerance
        }
        (Value::Array(a), Value::Array(b)) => {
            a.len() == b.len() && a.iter().zip(b).all(|(x, y)| geometry_close(x, y, key, scale))
        }
        (Value::Object(a), Value::Object(b)) => {
            a.len() == b.len() && a.iter().all(|(k, x)| b.get(k).is_some_and(|y| geometry_close(x, y, k, scale)))
        }
        _ => a == b,
    }
}

/// Position-sensitive face geometry for hosts whose private evaluation permits only inspection.
/// Every saved face must match a distinct rebuilt face's surface, area and centre. Missing or
/// unsupported face information rejects the rebuild; this never falls back to totals alone.
pub fn check_shape_by_faces<E: Evaluator + ?Sized>(ev: &mut E, reference: &Value, candidate: &Value) -> Result<(), &'static str> {
    let (Some(a), Some(b)) = (ev.evaluate(candidate), ev.evaluate(reference)) else {
        return Err("face check: evaluation failed");
    };
    if !same(Some(&a), Some(&b)) {
        return Err("face check: measurements differ");
    }
    let scale = match (b.lo, b.hi) {
        (Some(lo), Some(hi)) => (0..3).map(|k| hi[k] - lo[k]).fold(f64::NEG_INFINITY, f64::max).max(1.0),
        _ => return Err("face check: no reference bounds"),
    };
    let (Some(reference_faces), Some(candidate_faces)) = (ev.faces(reference), ev.faces(candidate)) else {
        return Err("face check: inspection unavailable");
    };
    let (Some(reference_faces), Some(candidate_faces)) = (reference_faces.as_array(), candidate_faces.as_array()) else {
        return Err("face check: inspection did not return arrays");
    };
    if reference_faces.is_empty() || reference_faces.len() != candidate_faces.len() {
        return Err("face check: no faces or different face counts");
    }
    if reference_faces.iter().chain(candidate_faces).any(|f| !f["exact"].as_bool().unwrap_or(false)) {
        return Err("face check: a face has no exact geometry");
    }
    let Some(wanted) = reference_faces.iter().map(canonical_face).collect::<Option<Vec<_>>>() else {
        return Err("face check: invalid reference face");
    };
    let Some(mut remaining) = candidate_faces.iter().map(canonical_face).collect::<Option<Vec<_>>>() else {
        return Err("face check: invalid rebuilt face");
    };
    for face in wanted {
        let Some(index) = remaining.iter().position(|other| geometry_close(&face, other, "", scale)) else {
            return Err("face check: no matching rebuilt face");
        };
        remaining.remove(index);
    }
    Ok(())
}

pub fn same_shape_by_faces<E: Evaluator + ?Sized>(ev: &mut E, reference: &Value, candidate: &Value) -> bool {
    check_shape_by_faces(ev, reference, candidate).is_ok()
}

/// How far apart two evaluations are, for keeping the closest attempt.
pub fn gap(a: &Eval, b: &Eval) -> f64 {
    let (va, vb) = (a.volume.unwrap_or(0.0), b.volume.unwrap_or(0.0));
    let (aa, ab) = (a.area.unwrap_or(0.0), b.area.unwrap_or(0.0));
    (va - vb).abs() / vb.abs().max(1e-9) + (aa - ab).abs() / ab.abs().max(1e-9) + if a.errors.is_empty() { 0.0 } else { 1.0 }
}

/// Whether the tree is read whole: nothing TBD, every sketch on a plane with no problems, and a
/// feature that makes a solid.
pub fn fully_decoded(feats: &[Feature]) -> bool {
    if feats.is_empty() {
        return false;
    }
    if feats.iter().any(|f| f.kind == "tbd" || (!f.reason.is_empty() && f.kind != "absorbed")) {
        return false;
    }
    if feats.iter().any(|f| f.kind == "sketch" && f.sketch.as_ref().is_none_or(|s| s.planes.is_empty() || !s.problems.is_empty())) {
        return false;
    }
    // an import is a solid to build on when its body as imported is in the file
    if feats.iter().any(|f| f.kind == "import" && f.import_body.is_none()) {
        return false;
    }
    feats.iter().any(|f| ["boss", "cut", "revolve", "revcut", "sweep"].contains(&f.kind.as_str()))
}

/// Why a rebuild doesn't match, in the shape of a cause.
pub fn mismatch_signature(ours: Option<&Eval>, rf: Option<&Eval>) -> String {
    let Some(ours) = ours else { return "no build to compare".into() };
    if let Some(msg) = ours.errors.first() {
        let msg = msg.strip_prefix("not supported yet: ").unwrap_or(msg);
        return format!("does not build: {}", msg.split(". ").next().unwrap_or(""));
    }
    let (Some(ov), Some(r)) = (ours.volume.filter(|v| *v != 0.0), rf) else { return "no volume to compare".into() };
    let Some(rv) = r.volume.filter(|v| *v != 0.0) else { return "no volume to compare".into() };
    let dv = (ov - rv) / rv.abs();
    let da = match (ours.area, r.area.filter(|a| *a != 0.0)) {
        (Some(oa), Some(ra)) => (oa - ra) / ra.abs(),
        _ => 0.0,
    };
    let pct = |x: f64, d: usize| format!("{:+.*}%", d, x * 100.0);
    if dv.abs() <= REL && da.abs() > REL {
        return format!("same volume, area {}: a fillet or chamfer is missing or wrong", pct(da, 1));
    }
    if dv > REL {
        return format!("too much material ({}): a loop is an island, or a cut didn't take", pct(dv, 1));
    }
    if dv < -REL {
        return format!("too little material ({}): a feature is missing, or its direction is wrong", pct(dv, 1));
    }
    if let (Some(ol), Some(oh), Some(rl), Some(rh)) = (ours.lo, ours.hi, r.lo, r.hi) {
        let d: Vec<f64> = (0..3).map(|k| ol[k] - rl[k]).chain((0..3).map(|k| oh[k] - rh[k])).collect();
        if d.iter().any(|x| x.abs() > 0.1) {
            return format!("volume and area agree, the box doesn't: {} mm (lo, hi)", d.iter().map(|x| format!("{x:+.2}")).collect::<Vec<_>>().join(", "));
        }
    }
    format!("close but not within 0.1 %: volume {}, area {}", pct(dv, 2), pct(da, 2))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::collections::VecDeque;

    #[test]
    fn shape_differences_require_both_directions_within_tolerance() {
        assert!(!shape_differences_within(None, None, 1.0));
        assert!(!shape_differences_within(Some(0.0), None, 1000.0));
        assert!(shape_differences_within(Some(0.5), Some(0.5), 1000.0));
        assert!(!shape_differences_within(Some(2.0), Some(0.0), 1000.0));
        assert!(!shape_differences_within(Some(0.0), Some(-2.0), 1000.0));
    }

    #[derive(Default)]
    struct DifferenceEval {
        differences: VecDeque<Option<f64>>,
        calls: Vec<String>,
    }

    impl Evaluator for DifferenceEval {
        fn evaluate(&mut self, _design: &Value) -> Option<Eval> {
            Some(Eval { volume: Some(1000.0), ..Default::default() })
        }
        fn edges(&mut self, _design: &Value) -> Option<Value> { Some(json!([])) }
        fn faces(&mut self, _design: &Value) -> Option<Value> { Some(json!([])) }
        fn difference_volume(&mut self, target: &Value, tool: &Value) -> Option<f64> {
            self.calls.push(format!("{}-{}", target["id"].as_str().unwrap(), tool["id"].as_str().unwrap()));
            self.differences.pop_front().unwrap_or(None)
        }
        fn now(&self) -> f64 { 0.0 }
    }

    #[test]
    fn same_shape_checks_candidate_minus_reference_then_the_reverse() {
        let mut ev = DifferenceEval { differences: VecDeque::from([Some(0.0), Some(0.0)]), ..Default::default() };
        assert!(same_shape(&mut ev, &json!({"id": "reference"}), &json!({"id": "candidate"})));
        assert_eq!(ev.calls, ["candidate-reference", "reference-candidate"]);
    }

    #[test]
    fn face_geometry_is_position_sensitive_but_ignores_surface_orientation() {
        let face = json!({"name": "F1", "index": 1, "point": [5.0, 5.0, 0.0], "area": 100.0,
                          "centroid": [0.0, 0.0, 0.0], "plane_normal": [0.0, 0.0, -1.0], "exact": true});
        let mut equivalent = face.clone();
        equivalent["name"] = json!("another name");
        equivalent["index"] = json!(7);
        equivalent["point"] = json!([20.0, 20.0, 0.0]);
        equivalent["plane_normal"] = json!([0.0, 0.0, 1.0]);
        let mut shifted = face.clone();
        shifted["centroid"] = json!([0.0, 0.0, 20.0]);
        let (a, b, c) = (canonical_face(&face).unwrap(), canonical_face(&equivalent).unwrap(), canonical_face(&shifted).unwrap());
        assert!(geometry_close(&a, &b, "", 100.0));
        assert!(!geometry_close(&a, &c, "", 100.0));
    }

    #[test]
    fn same_shape_rejects_a_failed_difference() {
        let mut ev = DifferenceEval { differences: VecDeque::from([None, Some(0.0)]), ..Default::default() };
        assert!(!same_shape(&mut ev, &json!({"id": "reference"}), &json!({"id": "candidate"})));
        assert_eq!(ev.calls.len(), 2);
    }
}
