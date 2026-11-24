//! A fillet's edges in the rebuilt SolidCraft design (port of `sw2sc/fillets.py`).
//!
//! SolidWorks names a fillet's edges by the faces meeting there: a face swept by a sketch entity
//! of a feature, or a feature's end face (0 start, 1 end). SolidCraft names an edge the same way
//! (`F5:side:l3|F5:top`, `model.edges`). Which of our sketch curves an entity number is, and which
//! end face is SolidCraft's start or top, are solved for: an assignment is kept when every edge
//! SolidWorks names is an edge of the rebuilt body.

use std::collections::{BTreeSet, HashMap, HashSet};
use std::sync::OnceLock;

use regex::Regex;
use serde_json::Value;

use crate::features::{Edge, FaceRef, Feature};
use crate::verify::Evaluator;

pub const MAX_SOLUTIONS: usize = 40;
pub const BUDGET: usize = 200_000;

/// A SolidCraft face: (side | end | blend, design feature id, curve / start|top|bottom|end / edge).
pub type ScFace = (&'static str, i64, String);
pub type ScPair = (ScFace, ScFace);
/// An edge of the body: its two faces, its mid point, its name.
pub type ScEdge = (ScPair, Value, String);
/// SolidWorks face -> SolidCraft face.
pub type Amap = HashMap<FaceRef, ScFace>;

fn face_re() -> &'static Regex {
    static R: OnceLock<Regex> = OnceLock::new();
    R.get_or_init(|| Regex::new(r"^F(\d+):(?:side:([A-Za-z]+\d+)(?:#\[[^\]]*\])?|(start|top|bottom|end)(?:#\[[^\]]*\])?|blend\((.*)\))$").unwrap())
}

/// An edge name's two faces: split at the `|` outside parentheses.
fn split(name: &str) -> Vec<String> {
    let (mut parts, mut depth, mut cur) = (Vec::new(), 0i32, String::new());
    for ch in name.chars() {
        if ch == '|' && depth == 0 {
            parts.push(std::mem::take(&mut cur));
            continue;
        }
        depth += (ch == '(') as i32 - (ch == ')') as i32;
        cur.push(ch);
    }
    parts.push(cur);
    parts
}

/// (kind, feature id, which) for each of an edge's two faces.
pub fn faces(name: &str) -> Option<ScPair> {
    let mut out = Vec::new();
    for part in split(name) {
        let m = face_re().captures(&part)?;
        let fid: i64 = m[1].parse().ok()?;
        out.push(if let Some(c) = m.get(2) {
            ("side", fid, c.as_str().to_string())
        } else if let Some(c) = m.get(3) {
            ("end", fid, c.as_str().to_string())
        } else {
            ("blend", fid, m.get(4).map_or(String::new(), |c| c.as_str().to_string()))
        });
    }
    if out.len() == 2 {
        let b = out.pop().unwrap();
        Some((out.pop().unwrap(), b))
    } else {
        None
    }
}

/// Every edge of the design's bodies: (faces, mid point, name).
pub fn body_edges(design: &Value, ev: &mut dyn Evaluator) -> Option<Vec<ScEdge>> {
    let all = ev.edges(design)?;
    let mut out = Vec::new();
    for e in all.as_array()? {
        let name = e.get("name").and_then(Value::as_str).unwrap_or("");
        if let Some(fc) = faces(name) {
            out.push((fc, e["mid"].clone(), name.to_string()));
        }
    }
    Some(out)
}

/// Every face of the design's bodies as `model.faces` gives it.
pub fn body_faces(design: &Value, ev: &mut dyn Evaluator) -> Vec<Value> {
    ev.faces(design).and_then(|v| v.as_array().cloned()).unwrap_or_default()
}

fn key_pair(a: &ScFace, b: &ScFace) -> (ScFace, ScFace) {
    if a <= b { (a.clone(), b.clone()) } else { (b.clone(), a.clone()) }
}

/// One answer: the SolidCraft edges (mid point, name) in SolidWorks' order, with every
/// assignment that reaches them.
pub type Solution = (Vec<(Value, String)>, Vec<Amap>);

/// Assignments of SolidWorks faces to SolidCraft's that make every edge in `sw_edges` an edge of
/// `sc_edges` (see the Python for the search).
#[allow(clippy::too_many_arguments)]
pub fn solve(
    sw_edges: &[Edge], sc_edges: &[ScEdge], design_id: &HashMap<u32, i64>, sketch_curves: &HashMap<i64, Vec<String>>,
    known: Option<&[Amap]>, blends: &HashMap<i64, Vec<String>>, ends: &[Edge], all_edges: &[ScEdge],
) -> Vec<Solution> {
    let all_edges = if all_edges.is_empty() { sc_edges } else { all_edges };
    let touching: HashSet<(ScFace, ScFace)> = all_edges.iter().map(|(fc, _, _)| key_pair(&fc.0, &fc.1)).collect();
    // (face ref, face ref) pairs that must touch: an edge's end faces border its faces
    let mut borders: HashMap<FaceRef, HashSet<FaceRef>> = HashMap::new();
    for ((a, b), e2) in sw_edges.iter().zip(ends.iter()) {
        for x in [e2.0, e2.1] {
            for y in [*a, *b] {
                if x != y && x.side && y.side {
                    borders.entry(x).or_default().insert(y);
                    borders.entry(y).or_default().insert(x);
                }
            }
        }
    }
    // a curve whose face comes in pieces can be several SolidWorks entities
    static PIECE: OnceLock<Regex> = OnceLock::new();
    let piece = PIECE.get_or_init(|| Regex::new(r"F(\d+):side:([A-Za-z]+\d+)(#\[[^\]]*\])").unwrap());
    let mut pieces: HashMap<(i64, String), HashSet<String>> = HashMap::new();
    for (_fc, _m, name) in all_edges {
        for m in piece.captures_iter(name) {
            pieces.entry((m[1].parse().unwrap_or(0), m[2].to_string())).or_default().insert(m[3].to_string());
        }
    }
    let split_n: HashMap<(i64, String), usize> = pieces.into_iter().map(|(k, v)| (k, v.len())).collect();
    let no_borders = HashSet::new();
    let fits = |r: &FaceRef, face: &ScFace, amap: &Amap| -> Option<Amap> {
        let d = *design_id.get(&r.fid)?;
        if face.1 != d {
            return None;
        }
        if let Some(have) = amap.get(r) {
            return if have == face { Some(Amap::new()) } else { None };
        }
        if r.side {
            let is_blend = blends.contains_key(&d);
            let want = if is_blend { "blend" } else { "side" };
            let pool: &[String] = if is_blend { &blends[&d] } else { sketch_curves.get(&d).map_or(&[][..], |v| v.as_slice()) };
            if face.0 != want || !pool.contains(&face.2) {
                return None;
            }
            let bs = borders.get(r).unwrap_or(&no_borders);
            for nb in bs {
                if let Some(other) = amap.get(nb) {
                    if other != face && !touching.contains(&key_pair(face, other)) {
                        return None; // SolidWorks says these faces meet; these SolidCraft faces don't
                    }
                }
            }
            let sharers: Vec<&FaceRef> = amap.iter().filter(|(r2, val)| *r2 != r && r2.side && r2.fid == r.fid && *val == face).map(|(r2, _)| r2).collect();
            let cap = split_n.get(&(face.1, face.2.clone())).copied().unwrap_or(1);
            if sharers.len() >= cap && !sharers.iter().all(|x| bs.contains(*x)) {
                return None; // other entities have that curve already
            }
            let mut m = Amap::new();
            m.insert(*r, face.clone());
            return Some(m);
        }
        if face.0 != "end" {
            return None;
        }
        let other = amap.get(&FaceRef { side: false, fid: r.fid, v: 1u32.wrapping_sub(r.v) });
        if other.is_some_and(|o| o.2 == face.2) {
            return None; // start and end are two faces
        }
        let mut m = Amap::new();
        m.insert(*r, face.clone());
        Some(m)
    };
    let kinds_fit = |r: &FaceRef, face: &ScFace| -> bool {
        let Some(&d) = design_id.get(&r.fid) else { return false };
        if face.1 != d {
            return false;
        }
        if !r.side {
            return face.0 == "end";
        }
        face.0 == if blends.contains_key(&d) { "blend" } else { "side" }
    };
    // each SolidWorks edge's possible SolidCraft edges, by kind and feature alone
    let pool: Vec<Vec<&ScEdge>> = sw_edges
        .iter()
        // (an edge SolidWorks gives as one face twice, a cylinder's rim: any edge of that face)
        .map(|(a, b)| {
            sc_edges
                .iter()
                .filter(|e| {
                    (kinds_fit(a, &e.0 .0) && kinds_fit(b, &e.0 .1))
                        || (kinds_fit(a, &e.0 .1) && kinds_fit(b, &e.0 .0))
                        || (a == b && (kinds_fit(a, &e.0 .0) || kinds_fit(a, &e.0 .1)))
                })
                .collect()
        })
        .collect();

    struct Ctx<'a> {
        solutions: Vec<(Vec<(Value, String)>, Amap)>,
        work: usize,
        sw_edges: &'a [Edge],
    }
    type Opt = ((Value, String), Amap);
    let matches = |ctx: &mut Ctx, i: usize, amap: &Amap, used: &BTreeSet<String>| -> Vec<Opt> {
        let (a, b) = ctx.sw_edges[i];
        let mut out: Vec<Opt> = Vec::new();
        for (fc, mid, name) in &pool[i] {
            ctx.work += 1;
            for (f1, f2) in [(&fc.0, &fc.1), (&fc.1, &fc.0)] {
                let Some(b1) = fits(&a, f1, amap) else { continue };
                let b2 = if a == b {
                    // SolidWorks gives one face for it (a cylinder's rim between its end and its
                    // side): an edge of that face, the other face left open
                    Default::default()
                } else {
                    let mut m2 = amap.clone();
                    m2.extend(b1.iter().map(|(k, v)| (*k, v.clone())));
                    let Some(b2) = fits(&b, f2, &m2) else { continue };
                    b2
                };
                if used.contains(name) {
                    // an edge already taken: only by an entity sharing its curve with a neighbour
                    let shared = [(&a, f1), (&b, f2)].iter().any(|(r, fb)| r.side && amap.iter().any(|(r2, v)| r2 != *r && v == *fb));
                    if !shared {
                        continue;
                    }
                }
                let mut binds = b1.clone();
                binds.extend(b2);
                out.push(((mid.clone(), name.clone()), binds));
            }
        }
        // faces no other entity has first: sharing a split curve is the exception
        let vals: Vec<&ScFace> = amap.values().collect();
        out.sort_by_key(|o| o.1.values().filter(|fc| vals.contains(fc)).count());
        out
    };
    fn walk(
        ctx: &mut Ctx, left: Vec<usize>, amap: Amap, used: BTreeSet<String>, picked: HashMap<usize, (Value, String)>,
        matches: &dyn Fn(&mut Ctx, usize, &Amap, &BTreeSet<String>) -> Vec<Opt>,
    ) {
        if ctx.solutions.len() >= MAX_SOLUTIONS || ctx.work > BUDGET {
            return;
        }
        if left.is_empty() {
            let n = ctx.sw_edges.len();
            ctx.solutions.push(((0..n).map(|i| picked[&i].clone()).collect(), amap));
            return;
        }
        let mut best: Option<(usize, Vec<Opt>)> = None;
        for &i in &left {
            let opts = matches(ctx, i, &amap, &used);
            if opts.is_empty() {
                return; // this branch can't name that edge
            }
            if best.as_ref().is_none_or(|b| opts.len() < b.1.len()) {
                best = Some((i, opts));
            }
        }
        let (i, opts) = best.unwrap();
        let rest: Vec<usize> = left.iter().copied().filter(|j| *j != i).collect();
        for (e, binds) in opts {
            let mut m = amap.clone();
            m.extend(binds);
            let mut u = used.clone();
            u.insert(e.1.clone());
            let mut p = picked.clone();
            p.insert(i, e);
            walk(ctx, rest.clone(), m, u, p, matches);
        }
    }
    let mut ctx = Ctx { solutions: Vec::new(), work: 0, sw_edges };
    // restarts: each way of placing the most constrained edge is searched on its own budget
    let every: Vec<usize> = (0..sw_edges.len()).collect();
    let empty = [Amap::new()];
    let starts: &[Amap] = match known {
        Some(k) if !k.is_empty() => k,
        _ => &empty,
    };
    for k in starts {
        let firsts: Vec<(usize, Vec<Opt>)> = every.iter().map(|&i| (i, matches(&mut ctx, i, k, &BTreeSet::new()))).collect();
        if firsts.iter().any(|(_, o)| o.is_empty()) {
            continue;
        }
        let (i0, opts) = firsts.into_iter().min_by_key(|x| x.1.len()).unwrap();
        for (e, binds) in opts {
            ctx.work = 0;
            let mut m = k.clone();
            m.extend(binds);
            let mut used = BTreeSet::new();
            used.insert(e.1.clone());
            let mut p = HashMap::new();
            p.insert(i0, e);
            walk(&mut ctx, every.iter().copied().filter(|j| *j != i0).collect(), m, used, p, &matches);
            if ctx.solutions.len() >= MAX_SOLUTIONS {
                break;
            }
        }
    }
    // the same edges reached by different assignments are one answer, keeping the assignments
    let mut groups: Vec<(BTreeSet<String>, Solution)> = Vec::new();
    for (s, amap) in ctx.solutions {
        let key: BTreeSet<String> = s.iter().map(|x| x.1.clone()).collect();
        let g = match groups.iter().position(|g| g.0 == key) {
            Some(i) => i,
            None => {
                groups.push((key, (s, vec![])));
                groups.len() - 1
            }
        };
        if !groups[g].1 .1.contains(&amap) {
            groups[g].1 .1.push(amap);
        }
    }
    groups.into_iter().map(|g| g.1).collect()
}

/// The edge sets the fillet could round in the design `prefix` (everything before it), each with
/// the assignments that reach it. Smooth edges (an arc running on from a line) are left out.
pub fn candidates(prefix: &Value, fillet: &Feature, feats: &[Feature], ev: &mut dyn Evaluator, known: Option<&[Amap]>) -> Vec<Solution> {
    let Some(every) = body_edges(prefix, ev) else { return vec![] };
    if every.is_empty() {
        return vec![];
    }
    let smooth = smooth_pairs(prefix);
    let sc: Vec<ScEdge> = every
        .iter()
        .filter(|e| {
            let (a, b) = &e.0;
            !(a.0 == "side" && b.0 == "side" && smooth.contains(&(a.1, key2(&a.2, &b.2))))
        })
        .cloned()
        .collect();
    let feats_json = prefix["features"].as_array().cloned().unwrap_or_default();
    let by_name: HashMap<&str, &Value> = feats_json.iter().map(|f| (f["name"].as_str().unwrap_or(""), f)).collect();
    let design_id: HashMap<u32, i64> = feats.iter().filter_map(|f| by_name.get(f.name.as_str()).map(|g| (f.fid, g["id"].as_i64().unwrap_or(0)))).collect();
    let sketches: HashMap<i64, &Value> = feats_json.iter().filter(|f| f["type"] == "sketch").map(|f| (f["id"].as_i64().unwrap_or(0), f)).collect();
    let mut curves: HashMap<i64, Vec<String>> = HashMap::new();
    for f in &feats_json {
        if let Some(sk) = f.get("sketch").and_then(Value::as_i64).and_then(|i| sketches.get(&i)) {
            let ids: Vec<String> = sk["sketch"]["curves"].as_array().map_or(vec![], |cs| {
                cs.iter().filter(|c| !c.get("construction").and_then(Value::as_bool).unwrap_or(false)).map(|c| c["id"].as_str().unwrap_or("").to_string()).collect()
            });
            curves.insert(f["id"].as_i64().unwrap_or(0), ids);
        }
    }
    let blends: HashMap<i64, Vec<String>> = feats_json
        .iter()
        .filter(|f| f["type"] == "fillet")
        .map(|f| (f["id"].as_i64().unwrap_or(0), f["edge_names"].as_array().map_or(vec![], |a| a.iter().map(|x| x.as_str().unwrap_or("").to_string()).collect())))
        .collect();
    solve(&fillet.edges, &sc, &design_id, &curves, known, &blends, &fillet.edge_ends, &every)
}

fn key2(a: &str, b: &str) -> (String, String) {
    if a <= b { (a.into(), b.into()) } else { (b.into(), a.into()) }
}

/// (extrude id, {curve, curve}) for curves of its sketch that meet tangentially.
fn smooth_pairs(design: &Value) -> HashSet<(i64, (String, String))> {
    let mut out = HashSet::new();
    let feats = design["features"].as_array().cloned().unwrap_or_default();
    let sketches: HashMap<i64, &Value> = feats.iter().filter(|f| f["type"] == "sketch").map(|f| (f["id"].as_i64().unwrap_or(0), &f["sketch"])).collect();
    for f in &feats {
        let Some(sk) = f.get("sketch").and_then(Value::as_i64).and_then(|i| sketches.get(&i)) else { continue };
        let pts: Vec<(f64, f64)> = sk["points"].as_array().map_or(vec![], |ps| ps.iter().map(|p| (p["pos"][0].as_f64().unwrap_or(0.0), p["pos"][1].as_f64().unwrap_or(0.0))).collect());
        let mut ends: Vec<((i64, i64), Vec<(String, (f64, f64))>)> = Vec::new();
        for c in sk["curves"].as_array().cloned().unwrap_or_default() {
            let ty = c["type"].as_str().unwrap_or("");
            if c.get("construction").and_then(Value::as_bool).unwrap_or(false) || !(ty == "line" || ty == "arc") {
                continue;
            }
            for k in ["a", "b"] {
                let p = pts[c[k].as_u64().unwrap_or(0) as usize];
                let t = if ty == "line" {
                    let q = pts[c[if k == "a" { "b" } else { "a" }].as_u64().unwrap_or(0) as usize];
                    (q.0 - p.0, q.1 - p.1)
                } else {
                    let o = pts[c["c"].as_u64().unwrap_or(0) as usize];
                    (-(p.1 - o.1), p.0 - o.0)
                };
                let key = ((crate::pyfmt::round(p.0, 6) * 1e6).round() as i64, (crate::pyfmt::round(p.1, 6) * 1e6).round() as i64);
                let id = c["id"].as_str().unwrap_or("").to_string();
                match ends.iter_mut().find(|e| e.0 == key) {
                    Some(e) => e.1.push((id, t)),
                    None => ends.push((key, vec![(id, t)])),
                }
            }
        }
        for (_, here) in &ends {
            for i in 0..here.len() {
                for (c2, t2) in &here[i + 1..] {
                    let (c1, t1) = &here[i];
                    let n = t1.0.hypot(t1.1) * t2.0.hypot(t2.1);
                    if n != 0.0 && (t1.0 * t2.1 - t1.1 * t2.0).abs() <= 1e-6 * n {
                        out.insert((f["id"].as_i64().unwrap_or(0), key2(c1, c2)));
                    }
                }
            }
        }
    }
    out
}
