//! SolidCraft designs from the features read (port of the writer half of `sw2sc/features.py`:
//! `sketch_feature`, the constraints, loops, `extrude_feature`, `design` and `design_tail`).
//!
//! The rebuild check's choices travel as JSON values keyed like the Python's dicts: `choices`
//! holds each extrude's `[direction, operation]`, a revolve's `[axis index, sign]` and
//! `arcs:<sketch>` flips; `picks` (the Python's `fillets`) holds the rest (`flip:`, `hole:`,
//! `mirror:` … and a fillet's edges under its name).

use std::collections::{BTreeSet, HashMap, HashSet};

use indexmap::IndexMap;
use serde_json::{json, Map, Value};

use crate::features::sketch::{select_sketch_loops, with_centres};
use crate::features::{Feature, Handle, Sketch};
use crate::pyfmt::{g, repr, round};

pub type Choices = HashMap<String, Value>;

/// The rebuild check's picks: JSON values by key (as the Python's `fillets` dict), and the
/// assignments of SolidWorks faces earlier fillets left open (the Python's `fillets[""]`).
#[derive(Clone, Debug, Default)]
pub struct Picks {
    pub v: IndexMap<String, Value>,
    pub known: Option<std::rc::Rc<Vec<crate::fillets::Amap>>>,
}

impl Picks {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn get(&self, k: &str) -> Option<&Value> {
        self.v.get(k)
    }

    /// A copy with `k` set.
    pub fn with(&self, k: &str, v: Value) -> Self {
        let mut p = self.clone();
        p.v.insert(k.to_string(), v);
        p
    }
}

fn dist(a: (f64, f64), b: (f64, f64)) -> f64 {
    (a.0 - b.0).hypot(a.1 - b.1)
}

fn key9(p: (f64, f64)) -> (i64, i64) {
    // Python's (round(x, 9), round(y, 9)) as a hashable key
    ((round(p.0, 9) * 1e9).round() as i64, (round(p.1, 9) * 1e9).round() as i64)
}

/// A SolidCraft parameter name for SolidWorks' `D1@Sketch2`: `Sketch2_D1`.
pub fn param_name(sketch: &str, dim: &str) -> String {
    let n: String = format!("{sketch}_{dim}").chars().map(|c| if c.is_alphanumeric() || c == '_' { c } else { '_' }).collect();
    // a leading digit would be read as a number by SolidCraft's expressions (see the Python)
    if n.chars().next().is_some_and(|c| c.is_ascii_digit()) { format!("_{n}") } else { n }
}

/// A SolidCraft sketch feature: the sketch on a custom plane (origin, x and y directions in
/// model space, mm), its points and curves. Sets the sketch's params, offsets, skips.
pub fn sketch_feature(sk: &mut Sketch, fid: i64, constraints: bool) -> Value {
    let ([x, y, _n], t) = sk.plane().expect("a sketch with a plane");
    let mut pts: Vec<Value> = vec![json!({"fixed": true, "id": "origin", "pos": [0.0, 0.0]})];
    let mut index: IndexMap<u32, usize> = IndexMap::new();
    let points = sk.points.clone();
    let pt = |pid: u32, pts: &mut Vec<Value>, index: &mut IndexMap<u32, usize>| -> usize {
        if let Some(&i) = index.get(&pid) {
            return i;
        }
        let (u, v) = points[&pid];
        if pid == 1 && u.abs() < 1e-12 && v.abs() < 1e-12 {
            index.insert(pid, 0); // SolidWorks' point 1 is the sketch origin: SolidCraft's fixed origin
            return 0;
        }
        let i = pts.len();
        index.insert(pid, i);
        pts.push(json!({"fixed": false, "id": format!("p{pid}"), "pos": [u * 1000.0, v * 1000.0]}));
        i
    };
    let mut curves: Vec<Value> = Vec::new();
    for (n, &(a, c)) in sk.lines.iter().enumerate() {
        let (ia, ic) = (pt(a, &mut pts, &mut index), pt(c, &mut pts, &mut index));
        curves.push(json!({"a": ia, "b": ic, "construction": sk.construction.contains(&n), "id": format!("l{}", n + 1), "type": "line"}));
    }
    for (n, &(a, c, ctr)) in sk.arcs.iter().enumerate() {
        let (a, c) = arc_ends(sk, a, c, ctr);
        let (ia, ic, ictr) = (pt(a, &mut pts, &mut index), pt(c, &mut pts, &mut index), pt(ctr, &mut pts, &mut index));
        curves.push(json!({"a": ia, "b": ic, "c": ictr, "construction": false, "id": format!("a{}", n + 1), "type": "arc"}));
    }
    for (n, &(ctr, r)) in sk.circles.iter().enumerate() {
        let ic = pt(ctr, &mut pts, &mut index);
        curves.push(json!({"c": ic, "construction": false, "id": format!("c{}", n + 1), "r": r * 1000.0, "type": "circle"}));
    }
    let mut ids: Vec<u32> = sk.points.keys().copied().collect();
    ids.sort();
    for pid in ids {
        pt(pid, &mut pts, &mut index);
    }
    let plane = json!({"type": "custom", "plane": {"origin": [t[0] * 1000.0, t[1] * 1000.0, t[2] * 1000.0], "x_dir": x, "y_dir": y}});
    let (cons, params) = if constraints { sketch_constraints(sk, &index, &curves) } else { (vec![], vec![]) };
    sk.params = params;
    let k = cons.len();
    json!({"id": fid, "name": sk.name, "plane": plane, "suppressed": false, "type": "sketch",
           "sketch": {"constraints": cons, "curves": curves, "points": pts,
                      "counters": {"a": sk.arcs.len(), "c": sk.circles.len(), "k": k, "l": sk.lines.len()}}})
}

fn curve_key(kind: &str, h: u32) -> (String, u16) {
    (kind.to_string(), h as u16)
}

fn dimension_point_options(handles: &[Handle], p: &IndexMap<u32, (f64, f64)>, mode: &str) -> Vec<Vec<u32>> {
    let mut seen = HashSet::new();
    let mut out = Vec::new();
    for h in handles {
        if h.cls != "sgPointHandle" || !seen.insert((h.cls.clone(), h.id)) {
            continue;
        }
        let mut options = Vec::new();
        if mode == "offset" {
            if let Some(pid) = h.id.checked_add(1).filter(|pid| p.contains_key(pid)) {
                options.push(pid);
            }
        } else if mode == "direct" {
            if h.id == 0 || p.contains_key(&h.id) {
                options.push(h.id);
            }
        } else {
            let raw_count = p.len() - usize::from(p.keys().last() == Some(&0));
            if (h.id as usize) < raw_count {
                if let Some((pid, _)) = p.get_index(h.id as usize) {
                    options.push(*pid);
                }
            }
        }
        out.push(options);
    }
    out
}

fn point_distance(cls: &str, val: f64, a: u32, b: u32, p: &IndexMap<u32, (f64, f64)>, pidx: impl Fn(u32) -> Option<usize>) -> Option<Map<String, Value>> {
    let ((ax, ay), (bx, by)) = (p[&a], p[&b]);
    let (pi, qi) = (pidx(a)?, pidx(b)?);
    if cls == "sgPntPntHorDist" {
        if ((bx - ax).abs() - val).abs() < 1e-9 {
            let (a, b) = if bx >= ax { (pi, qi) } else { (qi, pi) };
            return Some(obj(json!({"type": "distance_x", "p": a, "q": b})));
        }
        return None;
    }
    if cls == "sgPntPntVertDist" {
        if ((by - ay).abs() - val).abs() < 1e-9 {
            let (a, b) = if by >= ay { (pi, qi) } else { (qi, pi) };
            return Some(obj(json!({"type": "distance_y", "p": a, "q": b})));
        }
        return None;
    }
    if ((bx - ax).hypot(by - ay) - val).abs() < 1e-9 {
        return Some(obj(json!({"type": "distance", "p": pi, "q": qi})));
    }
    None
}

/// The sketch's dimensions as SolidCraft driving dimensions, each with a model parameter named
/// after the SolidWorks one; a dimension whose value doesn't match a reading is left out.
fn sketch_constraints(sk: &mut Sketch, index: &IndexMap<u32, usize>, curves: &[Value]) -> (Vec<Value>, Vec<Value>) {
    let mut p = sk.points.clone();
    p.entry(0).or_insert((0.0, 0.0));
    let cindex: HashMap<String, usize> = curves.iter().enumerate().map(|(n, c)| (c["id"].as_str().unwrap().to_string(), n)).collect();
    let mut cons: Vec<Value> = Vec::new();
    let mut params: Vec<Value> = Vec::new();
    sk.dims_skipped = vec![];
    sk.offsets = vec![];
    let mut offset_done: HashSet<String> = HashSet::new();
    let mut origin: Vec<u32> = vec![0];
    origin.extend(p.iter().filter(|(pid, (u, v))| **pid == 1 && u.abs() < 1e-12 && v.abs() < 1e-12).map(|(k, _)| *k));
    let pidx = |pid: u32| -> Option<usize> { if origin.contains(&pid) { Some(0) } else { index.get(&pid).copied() } };
    for d in sk.dims.clone() {
        let mut curve_seen = HashSet::new();
        let crv: Vec<(String, u16)> = d
            .handles
            .iter()
            .filter(|h| h.cls == "sgLineHandle" || h.cls == "sgArcHandle")
            .map(|h| curve_key(if h.cls == "sgLineHandle" { "line" } else { "arc" }, h.id))
            .filter(|key| curve_seen.insert(key.clone()))
            .collect();
        let (val, cls) = (d.value, d.cls.as_str());
        let mm = val * 1000.0;
        let mut con: Option<Map<String, Value>> = None;
        if ["sgPntPntDist", "sgPntPntHorDist", "sgPntPntVertDist"].contains(&cls) {
            for mode in ["offset", "direct", "position"] {
                let pts = dimension_point_options(&d.handles, &p, mode);
                let mut matches = IndexMap::new();
                if pts.len() == 2 && pts.iter().all(|options| !options.is_empty()) {
                    for &a in &pts[0] {
                        for &b in &pts[1] {
                            if let Some(candidate) = point_distance(cls, val, a, b, &p, pidx) {
                                if let Ok(key) = serde_json::to_string(&candidate) {
                                    matches.entry(key).or_insert(candidate);
                                }
                            }
                        }
                    }
                }
                let matched = !matches.is_empty();
                if matches.len() == 1 {
                    con = matches.into_iter().next().map(|(_, value)| value);
                }
                if matched {
                    break;
                }
            }
        } else if cls == "sgCircleDim" && crv.len() == 1 && sk.curve_of.contains_key(&crv[0]) {
            let cid = sk.curve_of[&crv[0]].clone();
            let c = &curves[cindex[&cid]];
            let mut r = c.get("r").and_then(Value::as_f64);
            if r.is_none() {
                // an arc: its radius from its points
                let ci = c["c"].as_u64().unwrap() as usize;
                let ai = c["a"].as_u64().unwrap() as usize;
                let ctr = index.iter().find(|(_, v)| **v == ci).map(|(k, _)| *k);
                let st = index.iter().find(|(_, v)| **v == ai).map(|(k, _)| *k);
                if let (Some(ctr), Some(st)) = (ctr, st) {
                    r = Some(dist(p[&st], p[&ctr]) * 1000.0);
                }
            }
            if let Some(r) = r {
                if (r - mm).abs() < 1e-6 {
                    con = Some(obj(json!({"type": "radius", "c": cindex[&cid]})));
                } else if (2.0 * r - mm).abs() < 1e-6 {
                    con = Some(obj(json!({"type": "diameter", "c": cindex[&cid]})));
                }
            }
        } else if cls == "sgPntLineDist" {
            for mode in ["offset", "direct", "position"] {
                let pts = dimension_point_options(&d.handles, &p, mode);
                let mut matches = IndexMap::new();
                for options in &pts {
                    for &pid in options {
                        for curve in &crv {
                            if curve.0 != "line" {
                                continue;
                            }
                            let Some(cid) = sk.curve_of.get(curve) else { continue };
                            let Some(&ci) = cindex.get(cid) else { continue };
                            let Some(&(a, b)) = cid[1..].parse::<usize>().ok().and_then(|n| sk.lines.get(n.saturating_sub(1))) else { continue };
                            let (pa, pb) = (p[&a], p[&b]);
                            let (dx, dy) = (pb.0 - pa.0, pb.1 - pa.1);
                            let length = dx.hypot(dy);
                            let distance = if length > 0.0 { ((p[&pid].0 - pa.0) * dy - (p[&pid].1 - pa.1) * dx).abs() / length } else { -1.0 };
                            if let Some(pi) = pidx(pid) {
                                if (distance - val).abs() < 1e-9 {
                                    let candidate = obj(json!({"type": "point_line_distance", "p": pi, "l": ci}));
                                    if let Ok(key) = serde_json::to_string(&candidate) {
                                        matches.entry(key).or_insert(candidate);
                                    }
                                }
                            }
                        }
                    }
                }
                let matched = !matches.is_empty();
                if matches.len() == 1 {
                    con = matches.into_iter().next().map(|(_, value)| value);
                }
                if matched {
                    break;
                }
            }
        } else if cls == "sgSkOffsetDim" {
            let pname = param_name(&sk.name, &d.name);
            let (off, lp, sources) = offset_constraints(sk, index, &cindex, val, &pname, &mut offset_done);
            if !off.is_empty() {
                sk.offsets.push(json!({"loop": lp, "sources": sources, "param": pname, "value": round(mm, 9)}));
                for mut c in off {
                    c.insert("id".into(), json!(format!("k{}", cons.len() + 1)));
                    cons.push(Value::Object(c));
                }
                params.push(json!({"name": pname, "expr": repr(round(mm, 9)), "model": true, "unit": "mm"}));
                continue;
            }
        }
        let Some(mut c) = con else {
            sk.dims_skipped.push(format!("{} ({})", d.name, cls));
            continue;
        };
        let pname = param_name(&sk.name, &d.name);
        c.insert("id".into(), json!(format!("k{}", cons.len() + 1)));
        c.insert("param".into(), json!(pname));
        c.insert("value".into(), json!(round(mm, 9)));
        cons.push(Value::Object(c));
        params.push(json!({"name": pname, "expr": repr(round(mm, 9)), "model": true, "unit": "mm"}));
    }
    for mut c in relation_constraints(sk, index, curves) {
        c.insert("id".into(), json!(format!("k{}", cons.len() + 1)));
        cons.push(Value::Object(c));
    }
    (cons, params)
}

fn obj(v: Value) -> Map<String, Value> {
    match v {
        Value::Object(m) => m,
        _ => Map::new(),
    }
}

/// An offset (`sgSkOffsetDim`) as SolidCraft constraints: parallel + point-line distance for
/// lines, concentric for arcs, tangent where an offset arc meets an offset line. Nothing if any
/// offset curve has no partner.
fn offset_constraints(
    sk: &Sketch, index: &IndexMap<u32, usize>, cindex: &HashMap<String, usize>, val: f64, pname: &str, done: &mut HashSet<String>,
) -> (Vec<Map<String, Value>>, Vec<String>, Vec<String>) {
    let p = &sk.points;
    let mut named: HashSet<Option<String>> = HashSet::new();
    for r in &sk.relations {
        for grp in &r.groups {
            for h in grp {
                if h.cls != "point" {
                    named.insert(sk.curve_of.get(&curve_key(&h.cls, h.id)).cloned());
                }
            }
        }
    }
    for d in &sk.dims {
        for h in &d.handles {
            if h.cls == "sgLineHandle" || h.cls == "sgArcHandle" {
                named.insert(sk.curve_of.get(&curve_key(if h.cls == "sgLineHandle" { "line" } else { "arc" }, h.id)).cloned());
            }
        }
    }
    let lines: IndexMap<String, (u32, u32)> =
        sk.lines.iter().enumerate().filter(|(n, _)| !sk.construction.contains(n)).map(|(n, l)| (format!("l{}", n + 1), *l)).collect();
    let mut arcs: IndexMap<String, ((f64, f64), f64)> =
        sk.arcs.iter().enumerate().map(|(n, a)| (format!("a{}", n + 1), (p[&a.2], dist(p[&a.0], p[&a.2])))).collect();
    for (n, (c, r)) in sk.circles.iter().enumerate() {
        arcs.insert(format!("c{}", n + 1), (p[c], *r));
    }
    let all: Vec<String> = lines.keys().chain(arcs.keys()).cloned().collect();
    let unnamed: BTreeSet<String> =
        all.iter().filter(|k| !named.contains(&Some((*k).clone())) && !done.contains(*k) && cindex.contains_key(*k)).cloned().collect();
    if unnamed.is_empty() {
        return (vec![], vec![], vec![]);
    }
    // the whole loop an unnamed curve is on is the offset
    let mut free: Vec<String> = Vec::new();
    for (ids, _poly) in loops(sk) {
        if ids.iter().any(|i| unnamed.contains(i)) {
            free.extend(ids.iter().filter(|k| !done.contains(*k) && cindex.contains_key(*k)).cloned());
        }
    }
    for k in &unnamed {
        if !free.contains(k) {
            free.push(k.clone());
        }
    }
    let named: HashSet<String> = all.iter().filter(|k| !free.contains(k)).cloned().collect();
    const T: f64 = 1e-7;
    let dist_pl = |q: (f64, f64), ln: (u32, u32)| -> f64 {
        let ((ax, ay), (bx, by)) = (p[&ln.0], p[&ln.1]);
        let l = (bx - ax).hypot(by - ay);
        if l != 0.0 { ((q.0 - ax) * (by - ay) - (q.1 - ay) * (bx - ax)).abs() / l } else { -1.0 }
    };
    let mut out: Vec<Map<String, Value>> = Vec::new();
    let mut sources: Vec<String> = Vec::new();
    for k in &free {
        if let Some(&(a, b)) = lines.get(k) {
            let partner = lines
                .iter()
                .find(|(k2, ln2)| named.contains(*k2) && (dist_pl(p[&a], **ln2) - val).abs() < T && (dist_pl(p[&b], **ln2) - val).abs() < T)
                .map(|(k2, _)| k2.clone());
            let Some(partner) = partner else { return (vec![], vec![], vec![]) };
            out.push(obj(json!({"type": "parallel", "a": cindex[k], "b": cindex[&partner]})));
            out.push(obj(json!({"type": "point_line_distance", "p": index[&a], "l": cindex[&partner], "param": pname, "value": round(val * 1000.0, 9)})));
            sources.push(partner);
        } else {
            let (c, r) = arcs[k];
            let partner = arcs
                .iter()
                .find(|(k2, (c2, r2))| named.contains(*k2) && dist(c, *c2) < T && ((r - r2).abs() - val).abs() < T)
                .map(|(k2, _)| k2.clone());
            let Some(partner) = partner else { return (vec![], vec![], vec![]) };
            out.push(obj(json!({"type": "concentric", "a": cindex[k], "b": cindex[&partner]})));
            sources.push(partner);
            if let Some(n) = k.strip_prefix('a') {
                let n: usize = n.parse::<usize>().unwrap() - 1;
                let (s0, e0, ctr) = sk.arcs[n];
                for (kl, &(la, lb)) in &lines {
                    if !free.contains(kl) {
                        continue;
                    }
                    for end in [s0, e0] {
                        if (end == la || end == lb) && (dist_pl(p[&ctr], (la, lb)) - r).abs() < T {
                            out.push(obj(json!({"type": "tangent", "a": cindex[k], "b": cindex[kl]})));
                        }
                    }
                }
            }
        }
    }
    done.extend(free.iter().cloned());
    (out, free, sources)
}

#[derive(Clone, Copy)]
enum Ent {
    Point(usize, (f64, f64)),
    Line(usize, ((f64, f64), (f64, f64))),
    Arc(usize, ((f64, f64), f64)),
}

impl Ent {
    fn idx(&self) -> usize {
        match self {
            Ent::Point(i, _) | Ent::Line(i, _) | Ent::Arc(i, _) => *i,
        }
    }
}

/// The sketch's relations as SolidCraft constraints (types decoded: 4 horizontal, 5 vertical,
/// 6 tangent, 7 parallel, 8 perpendicular, 9 coincident / on curve, 12 midpoint, 13 at two lines'
/// intersection, 14 / 57 equal, 27 collinear, 28 concentric, 11 symmetric, 25 / 26 level or
/// plumb), written only when they hold in the sketch as read.
fn relation_constraints(sk: &mut Sketch, index: &IndexMap<u32, usize>, curves: &[Value]) -> Vec<Map<String, Value>> {
    let p = sk.points.clone();
    let cindex: HashMap<String, usize> = curves.iter().enumerate().map(|(n, c)| (c["id"].as_str().unwrap().to_string(), n)).collect();
    const T: f64 = 1e-9;
    let mut out: Vec<Map<String, Value>> = Vec::new();
    sk.relations_skipped = 0;
    let ent = |kind: &str, hid: u32| -> Option<Ent> {
        if kind == "point" {
            let pid = hid + 1;
            if !p.contains_key(&pid) || !index.contains_key(&pid) {
                return None;
            }
            return Some(Ent::Point(index[&pid], p[&pid]));
        }
        let key = sk.curve_of.get(&curve_key(kind, hid))?;
        let ci = *cindex.get(key)?;
        let n: usize = key[1..].parse::<usize>().ok()? - 1;
        match &key[..1] {
            "l" => {
                let (a, b) = sk.lines[n];
                Some(Ent::Line(ci, (p[&a], p[&b])))
            }
            "a" => {
                let (a, _b, c) = sk.arcs[n];
                Some(Ent::Arc(ci, (p[&c], dist(p[&a], p[&c]))))
            }
            _ => {
                let (c, r) = sk.circles[n];
                Some(Ent::Arc(ci, (p[&c], r)))
            }
        }
    };
    let dv = |l: ((f64, f64), (f64, f64))| (l.1 .0 - l.0 .0, l.1 .1 - l.0 .1);
    let on_line = |q: (f64, f64), l: ((f64, f64), (f64, f64))| {
        let d = dv(l);
        let n = d.0.hypot(d.1);
        n > T && ((q.0 - l.0 .0) * d.1 - (q.1 - l.0 .1) * d.0).abs() <= T * n
    };
    let cross_dot = |l1, l2| {
        let (u, v) = (dv(l1), dv(l2));
        let n = u.0.hypot(u.1) * v.0.hypot(v.1);
        if n != 0.0 { ((u.0 * v.1 - u.1 * v.0).abs() / n, (u.0 * v.0 + u.1 * v.1).abs() / n) } else { (1.0, 1.0) }
    };
    let mut skipped = 0;
    for rel in sk.relations.clone() {
        let t = rel.kind;
        for grp in &rel.groups {
            let es: Vec<Option<Ent>> = grp.iter().map(|h| ent(&h.cls, h.id)).collect();
            if es.is_empty() || es.iter().any(Option::is_none) {
                skipped += 1;
                continue;
            }
            let es: Vec<Ent> = es.into_iter().map(Option::unwrap).collect();
            let ls: Vec<(usize, ((f64, f64), (f64, f64)))> = es.iter().filter_map(|e| if let Ent::Line(i, l) = e { Some((*i, *l)) } else { None }).collect();
            let as_: Vec<(usize, ((f64, f64), f64))> = es.iter().filter_map(|e| if let Ent::Arc(i, a) = e { Some((*i, *a)) } else { None }).collect();
            let ps: Vec<(usize, (f64, f64))> = es.iter().filter_map(|e| if let Ent::Point(i, q) = e { Some((*i, *q)) } else { None }).collect();
            let only_line = es.len() == 1 && ls.len() == 1;
            let mut con: Option<Vec<Value>> = None;
            if t == 4 && only_line && dv(ls[0].1).1.abs() < T {
                con = Some(vec![json!({"type": "horizontal", "l": ls[0].0})]);
            } else if t == 5 && only_line && dv(ls[0].1).0.abs() < T {
                con = Some(vec![json!({"type": "vertical", "l": ls[0].0})]);
            } else if t == 6 && es.len() == 2 && ps.is_empty() {
                if as_.len() == 1 && ls.len() == 1 {
                    let ((c, r), l) = (as_[0].1, ls[0].1);
                    let d = dv(l);
                    let n = d.0.hypot(d.1);
                    if n != 0.0 && (((c.0 - l.0 .0) * d.1 - (c.1 - l.0 .1) * d.0).abs() / n - r).abs() < T {
                        con = Some(vec![json!({"type": "tangent", "a": es[0].idx(), "b": es[1].idx()})]);
                    }
                } else if as_.len() == 2 {
                    let dd = dist(as_[0].1 .0, as_[1].1 .0);
                    if (dd - (as_[0].1 .1 + as_[1].1 .1)).abs() < T || (dd - (as_[0].1 .1 - as_[1].1 .1).abs()).abs() < T {
                        con = Some(vec![json!({"type": "tangent", "a": es[0].idx(), "b": es[1].idx()})]);
                    }
                }
            } else if (t == 7 || t == 8 || t == 27) && ls.len() == 2 && es.len() == 2 {
                let (c_, d_) = cross_dot(ls[0].1, ls[1].1);
                if t == 7 && c_ < T {
                    con = Some(vec![json!({"type": "parallel", "a": ls[0].0, "b": ls[1].0})]);
                } else if t == 8 && d_ < T {
                    con = Some(vec![json!({"type": "perpendicular", "a": ls[0].0, "b": ls[1].0})]);
                } else if t == 27 && c_ < T && on_line(ls[1].1 .0, ls[0].1) {
                    con = Some(vec![json!({"type": "collinear", "a": ls[0].0, "b": ls[1].0})]);
                }
            } else if (t == 14 || t == 57) && es.len() == 2 && ps.is_empty() {
                if ls.len() == 2 {
                    let (a, b) = (dv(ls[0].1), dv(ls[1].1));
                    if (a.0.hypot(a.1) - b.0.hypot(b.1)).abs() < T {
                        con = Some(vec![json!({"type": "equal", "a": ls[0].0, "b": ls[1].0})]);
                    }
                } else if as_.len() == 2 && (as_[0].1 .1 - as_[1].1 .1).abs() < T {
                    con = Some(vec![json!({"type": "equal", "a": as_[0].0, "b": as_[1].0})]);
                }
            } else if t == 28 && as_.len() == 2 && es.len() == 2 && dist(as_[0].1 .0, as_[1].1 .0) < T {
                con = Some(vec![json!({"type": "concentric", "a": as_[0].0, "b": as_[1].0})]);
            } else if (t == 9 || t == 12) && es.len() == 2 {
                if ps.len() == 2 && dist(ps[0].1, ps[1].1) < T && ps[0].0 != ps[1].0 {
                    con = Some(vec![json!({"type": "coincident", "p": ps[0].0, "q": ps[1].0})]);
                } else if ps.len() == 1 && ls.len() == 1 && on_line(ps[0].1, ls[0].1) {
                    let l = ls[0].1;
                    let m = ((l.0 .0 + l.1 .0) / 2.0, (l.0 .1 + l.1 .1) / 2.0);
                    con = Some(vec![if t == 12 && dist(ps[0].1, m) < T {
                        json!({"type": "midpoint", "p": ps[0].0, "l": ls[0].0})
                    } else {
                        json!({"type": "point_on_curve", "p": ps[0].0, "c": ls[0].0})
                    }]);
                } else if ps.len() == 1 && as_.len() == 1 && (dist(ps[0].1, as_[0].1 .0) - as_[0].1 .1).abs() < T {
                    con = Some(vec![json!({"type": "point_on_curve", "p": ps[0].0, "c": as_[0].0})]);
                }
            } else if t == 13 && ps.len() == 1 && ls.len() == 2 && ls.iter().all(|l| on_line(ps[0].1, l.1)) {
                con = Some(ls.iter().map(|l| json!({"type": "point_on_curve", "p": ps[0].0, "c": l.0})).collect());
            } else if t == 11 && ps.len() == 2 && ls.len() == 1 {
                let (a, b) = (ps[0].1, ps[1].1);
                let m = ((a.0 + b.0) / 2.0, (a.1 + b.1) / 2.0);
                let ab = (b.0 - a.0, b.1 - a.1);
                let d = dv(ls[0].1);
                if on_line(m, ls[0].1) && (ab.0 * d.0 + ab.1 * d.1).abs() < T * ab.0.hypot(ab.1).max(T) * d.0.hypot(d.1) {
                    con = Some(vec![json!({"type": "symmetric", "p": ps[0].0, "q": ps[1].0, "l": ls[0].0})]);
                }
            } else if (t == 25 || t == 26) && ps.len() == 2 && es.len() == 2 {
                if (ps[0].1 .1 - ps[1].1 .1).abs() < T {
                    con = Some(vec![json!({"type": "horizontal_points", "p": ps[0].0, "q": ps[1].0})]);
                } else if (ps[0].1 .0 - ps[1].1 .0).abs() < T {
                    con = Some(vec![json!({"type": "vertical_points", "p": ps[0].0, "q": ps[1].0})]);
                }
            }
            match con {
                None => skipped += 1,
                Some(cs) => out.extend(cs.into_iter().map(obj)),
            }
        }
    }
    sk.relations_skipped = skipped;
    // one constraint once (a relation can be stored twice)
    let mut seen: HashSet<String> = HashSet::new();
    out.into_iter()
        .filter(|c| {
            let mut items: Vec<(&String, &Value)> = c.iter().collect();
            items.sort_by(|a, b| a.0.cmp(b.0));
            seen.insert(serde_json::to_string(&items).unwrap())
        })
        .collect()
}

/// (start, end) so that the arc runs anticlockwise from start to end as drawn.
pub fn arc_ends(sk: &Sketch, a: u32, c: u32, ctr: u32) -> (u32, u32) {
    let p = &sk.points;
    let key = |pid: u32| key9(p[&pid]);
    let (cx, cy) = p[&ctr];
    for (e, other) in [(a, c), (c, a)] {
        for &(l1, l2) in &sk.lines {
            if key(e) != key(l1) && key(e) != key(l2) {
                continue;
            }
            let o = if key(e) == key(l1) { l2 } else { l1 };
            let (dx, dy) = (p[&e].0 - p[&o].0, p[&e].1 - p[&o].1);
            let (rx, ry) = (p[&e].0 - cx, p[&e].1 - cy);
            let l = dx.hypot(dy) * rx.hypot(ry);
            if l == 0.0 || (dx * rx + dy * ry).abs() > 1e-6 * l {
                continue;
            }
            let ccw_leaves = -ry * dx + rx * dy > 0.0;
            return if ccw_leaves { (e, other) } else { (other, e) };
        }
    }
    let ((ax, ay), (bx, by)) = (p[&a], p[&c]);
    let sweep = ((by - cy).atan2(bx - cx) - (ay - cy).atan2(ax - cx)).rem_euclid(2.0 * std::f64::consts::PI);
    if sweep > std::f64::consts::PI + 1e-12 { (c, a) } else { (a, c) }
}

pub type Poly = Vec<(f64, f64)>;

/// Closed loops of the sketch's curves: (curve ids as sketch_feature names them, a polygon
/// through the loop for nesting tests).
pub fn loops(sk: &Sketch) -> Vec<(Vec<String>, Poly)> {
    use std::f64::consts::PI;
    let p = &sk.points;
    let mut edges: Vec<(String, u32, u32, Poly)> = Vec::new();
    for (n, &(a, c)) in sk.lines.iter().enumerate() {
        if !sk.construction.contains(&n) {
            edges.push((format!("l{}", n + 1), a, c, vec![p[&a], p[&c]]));
        }
    }
    for (n, &(a, c, ctr)) in sk.arcs.iter().enumerate() {
        let (cx, cy) = p[&ctr];
        let r = (p[&a].0 - cx).hypot(p[&a].1 - cy);
        let (a2, c2) = arc_ends(sk, a, c, ctr);
        let t0 = (p[&a2].1 - cy).atan2(p[&a2].0 - cx);
        let mut t1 = (p[&c2].1 - cy).atan2(p[&c2].0 - cx);
        if t1 <= t0 {
            t1 += 2.0 * PI;
        }
        let k = 2.max(((t1 - t0) / (PI / 8.0)).ceil() as usize);
        let poly = (0..=k).map(|i| {
            let t = t0 + (t1 - t0) * i as f64 / k as f64;
            (cx + r * t.cos(), cy + r * t.sin())
        });
        edges.push((format!("a{}", n + 1), a, c, poly.collect()));
    }
    let mut out: Vec<(Vec<String>, Poly)> = Vec::new();
    for (n, &(ctr, r)) in sk.circles.iter().enumerate() {
        let (cx, cy) = p[&ctr];
        out.push((
            vec![format!("c{}", n + 1)],
            (0..16).map(|k| (cx + r * (2.0 * PI * k as f64 / 16.0).cos(), cy + r * (2.0 * PI * k as f64 / 16.0).sin())).collect(),
        ));
    }
    let key = |pid: u32| key9(p[&pid]);
    let mut at: HashMap<(i64, i64), Vec<usize>> = HashMap::new();
    for (i, e) in edges.iter().enumerate() {
        at.entry(key(e.1)).or_default().push(i);
        at.entry(key(e.2)).or_default().push(i);
    }
    let mut used: HashSet<String> = HashSet::new();
    for e in &edges {
        if used.contains(&e.0) {
            continue;
        }
        let mut ids = vec![e.0.clone()];
        let mut poly = e.3.clone();
        let mut here = key(e.2);
        used.insert(e.0.clone());
        let start = key(e.1);
        let mut ok = false;
        for _ in 0..edges.len() {
            if here == start {
                ok = true;
                break;
            }
            let nxt: Vec<usize> = at.get(&here).map_or(vec![], |v| v.iter().copied().filter(|&i| !used.contains(&edges[i].0)).collect());
            if nxt.len() != 1 {
                break;
            }
            let x = &edges[nxt[0]];
            used.insert(x.0.clone());
            ids.push(x.0.clone());
            let fwd = key(x.1) == here;
            if fwd {
                poly.extend(x.3.iter().copied());
            } else {
                poly.extend(x.3.iter().rev().copied());
            }
            here = if fwd { key(x.2) } else { key(x.1) };
        }
        if ok {
            out.push((ids, poly));
        }
    }
    out
}

pub fn inside(pt: (f64, f64), poly: &[(f64, f64)]) -> bool {
    let (x, y) = pt;
    let mut c = false;
    let n = poly.len();
    for i in 0..n {
        let ((x1, y1), (x2, y2)) = (poly[i], poly[(i + 1) % n]);
        let dy = if y2 - y1 != 0.0 { y2 - y1 } else { 1e-30 };
        if (y1 > y) != (y2 > y) && x < (x2 - x1) * (y - y1) / dy + x1 {
            c = !c;
        }
    }
    c
}

/// Lines a revolve can turn about: the sketch's lines on no closed loop, centrelines first.
pub fn revolve_axes(sk: &Sketch) -> Vec<String> {
    let in_loops: HashSet<String> = loops(sk).into_iter().flat_map(|(ids, _)| ids).collect();
    let mut free: Vec<usize> = (0..sk.lines.len()).filter(|n| !in_loops.contains(&format!("l{}", n + 1))).collect();
    free.sort_by_key(|n| !sk.construction.contains(n)); // stable
    free.into_iter().map(|n| format!("l{}", n + 1)).collect()
}

/// What a revolve may turn about, most likely first.
pub fn revolve_axis_options(sk: &Sketch) -> Vec<Value> {
    let free = revolve_axes(sk);
    let in_loops: BTreeSet<String> = loops(sk).into_iter().flat_map(|(ids, _)| ids).filter(|c| c.starts_with('l')).collect();
    let mut out: Vec<Value> = free.iter().map(|c| json!({"type": "sketch_line", "curve": c})).collect();
    out.push(json!({"type": "sketch_axis", "axis": "x"}));
    out.push(json!({"type": "sketch_axis", "axis": "y"}));
    out.extend(in_loops.iter().map(|c| json!({"type": "sketch_line", "curve": c})));
    out
}

/// The loops to extrude: those nested inside an even number of others.
pub fn profile_loops(sk: &Sketch) -> Vec<Vec<String>> {
    profile_loops_skip(sk, &[])
}

/// `profile_loops` with the loops using a curve in `skip` left out before the nesting is worked out.
pub fn profile_loops_skip(sk: &Sketch, skip: &[String]) -> Vec<Vec<String>> {
    let lps: Vec<(Vec<String>, Poly)> = loops(sk).into_iter().filter(|(ids, _)| !ids.iter().any(|c| skip.contains(c))).collect();
    let mut out = Vec::new();
    for (i, (ids, poly)) in lps.iter().enumerate() {
        let mut probe = poly[0];
        let n = poly.len();
        'edges: for j in 0..n {
            let ((x1, y1), (x2, y2)) = (poly[j], poly[(j + 1) % n]);
            let l = (x2 - x1).hypot(y2 - y1);
            if l < 1e-9 {
                continue;
            }
            let (mx, my, nx, ny) = ((x1 + x2) / 2.0, (y1 + y2) / 2.0, -(y2 - y1) / l, (x2 - x1) / l);
            for sgn in [1.0, -1.0] {
                let q = (mx + sgn * nx * 1e-6, my + sgn * ny * 1e-6);
                if inside(q, poly) {
                    probe = q;
                    break 'edges;
                }
            }
        }
        let depth = lps.iter().enumerate().filter(|(j, (_, p2))| *j != i && inside(probe, p2)).count();
        if depth % 2 == 0 {
            out.push(ids.clone());
        }
    }
    out
}

/// An extrude: `to` up to a face (a point on it), else through all or the feature's depth.
pub fn extrude_feature(f: &Feature, fid: i64, sketch_id: i64, direction: &str, operation: &str, lps: &[Vec<String>], to: Option<&Value>) -> Value {
    let direction = if f.mid_plane { "symmetric" } else { direction };
    let prof = if lps.is_empty() { json!({"type": "all"}) } else { json!({"type": "curves", "loops": lps}) };
    let extent = if let Some(to) = to {
        json!({"convention": "total_distance", "direction": direction, "distance": "0", "to": to})
    } else if f.through_all {
        json!({"convention": "total_distance", "direction": direction, "distance": "0", "through_all": true})
    } else {
        json!({"convention": "total_distance", "direction": direction, "distance": repr(round(f.depth_mm.unwrap_or(0.0), 9))})
    };
    let mut g = json!({"id": fid, "name": f.name, "type": "extrude", "sketch": sketch_id, "suppressed": false,
                       "operation": operation, "profiles": prof, "extent": extent});
    if operation == "new_body" {
        g["body_names"] = json!([f.name]);
    }
    g
}

fn pending(name: &str, feats: &[Feature], out: Vec<Value>, nid: i64, f: &str) -> Value {
    let mut d = design_tail(name, feats, out, nid);
    d["pending"] = json!(f);
    d
}

fn by_name(out: &[Value]) -> HashMap<String, Value> {
    out.iter().map(|x| (x["name"].as_str().unwrap_or("").to_string(), x["id"].clone())).collect()
}

/// A single-body SolidCraft design from fully decoded features. `choices` gives each extrude's
/// [direction, operation] by name (default positive, new body first then join / cut); `upto`
/// stops after that feature. A feature whose choice the rebuild check makes in the design so far
/// (a fillet's edges, a mirror's plane …) and that isn't in `picks` ends the design there, with
/// `"pending": <its name>`.
/// A sketch on a flat face of the body, its outline projected from the face: an extrude of model
/// edges a SolidWorks sketch selects (see the Python). `p` a point on the face, `n` its normal, mm.
fn face_sketch(name: &str, fid: i64, p: [f64; 3], n: [f64; 3], body: &str) -> Value {
    let a = if n[2].abs() < 0.9 { [0.0, 0.0, 1.0] } else { [1.0, 0.0, 0.0] };
    let x = [a[1] * n[2] - a[2] * n[1], a[2] * n[0] - a[0] * n[2], a[0] * n[1] - a[1] * n[0]];
    let ln = (x[0] * x[0] + x[1] * x[1] + x[2] * x[2]).sqrt();
    let x = [x[0] / ln, x[1] / ln, x[2] / ln];
    let y = [n[1] * x[2] - n[2] * x[1], n[2] * x[0] - n[0] * x[2], n[0] * x[1] - n[1] * x[0]];
    json!({"id": fid, "name": name, "type": "sketch", "suppressed": false,
           "plane": {"type": "custom", "plane": {"origin": p, "x_dir": x, "y_dir": y}},
           "sketch": {"points": [{"id": "origin", "pos": [0.0, 0.0], "fixed": true}], "curves": [], "constraints": [],
                      "links": [{"id": "j1", "kind": "project", "source": {"type": "face", "body": body, "at": p}}],
                      "counters": {"j": 1, "l": 0, "p": 0}}})
}

/// mm: half the side of the square a flipped cut takes from (past any part).
pub const FLIP_SQUARE: f64 = 10000.0;

pub fn design(name: &str, feats: &mut [Feature], choices: &Choices, planes: &HashMap<String, usize>, constraints: bool, picks: &Picks, upto: Option<&str>) -> Value {
    let mut out: Vec<Value> = Vec::new();
    let mut ids: HashMap<String, i64> = HashMap::new();
    let mut sk_of: HashMap<String, Sketch> = HashMap::new();
    let mut nid: i64 = 1;
    let mut first = true;
    let mut selected: HashMap<String, Vec<Vec<String>>> = HashMap::new();
    for f in feats.iter() {
        if let (Some(profile), Some(loops)) = (f.profile.as_ref(), f.selected_loops.as_ref()) {
            if !profile.is_empty() {
                selected.insert(profile.clone(), loops.clone());
            }
        }
    }
    let pick = |k: &str| picks.get(k).filter(|v| !v.is_null());
    // the face each extrude of model edges is of (chosen in the rebuild), by its sketch
    let three = |v: &Value| -> Option<[f64; 3]> {
        let a = v.as_array()?;
        Some([a.first()?.as_f64()?, a.get(1)?.as_f64()?, a.get(2)?.as_f64()?])
    };
    let mut face_of: HashMap<String, ([f64; 3], [f64; 3])> = HashMap::new();
    for f in feats.iter() {
        if f.from_face && (f.kind == "boss" || f.kind == "cut") {
            if let (Some(prof), Some(v)) = (f.profile.as_ref(), pick(&format!("face:{}", f.name))) {
                if let (Some(p), Some(n)) = (v.get(0).and_then(three), v.get(1).and_then(three)) {
                    face_of.insert(prof.clone(), (p, n));
                }
            }
        }
    }
    for fi in 0..feats.len() {
        let f = &feats[fi];
        let kind = f.kind.clone();
        match kind.as_str() {
            "sketch" => {
                let choice = planes.get(&f.name).copied().unwrap_or(0);
                let flips: Vec<usize> = choices.get(&format!("arcs:{}", f.name)).and_then(Value::as_array).map_or(vec![], |a| a.iter().filter_map(|x| x.as_u64().map(|v| v as usize)).collect());
                let fm = &mut feats[fi];
                let skm = fm.sketch.as_mut().unwrap();
                skm.choice = choice;
                let mut sk = with_centres(skm, &flips);
                if let Some(loops) = selected.get(&fm.name) {
                    sk = select_sketch_loops(&sk, loops);
                }
                let body = out.iter().find_map(|g| g.get("body_names").and_then(|b| b.get(0)).and_then(Value::as_str).map(String::from));
                match (face_of.get(&fm.name), body) {
                    (Some((p, n)), Some(body)) => {
                        let g = face_sketch(&fm.name, nid, *p, *n, &body);
                        sketch_feature(&mut sk, nid, constraints); // (its params as for any sketch)
                        out.push(g);
                    }
                    _ => out.push(sketch_feature(&mut sk, nid, constraints)),
                }
                // (a copy with an arc turned holds them)
                skm.params = sk.params.clone();
                skm.dims_skipped = sk.dims_skipped.clone();
                skm.offsets = sk.offsets.clone();
                skm.relations_skipped = sk.relations_skipped;
                ids.insert(fm.name.clone(), nid);
                sk_of.insert(fm.name.clone(), sk);
            }
            "boss" | "cut" => {
                let (d, op) = match choices.get(&f.name).and_then(Value::as_array) {
                    Some(a) => (a[0].as_str().unwrap_or("positive").to_string(), a.get(1).and_then(Value::as_str).map(String::from)),
                    None => ("positive".to_string(), None),
                };
                let op = op.unwrap_or_else(|| if first { "new_body".into() } else if f.kind == "cut" { "cut".into() } else { "join".into() });
                let prof = f.profile.clone().unwrap_or_default();
                let sk = &sk_of[&prof];
                // loops the search leaves out (a stray curve reaching past the part)
                let skip: Vec<String> = pick(&format!("drop:{}", f.name))
                    .and_then(Value::as_array)
                    .map(|a| a.iter().filter_map(|x| x.as_str().map(String::from)).collect())
                    .unwrap_or_default();
                let mut g = extrude_feature(f, nid, ids[&prof], &d, &op, &profile_loops_skip(sk, &skip), pick(&format!("to:{}", f.name)));
                if f.kind == "cut" && pick(&format!("flipside:{}", f.name)).and_then(Value::as_bool).unwrap_or(false) {
                    // flip side to cut: the profile kept, the rest taken. A square far round the
                    // sketch's loops makes them holes in one region, cut instead (see the Python)
                    if let Some(mut sk_g) = out.iter().find(|x| x["id"] == json!(ids[&prof])).cloned() {
                        sk_g["id"] = json!(nid);
                        sk_g["name"] = json!(format!("{} outside", f.name));
                        let sq = FLIP_SQUARE;
                        let k0 = sk_g["sketch"]["points"].as_array().map_or(0, |a| a.len());
                        let nl = sk_g["sketch"]["counters"]["l"].as_i64().unwrap_or(0);
                        for (n, (a, b)) in [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)].into_iter().enumerate() {
                            sk_g["sketch"]["points"].as_array_mut().unwrap().push(json!({"fixed": true, "id": format!("q{n}"), "pos": [a * sq, b * sq]}));
                        }
                        for n in 0..4 {
                            sk_g["sketch"]["curves"].as_array_mut().unwrap().push(json!({"a": k0 + n, "b": k0 + (n + 1) % 4, "construction": false,
                                                                                         "id": format!("l{}", nl + n as i64 + 1), "type": "line"}));
                        }
                        sk_g["sketch"]["counters"]["l"] = json!(nl + 4);
                        out.push(sk_g);
                        nid += 1;
                        g["id"] = json!(nid);
                        g["sketch"] = json!(nid - 1);
                        g["profiles"] = json!({"type": "curves", "loops": [(0..4).map(|n| format!("l{}", nl + n + 1)).collect::<Vec<_>>()]});
                    }
                }
                if let Some(span) = pick(&format!("span:{}", f.name)).and_then(Value::as_f64) {
                    g["extent"] = json!({"convention": "total_distance", "direction": d, "distance": repr(round(span, 9))});
                }
                if let Some(start) = pick(&format!("start:{}", f.name)).and_then(Value::as_f64) {
                    // starting at a face of the body so far (verify)
                    g["extent"]["start_offset"] = json!(repr(round(start, 9)));
                }
                if let Some(th) = f.thin_mm.filter(|v| *v != 0.0) {
                    let mut cur: Vec<String> = (0..sk.lines.len()).filter(|n| !sk.construction.contains(n)).map(|n| format!("l{}", n + 1)).collect();
                    cur.extend((0..sk.arcs.len()).map(|n| format!("a{}", n + 1)));
                    cur.extend((0..sk.circles.len()).map(|n| format!("c{}", n + 1)));
                    let side = pick(&format!("thin:{}", f.name)).and_then(Value::as_str).unwrap_or("center").to_string();
                    g["thin"] = json!({"curves": cur, "thickness": repr(th), "side": side});
                    g["profiles"] = json!({"type": "all"});
                }
                out.push(g);
                first = false;
            }
            "revolve" | "revcut" => {
                let prof = f.profile.clone().unwrap_or_default();
                let sk = &sk_of[&prof];
                let axes = revolve_axis_options(sk);
                let (ai, sign) = match choices.get(&f.name).and_then(Value::as_array) {
                    Some(a) => (a[0].as_i64().unwrap_or(0), a[1].as_f64().unwrap_or(1.0)),
                    None => (0, 1.0),
                };
                let op = if first { "new_body" } else if f.kind == "revcut" { "cut" } else { "join" };
                let mut g = json!({"id": nid, "name": f.name, "type": "revolve", "sketch": ids[&prof], "suppressed": false,
                                   "operation": op, "profiles": {"type": "curves", "loops": profile_loops(sk)},
                                   "axis": axes[ai.rem_euclid(axes.len() as i64) as usize],
                                   "angle": repr(round(sign * f.angle_deg, 9)), "convention": "sketch_normal"});
                if op == "new_body" {
                    g["body_names"] = json!([f.name]);
                }
                out.push(g);
                first = false;
            }
            "fillet" | "chamfer" => {
                let Some(picked) = pick(&f.name).and_then(Value::as_array) else {
                    return pending(name, feats, out, nid, &feats[fi].name.clone());
                };
                // an edge two SolidWorks faces share: once (the last of each name, in first order)
                let mut once: IndexMap<String, Value> = IndexMap::new();
                for e in picked {
                    once.insert(e[1].as_str().unwrap_or("").to_string(), e[0].clone());
                }
                let mut g = json!({"id": nid, "name": f.name, "type": f.kind, "suppressed": false,
                                   "edges": once.values().cloned().collect::<Vec<_>>(), "edge_names": once.keys().cloned().collect::<Vec<_>>()});
                if f.kind == "fillet" {
                    g["tangent_chain"] = json!(false);
                    g["radius"] = json!(param_name(&f.name, "D1"));
                } else {
                    g["distance"] = json!(param_name(&f.name, "D1"));
                    if f.chamfer_mm2.is_some() {
                        g["distance2"] = json!(param_name(&f.name, "D2"));
                    } else if let Some(a) = f.chamfer_deg.filter(|a| (a - 45.0).abs() > 1e-9) {
                        g["angle"] = json!(format!("{} deg", repr(round(a, 9))));
                    }
                    if pick(&format!("flip:{}", f.name)).and_then(Value::as_bool).unwrap_or(false) {
                        g["flip"] = json!(true);
                    }
                }
                out.push(g);
            }
            "draft" | "moveface" => {
                // its faces (a draft's neutral plane and pull) are found in the design so far (search)
                let Some(got) = pick(&format!("{}:{}", f.kind, f.name)) else {
                    return pending(name, feats, out, nid, &feats[fi].name.clone());
                };
                let num = |v: &Value| v.as_f64().unwrap_or(0.0);
                if f.kind == "draft" {
                    let pull: Vec<f64> = got[2].as_array().map(|a| a.iter().map(num).collect()).unwrap_or_default();
                    let a = if pull[0].abs() < 0.9 { [1.0, 0.0, 0.0] } else { [0.0, 1.0, 0.0] };
                    let dot: f64 = (0..3).map(|k| a[k] * pull[k]).sum();
                    let x0 = [0, 1, 2].map(|k| a[k] - dot * pull[k]);
                    let ln = x0.iter().map(|c| c * c).sum::<f64>().sqrt();
                    let x = x0.map(|c| c / ln);
                    let y = [pull[1] * x[2] - pull[2] * x[1], pull[2] * x[0] - pull[0] * x[2], pull[0] * x[1] - pull[1] * x[0]];
                    out.push(json!({"id": nid, "name": f.name, "type": "draft", "suppressed": false,
                                    "faces": got[0], "angle": param_name(&f.name, "D1"),
                                    "neutral": {"type": "custom", "plane": {"origin": got[1], "x_dir": x, "y_dir": y}},
                                    "pull": got[2]}));
                } else {
                    let p = param_name(&f.name, "D1");
                    out.push(json!({"id": nid, "name": f.name, "type": "offset_face", "suppressed": false,
                                    "faces": got[0], "distance": if num(&got[1]) > 0.0 { p } else { format!("-{p}") }}));
                }
            }
            "shell" => {
                let Some(got) = pick(&format!("shell:{}", f.name)) else {
                    return pending(name, feats, out, nid, &feats[fi].name.clone());
                };
                out.push(json!({"id": nid, "name": f.name, "type": "shell", "suppressed": false,
                                "faces": got, "thickness": repr(f.thin_mm.unwrap_or(0.0))}));
            }
            "sweep" | "sweepcut" => {
                let swap = pick(&format!("swap:{}", f.name)).and_then(Value::as_bool).unwrap_or(false);
                let (prof, path) = if swap { (f.path.clone(), f.profile.clone()) } else { (f.profile.clone(), f.path.clone()) };
                let (prof, path) = (prof.unwrap_or_default(), path.unwrap_or_default());
                let psk = &sk_of[&path];
                let mut path_curves: Vec<String> = (0..psk.lines.len()).filter(|n| !psk.construction.contains(n)).map(|n| format!("l{}", n + 1)).collect();
                path_curves.extend((0..psk.arcs.len()).map(|n| format!("a{}", n + 1)));
                let op = if first { "new_body" } else if f.kind == "sweepcut" { "cut" } else { "join" };
                let lps = profile_loops(&sk_of[&prof]);
                let profiles = if lps.is_empty() { json!({"type": "all"}) } else { json!({"type": "curves", "loops": lps}) };
                let mut g = json!({"id": nid, "name": f.name, "type": "sweep", "suppressed": false, "sketch": ids[&prof],
                                   "profiles": profiles, "path_sketch": ids[&path], "path": path_curves, "operation": op});
                if op == "new_body" {
                    g["body_names"] = json!([f.name]);
                }
                out.push(g);
                first = false;
            }
            "move" => {
                // the part's body moved as SolidWorks moved it (rotation, then translation)
                let body = out.iter().find_map(|x| x.get("body_names").and_then(|b| b.get(0)).cloned());
                let rotation = f.rotation.unwrap_or([1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]);
                let t = f.translate.unwrap_or([0.0; 3]);
                if (0..9).any(|k| (rotation[k] - if k % 4 == 0 { 1.0 } else { 0.0 }).abs() > 1e-9) {
                    out.push(json!({"id": nid, "name": f.name, "type": "move", "suppressed": false,
                        "bodies": body.map_or(vec![], |b| vec![b]),
                        "matrix": [rotation[0..3].iter().copied().chain([t[0]]).collect::<Vec<_>>(),
                                   rotation[3..6].iter().copied().chain([t[1]]).collect::<Vec<_>>(),
                                   rotation[6..9].iter().copied().chain([t[2]]).collect::<Vec<_>>(), [0.0, 0.0, 0.0, 1.0]]}));
                } else {
                    out.push(json!({"id": nid, "name": f.name, "type": "move", "suppressed": false,
                        "bodies": body.map_or(vec![], |b| vec![b]), "translate": t.map(|x| repr(round(x, 9)))}));
                }
            }
            "scale" => {
                let Some(got) = pick(&format!("scale:{}", f.name)).cloned() else {
                    return pending(name, feats, out, nid, &feats[fi].name.clone());
                };
                let body = out.iter().find_map(|x| x.get("body_names").and_then(|b| b.get(0)).cloned());
                let [sx, sy, sz] = f.scale.unwrap_or([1.0; 3]);
                let mut g = json!({"id": nid, "name": f.name, "type": "scale", "suppressed": false,
                                   "bodies": body.map_or(vec![], |b| vec![b]), "origin": got});
                if (sx - sy).abs() < 1e-12 && (sx - sz).abs() < 1e-12 {
                    g["factor"] = json!(repr(sx));
                } else {
                    g["factors"] = json!([repr(sx), repr(sy), repr(sz)]);
                }
                out.push(g);
            }
            "dome" => {
                let Some(got) = pick(&format!("dome:{}", f.name)).and_then(Value::as_array).cloned() else {
                    return pending(name, feats, out, nid, &feats[fi].name.clone());
                };
                // SolidCraft has no dome feature; it makes domes as a revolve of an arc: a quarter
                // profile on a plane through the face's axis, turned about it
                let v3 = |v: &Value| -> [f64; 3] { [0, 1, 2].map(|i| v[i].as_f64().unwrap_or(0.0)) };
                let (c, n, r) = (v3(&got[0]), v3(&got[1]), got[2].as_f64().unwrap_or(0.0));
                let h = f.dome_mm.unwrap_or(0.0);
                let u0 = if n[0].abs() < 0.9 { [1.0, 0.0, 0.0] } else { [0.0, 1.0, 0.0] };
                let dt = u0[0] * n[0] + u0[1] * n[1] + u0[2] * n[2];
                let u = [u0[0] - dt * n[0], u0[1] - dt * n[1], u0[2] - dt * n[2]];
                let ln = (u[0] * u[0] + u[1] * u[1] + u[2] * u[2]).sqrt();
                let u = [u[0] / ln, u[1] / ln, u[2] / ln];
                let big = (r * r + h * h) / (2.0 * h);
                out.push(json!({"id": nid, "name": format!("{} profile", f.name), "type": "sketch", "suppressed": false,
                    "plane": {"type": "custom", "plane": {"origin": c, "x_dir": u, "y_dir": n}},
                    "sketch": {"constraints": [], "curves": [
                        {"a": 0, "b": 1, "construction": false, "id": "l1", "type": "line"},
                        {"a": 1, "b": 2, "c": 3, "construction": false, "id": "a1", "type": "arc"},
                        {"a": 2, "b": 0, "construction": false, "id": "l2", "type": "line"}],
                      "points": [{"fixed": true, "id": "origin", "pos": [0.0, 0.0]}, {"fixed": false, "id": "rim", "pos": [r, 0.0]},
                                 {"fixed": false, "id": "apex", "pos": [0.0, h]}, {"fixed": false, "id": "ctr", "pos": [0.0, h - big]}],
                      "counters": {"a": 1, "c": 0, "k": 0, "l": 2}}}));
                nid += 1;
                out.push(json!({"id": nid, "name": f.name, "type": "revolve", "sketch": nid - 1, "suppressed": false,
                    "operation": "join", "profiles": {"type": "curves", "loops": [["l1", "a1", "l2"]]},
                    "axis": {"type": "sketch_line", "curve": "l2"}, "angle": "360", "convention": "sketch_normal"}));
            }
            "rib" => {
                // its free-edge chain on its mid plane, then SolidCraft's rib (ported from
                // cadkit-kernel crates/ck-swedit/src/rib.rs, MIT OR Apache-2.0); side and ends
                // chosen in the rebuild
                let got = pick(&format!("rib:{}", f.name)).and_then(Value::as_array).cloned();
                let flip = got.as_ref().and_then(|g| g.first()).and_then(Value::as_bool).unwrap_or(false);
                let extend = got.as_ref().and_then(|g| g.get(1)).and_then(Value::as_bool).unwrap_or(true);
                let (o, x, y, ch) = f.rib.clone().unwrap_or_default();
                let pts: Vec<Value> = ch.iter().enumerate().map(|(k, p)| json!({"fixed": false, "id": format!("p{k}"), "pos": [round(p[0], 9), round(p[1], 9)]})).collect();
                let curves: Vec<Value> = (0..ch.len().saturating_sub(1)).map(|k| json!({"a": k, "b": k + 1, "construction": false, "id": format!("l{}", k + 1), "type": "line"})).collect();
                let ids: Vec<String> = (0..curves.len()).map(|k| format!("l{}", k + 1)).collect();
                out.push(json!({"id": nid, "name": format!("{} profile", f.name), "type": "sketch", "suppressed": false,
                    "plane": {"type": "custom", "plane": {"origin": o, "x_dir": x, "y_dir": y}},
                    "sketch": {"constraints": [], "curves": curves, "points": pts,
                      "counters": {"a": 0, "c": 0, "k": 0, "l": ids.len()}}}));
                nid += 1;
                let mut g = json!({"id": nid, "name": f.name, "type": "rib", "sketch": nid - 1, "suppressed": false,
                    "curves": ids, "thickness": repr(round(f.thin_mm.unwrap_or(0.0), 9))});
                if flip {
                    g["flip"] = json!(true);
                }
                if extend {
                    g["extend"] = json!(true);
                }
                out.push(g);
            }
            "pattern" => {
                let Some(got) = pick(&format!("pattern:{}", f.name)).and_then(Value::as_array).cloned() else {
                    return pending(name, feats, out, nid, &feats[fi].name.clone());
                };
                let bn = by_name(&out);
                let feats_ids: Vec<Value> = got[1].as_array().map_or(vec![], |w| w.iter().filter_map(|n| bn.get(n.as_str().unwrap_or("")).cloned()).collect());
                out.push(json!({"id": nid, "name": f.name, "type": "pattern", "suppressed": false, "features": feats_ids, "pattern": got[0]}));
            }
            "thread" => {
                let Some(got) = pick(&format!("thread:{}", f.name)).and_then(Value::as_array).cloned() else {
                    return pending(name, feats, out, nid, &feats[fi].name.clone());
                };
                let t = &f.thread;
                let num = |k: &str| t.get(k).and_then(Value::as_f64).unwrap_or(0.0);
                let mut g = json!({"id": nid, "name": f.name, "type": "thread", "suppressed": false, "face": got[0], "from": got[1],
                                   "designation": format!("M{}x{}", g(num("diameter")), g(num("pitch")))});
                if let Some(l) = t.get("length").and_then(Value::as_f64) {
                    g["length"] = json!(repr(l));
                }
                g["modeled"] = json!(true);
                g["continuous_flanks"] = json!(true);
                out.push(g);
            }
            "mirror" => {
                let Some(got) = pick(&format!("mirror:{}", f.name)).and_then(Value::as_array).cloned() else {
                    return pending(name, feats, out, nid, &feats[fi].name.clone());
                };
                let (plane, what) = (&got[0], &got[1]);
                let mut g = json!({"id": nid, "name": f.name, "type": "mirror", "suppressed": false, "plane": {"type": "custom", "plane": plane}});
                if what.as_str() == Some("body") {
                    let body = out.iter().find_map(|x| x.get("body_names").and_then(|b| b.get(0)).cloned());
                    g["features"] = json!([]);
                    g["bodies"] = json!(body.map_or(vec![], |b| vec![b]));
                    g["combine"] = json!(true);
                } else {
                    let bn = by_name(&out);
                    g["features"] = json!(what.as_array().map_or(vec![], |w| w.iter().filter_map(|n| bn.get(n.as_str().unwrap_or("")).cloned()).collect::<Vec<_>>()));
                }
                out.push(g);
            }
            "split" => {
                let Some(got) = pick(&format!("split:{}", f.name)).and_then(Value::as_array).cloned() else {
                    return pending(name, feats, out, nid, &feats[fi].name.clone());
                };
                let (tool, keep) = (&got[0], got[1].as_i64());
                let body = out.iter().find_map(|x| x.get("body_names").and_then(|b| b.get(0)).and_then(Value::as_str).map(str::to_string)).unwrap_or_default();
                let mut g = json!({"id": nid, "name": f.name, "type": "split", "suppressed": false, "body": body,
                                   "plane": {"type": "origin", "name": "XY"}});
                if let Some(line) = tool.get("line") {
                    g["sketch"] = json!(ids[f.profile.as_deref().unwrap_or("")]);
                    g["line"] = line.clone();
                } else {
                    g["plane"] = json!({"type": "custom", "plane": tool["plane"]});
                }
                out.push(g);
                if let Some(k) = keep {
                    // the other piece removed (SolidCraft names it "<body> (1)")
                    nid += 1;
                    let gone = if k == 0 { format!("{body} (1)") } else { body.clone() };
                    out.push(json!({"id": nid, "name": format!("{} (removed)", f.name), "type": "remove", "suppressed": false, "bodies": [gone]}));
                }
            }
            "hole" => {
                let prof = f.profile.clone().unwrap_or_default();
                let sk = &sk_of[&prof];
                let (through, flip) = match pick(&format!("hole:{}", f.name)).and_then(Value::as_array) {
                    Some(a) => (a[0].as_bool().unwrap_or(false), a[1].as_bool().unwrap_or(false)),
                    None => (false, false),
                };
                let ([px, py, nrm], t) = sk.plane().unwrap();
                let mut pids: Vec<u32> = sk.points.keys().copied().collect();
                pids.sort();
                pids.retain(|q| !(*q == 1 && sk.points[q].0.abs().max(sk.points[q].1.abs()) < 1e-12));
                // the hole points are the sketch's own points, not the ends or centres of curves
                let on_curve: HashSet<u32> = sk.lines.iter().flat_map(|l| [l.0, l.1]).chain(sk.arcs.iter().flat_map(|a| [a.0, a.1, a.2])).chain(sk.circles.iter().map(|c| c.0)).collect();
                let own: Vec<u32> = pids.iter().copied().filter(|q| !on_curve.contains(q)).collect();
                if !own.is_empty() {
                    pids = own;
                }
                if let Some(chosen) = pick(&format!("holepts:{}", f.name)).and_then(Value::as_array) {
                    let ch: Vec<u32> = chosen.iter().filter_map(|x| x.as_u64().map(|v| v as u32)).collect();
                    let sel: Vec<u32> = pids.iter().copied().filter(|q| ch.contains(q)).collect();
                    if !sel.is_empty() {
                        pids = sel;
                    }
                }
                // its only point the sketch's origin (a hole on a part's axis): SolidCraft's fixed origin point
                let origin_only = pids.is_empty() && sk.points.contains_key(&1);
                let position: Value = if let Some(q) = pids.first() {
                    let (u, v) = sk.points[q];
                    json!((0..3).map(|k| t[k] * 1000.0 + u * 1000.0 * px[k] + v * 1000.0 * py[k]).collect::<Vec<f64>>())
                } else if origin_only {
                    json!((0..3).map(|k| t[k] * 1000.0).collect::<Vec<f64>>())
                } else {
                    json!([0, 0, 0])
                };
                let mut hole_ids: Vec<String> = pids.iter().map(|q| format!("p{q}")).collect();
                if origin_only {
                    hole_ids.push("origin".into());
                }
                let mut points = json!({"sketch": ids[&prof], "ids": hole_ids});
                if flip {
                    points["flip"] = json!(true);
                }
                let mut g = json!({"id": nid, "name": f.name, "type": "hole", "suppressed": false,
                                   "diameter": param_name(&f.name, "diameter"), "direction": [-nrm[0], -nrm[1], -nrm[2]],
                                   "position": position, "points": points});
                let h = &f.hole;
                if h.contains_key("depth") && !through {
                    g["depth"] = json!(param_name(&f.name, "depth"));
                }
                let deg = |v: Option<&Value>, dflt: &str| v.map_or(dflt.to_string(), crate::pyfmt::str_num);
                if h.contains_key("cs_diameter") {
                    g["hole"] = json!({"type": "countersink", "cs_diameter": param_name(&f.name, "cs_diameter"),
                                       "cs_angle": format!("{} deg", deg(h.get("cs_angle"), "90"))});
                } else if h.contains_key("cb_diameter") {
                    g["hole"] = json!({"type": "counterbore", "cb_diameter": param_name(&f.name, "cb_diameter"),
                                       "cb_depth": param_name(&f.name, "cb_depth")});
                } else if h.contains_key("tip_angle") && g.get("depth").is_some() {
                    g["hole"] = json!({"type": "drilled", "tip_angle": format!("{} deg", deg(h.get("tip_angle"), ""))});
                }
                out.push(g);
            }
            "import" => {
                // the body as it was imported, the features after it built on it
                let fm = &mut feats[fi];
                if fm.import_step.is_none() {
                    if let Some(body) = &fm.import_body {
                        fm.import_step = Some(crate::step::body_step(body, &fm.name).unwrap_or_default());
                    }
                }
                out.push(json!({"id": nid, "name": fm.name, "type": "import", "suppressed": false,
                                "file": format!("{}.step", fm.name), "step": fm.import_step.clone().unwrap_or_default()}));
                first = false;
            }
            "plane" => {
                let ([x, y, _n], t) = f.frame.unwrap();
                let base = json!({"type": "custom", "plane": {"origin": [t[0] * 1000.0, t[1] * 1000.0, t[2] * 1000.0], "x_dir": x, "y_dir": y}});
                out.push(json!({"id": nid, "name": f.name, "type": "construction_plane", "suppressed": false,
                                "plane": {"type": "offset", "base": base, "distance": "0"}}));
            }
            _ => {}
        }
        nid += 1;
        if Some(feats[fi].name.as_str()) == upto {
            break;
        }
    }
    design_tail(name, feats, out, nid)
}

/// The design from its features: the model parameters the sketches' dimensions, the extrudes'
/// depths and the fillets' radii drive.
pub fn design_tail(name: &str, feats: &[Feature], mut out: Vec<Value>, nid: i64) -> Value {
    let written: HashSet<String> = out.iter().map(|g| g["name"].as_str().unwrap_or("").to_string()).collect();
    let mut params: Vec<Value> = Vec::new();
    for f in feats.iter().filter(|f| f.kind == "sketch" && written.contains(&f.name)) {
        params.extend(f.sketch.as_ref().unwrap().params.iter().cloned());
    }
    for f in feats.iter().filter(|f| (f.kind == "fillet" || f.kind == "chamfer") && written.contains(&f.name)) {
        params.push(json!({"name": param_name(&f.name, "D1"), "expr": repr(round(f.radius_mm.unwrap_or(0.0), 9)), "model": true, "unit": "mm"}));
    }
    for f in feats.iter().filter(|f| f.kind == "draft" && written.contains(&f.name)) {
        params.push(json!({"name": param_name(&f.name, "D1"), "expr": format!("{} deg", repr(round(f.draft_deg.unwrap_or(0.0), 9))), "model": true, "unit": "deg"}));
    }
    for f in feats.iter().filter(|f| f.kind == "moveface" && written.contains(&f.name)) {
        params.push(json!({"name": param_name(&f.name, "D1"), "expr": repr(round(f.move_mm.unwrap_or(0.0), 9)), "model": true, "unit": "mm"}));
    }
    for f in feats.iter().filter(|f| f.kind == "chamfer" && written.contains(&f.name)) {
        if let Some(d2) = f.chamfer_mm2 {
            params.push(json!({"name": param_name(&f.name, "D2"), "expr": repr(round(d2, 9)), "model": true, "unit": "mm"}));
        }
    }
    for f in feats.iter().filter(|f| f.kind == "hole" && written.contains(&f.name)) {
        for (k, v) in &f.hole {
            if ["diameter", "depth", "cs_diameter", "cb_diameter", "cb_depth"].contains(&k.as_str()) {
                params.push(json!({"name": param_name(&f.name, k), "expr": crate::pyfmt::str_num(v), "model": true, "unit": "mm"}));
            }
        }
    }
    for g in out.iter_mut() {
        // each extrude's depth as a model parameter, named after SolidWorks' D1@<feature>
        if g.get("type").and_then(Value::as_str) != Some("extrude") {
            continue;
        }
        let through = g["extent"].get("through_all").and_then(Value::as_bool).unwrap_or(false);
        if g.get("extent").is_some_and(|e| e.is_object()) && !through {
            let pname = param_name(g["name"].as_str().unwrap_or(""), "D1");
            params.push(json!({"name": pname, "expr": g["extent"]["distance"].clone(), "model": true, "unit": "mm"}));
            g["extent"]["distance"] = json!(pname);
        }
    }
    json!({"format": "solidcraft/55", "name": name, "units": "mm", "params": params, "features": out, "next_id": nid})
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fillet_blends_only_the_file_selected_edges() {
        let mut f = Feature::new("fillet", "Fillet1", 0, crate::features::FILLET);
        f.radius_mm = Some(0.15);
        let mut feats = vec![f];
        let picks = Picks::new().with("Fillet1", json!([[[0, 0, 0], "edge"]]));
        let d = design("Part", &mut feats, &Choices::new(), &HashMap::new(), true, &picks, None);
        assert_eq!(d["features"].as_array().unwrap().last().unwrap()["tangent_chain"], json!(false));
    }

    #[test]
    fn mid_plane_extrude_is_symmetric_even_with_a_one_sided_choice() {
        let mut f = Feature::new("boss", "Boss-Extrude1", 0, crate::features::BOSS);
        f.depth_mm = Some(55.0);
        f.mid_plane = true;
        let g = extrude_feature(&f, 2, 1, "positive", "new_body", &[], None);
        assert_eq!(g["extent"]["direction"], "symmetric");
        assert_eq!(g["extent"]["distance"], "55.0");
    }

    #[test]
    fn design_writes_only_the_features_selected_contours() {
        let mut sk = Sketch::new("Sketch1", 0);
        sk.points.extend([
            (1, (0.0, 0.0)),
            (2, (0.01, 0.0)),
            (3, (0.01, 0.01)),
            (4, (0.0, 0.01)),
            (5, (0.005, 0.005)),
        ]);
        sk.lines = vec![(1, 2), (2, 3), (3, 4), (4, 1)];
        sk.circles = vec![(5, 0.002)];
        sk.add_plane(&(crate::features::FRONT, [0.0; 3]), "test", false);
        let mut sketch = Feature::new("sketch", "Sketch1", 0, crate::features::SKETCH);
        sketch.sketch = Some(sk);
        let mut boss = Feature::new("boss", "Boss1", 1, crate::features::BOSS);
        boss.profile = Some("Sketch1".into());
        boss.depth_mm = Some(5.0);
        boss.selected_loops = Some(vec![vec!["l1".into(), "l2".into(), "l3".into(), "l4".into()]]);
        let mut feats = vec![sketch, boss];
        let d = design("Part", &mut feats, &Choices::new(), &HashMap::new(), true, &Picks::new(), None);
        let written = &d["features"][0]["sketch"];
        assert_eq!(written["counters"]["l"], 4);
        assert_eq!(written["counters"]["c"], 0);
        assert_eq!(written["curves"].as_array().unwrap().len(), 4);
        assert_eq!(d["features"][1]["profiles"]["loops"], json!([["l1", "l2", "l3", "l4"]]));
    }

    #[test]
    fn dimensions_use_only_references_that_match_the_saved_geometry() {
        let mut sk = Sketch::new("S", 0);
        sk.points.extend([(4, (-0.019, 0.0)), (5, (0.019, 0.0)), (6, (0.0, 0.0))]);
        sk.circles = vec![(4, 0.002), (5, 0.002)];
        sk.add_plane(&(crate::features::FRONT, [0.0; 3]), "test", false);
        sk.dims = vec![crate::features::Dim { name: "D3".into(), cls: "sgPntPntDist".into(), value: 0.038,
            handles: vec![Handle { cls: "sgPointHandle".into(), id: 5 }, Handle { cls: "sgPointHandle".into(), id: 4 }] }];
        let _d = sketch_feature(&mut sk, 1, true);
        assert_eq!(sk.params[0]["name"], "S_D3");
        sk.dims[0].value = 0.039;
        let _d = sketch_feature(&mut sk, 1, true);
        assert!(sk.params.is_empty());
        assert_eq!(sk.dims_skipped, ["D3 (sgPntPntDist)"]);

        let mut sk = Sketch::new("S", 0);
        sk.points.extend([(2, (-0.005, 0.070)), (3, (0.005, 0.070))]);
        sk.lines = vec![(2, 3)];
        sk.curve_of.insert(("line".into(), 2), "l1".into());
        sk.add_plane(&(crate::features::FRONT, [0.0; 3]), "test", false);
        sk.dims = vec![crate::features::Dim { name: "D4".into(), cls: "sgPntLineDist".into(), value: 0.070,
            handles: vec![Handle { cls: "sgPointHandle".into(), id: 0 }, Handle { cls: "sgLineHandle".into(), id: 2 }] }];
        let d = sketch_feature(&mut sk, 1, true);
        assert_eq!(sk.params[0]["name"], "S_D4");
        assert_eq!(d["sketch"]["constraints"][0]["type"], "point_line_distance");

        for (cls, value) in [("sgPntPntDist", 0.010), ("sgPntPntVertDist", 10.0f64.hypot(10.0) / 1000.0)] {
            let mut diagonal = Sketch::new("S", 0);
            diagonal.points.extend([(1, (0.0, 0.0)), (2, (0.010, 0.010))]);
            diagonal.add_plane(&(crate::features::FRONT, [0.0; 3]), "test", false);
            diagonal.dims = vec![crate::features::Dim { name: "D9".into(), cls: cls.into(), value,
                handles: vec![Handle { cls: "sgPointHandle".into(), id: 0 }, Handle { cls: "sgPointHandle".into(), id: 1 }] }];
            let _d = sketch_feature(&mut diagonal, 1, true);
            assert!(diagonal.params.is_empty());
        }

        let mut preferred = Sketch::new("S", 0);
        preferred.points.extend([(1, (0.0, 0.0)), (2, (0.010, 0.0)), (3, (0.020, 0.0))]);
        preferred.add_plane(&(crate::features::FRONT, [0.0; 3]), "test", false);
        preferred.dims = vec![crate::features::Dim { name: "D1".into(), cls: "sgPntPntDist".into(), value: 0.010,
            handles: vec![Handle { cls: "sgPointHandle".into(), id: 1 }, Handle { cls: "sgPointHandle".into(), id: 2 }] }];
        let d = sketch_feature(&mut preferred, 1, true);
        assert_eq!(preferred.params[0]["name"], "S_D1");
        assert_eq!((d["sketch"]["constraints"][0]["p"].as_u64(), d["sketch"]["constraints"][0]["q"].as_u64()), (Some(1), Some(2)));

        let mut positioned = Sketch::new("S", 0);
        positioned.points.extend([(1, (0.0, 0.0)), (2, (0.099, 0.0)), (4, (0.020, 0.0)), (5, (0.030, 0.0)), (6, (0.010, 0.0))]);
        positioned.add_plane(&(crate::features::FRONT, [0.0; 3]), "test", false);
        positioned.dims = vec![crate::features::Dim { name: "D2".into(), cls: "sgPntPntDist".into(), value: 0.010,
            handles: vec![Handle { cls: "sgPointHandle".into(), id: 4 }, Handle { cls: "sgPointHandle".into(), id: 0 }] }];
        let _d = sketch_feature(&mut positioned, 1, true);
        assert_eq!(positioned.params[0]["name"], "S_D2");
    }
}
