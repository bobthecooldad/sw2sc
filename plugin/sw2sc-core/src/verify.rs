//! Check a part's rebuilt feature tree against the solid SolidWorks saved (port of
//! `sw2sc/verify.py`).
//!
//! The feature tree read by `features` is written as SolidCraft features and evaluated; it is
//! used only when its volume, surface area and bounding box match the part's own solid within
//! 0.1 %. What the file leaves open (an extrude's direction, which plane a sketch uses, a
//! fillet's edges …) is settled by trying the candidates the file gives and keeping the one
//! that matches. SolidCraft itself is reached through [`Evaluator`]: `solidcraft-cli` when run
//! natively, the plugin host's `evaluate` interface inside the importer.

use serde_json::Value;

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
