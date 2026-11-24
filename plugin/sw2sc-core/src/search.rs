//! The rebuild search (port of `rebuild`, `_search`, `_sequential`, `_with_fillets`,
//! `_mirror_planes` and `_prefix` in `sw2sc/verify.py`).
//!
//! Python's generators become a recursive `step` that hands each complete design to a sink; the
//! sink judges it and says whether to stop.

use std::collections::{BTreeSet, HashMap, HashSet};
use std::rc::Rc;

use serde_json::{json, Value};

use crate::design::{self, design, Choices, Picks};
use crate::features::Feature;
use crate::fillets::{self, Amap};
use crate::pyfmt::{g, repr, round};
use crate::verify::{fully_decoded, gap, same, Eval, Evaluator, MAX_FILLET_CHOICES, REL, SAME, TIME_BUDGET};

pub const MAX_TRIES: usize = 120;

/// How the search went, for the import report.
#[derive(Clone, Debug, Default)]
pub struct Outcome {
    pub reference: Option<Eval>,
    /// The closest candidate evaluated.
    pub closest: Option<Eval>,
    pub tries: usize,
    pub timed_out: bool,
}

/// The evaluator as the search uses it: past the time budget it evaluates nothing more, so the
/// loops still running end at once instead of trying every remaining option.
struct Timed<'a> {
    inner: &'a mut dyn Evaluator,
    deadline: f64,
}

impl Evaluator for Timed<'_> {
    fn evaluate(&mut self, design: &Value) -> Option<Eval> {
        if self.inner.now() > self.deadline { None } else { self.inner.evaluate(design) }
    }
    fn edges(&mut self, design: &Value) -> Option<Value> {
        if self.inner.now() > self.deadline { None } else { self.inner.edges(design) }
    }
    fn faces(&mut self, design: &Value) -> Option<Value> {
        if self.inner.now() > self.deadline { None } else { self.inner.faces(design) }
    }
    fn now(&self) -> f64 {
        self.inner.now()
    }
}

struct Ctx<'a> {
    name: String,
    feats: &'a mut Vec<Feature>,
    planes: HashMap<String, usize>,
    constraints: bool,
    ev: &'a mut dyn Evaluator,
    rf: Option<Eval>,
    deadline: f64,
    out: Outcome,
    /// The box check's second pass: a partial build may lie outside the part's box when a cut
    /// still to come could trim it (an imported blank wider than the part).
    relax_box: bool,
    /// The strict pass stopped such a build, so the second pass is worth running.
    box_blocked: bool,
    /// How far the sequential build got: the index in `feats` of the furthest feature it tried
    /// (`feats.len()` once it made a whole design).
    reach: Option<usize>,
}

/// Python's `round(x, 6)` as a key part.
fn k6(x: Option<f64>) -> i64 {
    (round(x.unwrap_or(0.0), 6) * 1e6).round() as i64
}

impl Ctx<'_> {
    fn late(&mut self) -> bool {
        let late = self.ev.now() > self.deadline;
        self.out.timed_out |= late;
        late
    }

    fn design(&mut self, choices: &Choices, picks: &Picks, upto: Option<&str>) -> Value {
        let mut d = design(&self.name, self.feats, choices, &self.planes, self.constraints, picks, upto);
        if let Some(o) = d.as_object_mut() {
            o.remove("pending");
        }
        d
    }

    fn prefix(&mut self, choices: &Choices, picks: &Picks, upto: &str) -> (Value, Option<Eval>) {
        let d = self.design(choices, picks, Some(upto));
        let r = self.ev.evaluate(&d);
        (d, r)
    }

    /// Evaluate a candidate, remember how close it came, and say whether it matches.
    fn judge(&mut self, d: &Value) -> bool {
        let r = self.ev.evaluate(d);
        self.out.tries += 1;
        if let (Some(r), Some(rf)) = (&r, &self.rf) {
            if self.out.closest.as_ref().is_none_or(|c| gap(r, rf) < gap(c, rf)) {
                self.out.closest = Some(r.clone());
            }
        }
        same(r.as_ref(), self.rf.as_ref())
    }

    fn by_fname(&self, n: &str) -> Option<&Feature> {
        self.feats.iter().find(|x| x.name == n)
    }
}

type Sink<'s> = dyn FnMut(&mut Ctx, Value) -> bool + 's;

/// Cartesian product of `sizes` (each index running 0..size), in itertools.product's order.
fn product(sizes: &[usize]) -> Vec<Vec<usize>> {
    let mut out = vec![vec![]];
    for &n in sizes {
        let mut next = Vec::new();
        for p in &out {
            for i in 0..n {
                let mut q = p.clone();
                q.push(i);
                next.push(q);
            }
        }
        out = next;
    }
    out
}

/// The feature tree as a SolidCraft design whose rebuild matches `reference` (a design with the
/// part's own solid), or None; and how the search went.
pub fn rebuild(feats: &mut Vec<Feature>, reference: &Value, name: &str, ev: &mut dyn Evaluator) -> (Option<Value>, Outcome) {
    let mut outcome = Outcome::default();
    if !fully_decoded(feats) {
        return (None, outcome);
    }
    let rf = ev.evaluate(reference);
    outcome.reference = rf.clone();
    let Some(rf) = rf.filter(|r| r.volume.is_some_and(|v| v != 0.0) || r.area.is_some_and(|a| a != 0.0)) else {
        return (None, outcome);
    };
    let deadline = ev.now() + TIME_BUDGET;
    let mut timed = Timed { inner: ev, deadline };
    let mut ctx = Ctx {
        name: name.into(), feats, planes: HashMap::new(), constraints: true, ev: &mut timed, rf: Some(rf), deadline, out: outcome,
        relax_box: false, box_blocked: false, reach: None,
    };
    for constraints in [true, false] {
        // without the sketches' constraints only if they spoil it
        ctx.constraints = constraints;
        if let Some(d) = search(&mut ctx) {
            return (Some(d), ctx.out);
        }
        if ctx.box_blocked {
            ctx.relax_box = true;
            let found = search(&mut ctx);
            ctx.relax_box = false;
            ctx.box_blocked = false;
            if let Some(d) = found {
                return (Some(d), ctx.out);
            }
        }
    }
    (None, ctx.out)
}

/// Try the candidates the file leaves open (sketch planes, revolve axes and sides, extrude
/// directions); the first design whose rebuild matches, or None.
fn search(ctx: &mut Ctx) -> Option<Value> {
    let extr: Vec<String> = ctx.feats.iter().filter(|f| f.kind == "boss" || f.kind == "cut").map(|f| f.name.clone()).collect();
    let revs: Vec<String> = ctx.feats.iter().filter(|f| f.kind == "revolve" || f.kind == "revcut").map(|f| f.name.clone()).collect();
    let sk_list: Vec<(String, usize, Vec<usize>)> = ctx
        .feats
        .iter()
        .filter(|f| f.kind == "sketch")
        .map(|f| {
            let s = f.sketch.as_ref().unwrap();
            (f.name.clone(), s.planes.len(), s.alt_centres.keys().copied().collect())
        })
        .collect();
    let rev_opts: Vec<Vec<(usize, i64)>> = revs
        .iter()
        .map(|r| {
            let f = ctx.by_fname(r).unwrap();
            let sk = ctx.by_fname(f.profile.as_deref().unwrap_or("")).and_then(|s| s.sketch.as_ref());
            let n = sk.map_or(0, |s| design::revolve_axis_options(s).len()).min(8);
            (0..n).flat_map(|a| [(a, 1), (a, -1)]).collect()
        })
        .collect();
    // arcs whose centre the file leaves open: none turned first, then each sketch's alone, then all
    let alts: Vec<&(String, usize, Vec<usize>)> = sk_list.iter().filter(|s| !s.2.is_empty()).collect();
    let mut arc_opts: Vec<Vec<(String, Vec<usize>)>> = vec![vec![]];
    for s in &alts {
        arc_opts.push(vec![(format!("arcs:{}", s.0), s.2.clone())]);
        if s.2.len() > 1 {
            for n in &s.2 {
                arc_opts.push(vec![(format!("arcs:{}", s.0), vec![*n])]);
            }
        }
    }
    if alts.len() > 1 {
        arc_opts.push(alts.iter().map(|s| (format!("arcs:{}", s.0), s.2.clone())).collect());
    }
    let seq = ctx.feats.iter().any(|f| {
        ["fillet", "chamfer", "hole", "mirror", "thread", "pattern", "dome", "sweep", "sweepcut", "shell", "scale"].contains(&f.kind.as_str())
            || f.thin_mm.is_some_and(|t| t != 0.0)
            || f.through_all
    });
    let options = ["positive", "negative", "symmetric"];
    let mut tries = 0usize;
    let mut done: HashSet<String> = HashSet::new();
    // plane sets whose sequence stopped short: (arc and revolve choices, the planes of the
    // sketches before the feature it got stuck at). What is built up to there depends only on
    // those, so a later set with the same planes for them stops there too and is skipped
    let mut stuck: Vec<(String, Vec<(usize, usize)>)> = Vec::new();
    // each sketch's planes, those that put its points inside the part's box first (a sketch on a
    // face of the part lies on the part; a cut's outline may reach past it, so it only orders)
    let plane_orders: Vec<Vec<usize>> = sk_list
        .iter()
        .map(|(name, n, _)| {
            let sk = ctx.by_fname(name).and_then(|f| f.sketch.as_ref()).unwrap();
            let outside = |k: usize| -> usize {
                let Some(rf) = ctx.rf.as_ref() else { return 0 };
                let (Some(lo), Some(hi)) = (rf.lo, rf.hi) else { return 0 };
                let ([x, y, _], t) = sk.planes[k].0;
                let tol = REL * (0..3).map(|i| hi[i] - lo[i]).fold(f64::NEG_INFINITY, f64::max).max(1.0) + 1e-6;
                sk.points
                    .values()
                    .filter(|(u, v)| {
                        let w = [0, 1, 2].map(|i| (t[i] + u * x[i] + v * y[i]) * 1000.0);
                        (0..3).any(|i| w[i] < lo[i] - tol || w[i] > hi[i] + tol)
                    })
                    .count()
            };
            let mut ks: Vec<usize> = (0..*n).collect();
            ks.sort_by_key(|k| outside(*k)); // stable, as Python's sorted
            ks
        })
        .collect();
    let plane_sets: Vec<Vec<usize>> = product(&sk_list.iter().map(|s| s.1).collect::<Vec<_>>())
        .into_iter()
        .map(|pc| pc.iter().enumerate().map(|(j, k)| plane_orders[j][*k]).collect())
        .collect();
    let rev_sets = product(&rev_opts.iter().map(|o| o.len()).collect::<Vec<_>>());
    // built in sequence, each extrude's direction is chosen as it is built: one set is enough
    let dir_sets = if seq { vec![vec![0; extr.len()]] } else { product(&vec![3; extr.len()]) };
    for pc in &plane_sets {
        for ac in &arc_opts {
            for rc in &rev_sets {
                for dc in &dir_sets {
                    if ctx.late() {
                        return None;
                    }
                    let key = format!("{pc:?}|{ac:?}|{rc:?}");
                    if seq && done.contains(&key) {
                        continue; // directions are chosen in sequence: once per plane/arc/revolve choice
                    }
                    let rest = format!("{ac:?}|{rc:?}");
                    if seq && stuck.iter().any(|(k0, fixed)| *k0 == rest && fixed.iter().all(|(j, v)| pc[*j] == *v)) {
                        continue;
                    }
                    tries += 1;
                    if tries > MAX_TRIES {
                        return None;
                    }
                    let mut choices: Choices = HashMap::new();
                    for (k, v) in ac {
                        choices.insert(k.clone(), json!(v));
                    }
                    for (f, c) in extr.iter().zip(dc) {
                        choices.insert(f.clone(), json!([options[*c], null]));
                    }
                    for ((f, i), opts) in revs.iter().zip(rc).zip(&rev_opts) {
                        let (a, s) = opts[*i];
                        choices.insert(f.clone(), json!([a, s]));
                    }
                    ctx.planes = sk_list.iter().zip(pc).map(|(s, i)| (s.0.clone(), *i)).collect();
                    let mut found: Option<Value> = None;
                    let mut count = tries;
                    let mut sink = |c: &mut Ctx, d: Value| -> bool {
                        if c.judge(&d) {
                            found = Some(d);
                            return true;
                        }
                        count += 1;
                        count > MAX_TRIES
                    };
                    if seq {
                        done.insert(key);
                        ctx.reach = None;
                        sequential(ctx, &choices, &mut sink);
                        let reached = ctx.reach.take();
                        if let Some(at) = reached.filter(|&at| at < ctx.feats.len()) {
                            if !ctx.late() {
                                let before: HashSet<&str> = ctx.feats[..at].iter().map(|x| x.name.as_str()).collect();
                                let fixed = sk_list.iter().enumerate().filter(|(_, s)| before.contains(s.0.as_str())).map(|(j, _)| (j, pc[j])).collect();
                                stuck.push((rest, fixed));
                            }
                        }
                    } else {
                        with_fillets(ctx, &choices, &Picks::new(), &mut sink);
                    }
                    tries = count;
                    if found.is_some() {
                        return found;
                    }
                    if tries > MAX_TRIES {
                        return None;
                    }
                }
            }
        }
    }
    None
}

fn flips_for(f: &Feature, tol: f64) -> Vec<bool> {
    if f.kind == "chamfer" && (f.chamfer_mm2.is_some() || f.chamfer_deg.is_some_and(|a| (a - 45.0).abs() > tol)) {
        vec![false, true]
    } else {
        vec![false]
    }
}

fn edges_value(edges: &[(Value, String)]) -> Value {
    Value::Array(edges.iter().map(|(m, n)| json!([m, n])).collect())
}

/// Every complete design for these choices, each fillet's edges found in the design built up to
/// it, trying the edge sets that fit (a few at most), in order. Returns true to stop.
fn with_fillets(ctx: &mut Ctx, choices: &Choices, picks: &Picks, sink: &mut Sink) -> bool {
    let mut d = design(&ctx.name, ctx.feats, choices, &ctx.planes, ctx.constraints, picks, None);
    let pending = d.as_object_mut().and_then(|o| o.remove("pending"));
    let Some(pending) = pending.and_then(|p| p.as_str().map(String::from)) else {
        return sink(ctx, d);
    };
    let f = ctx.by_fname(&pending).unwrap().clone();
    let known = picks.known.clone();
    let cands = fillets::candidates(&d, &f, ctx.feats, ctx.ev, known.as_deref().map(|v| v.as_slice()));
    for (edges, amaps) in cands.into_iter().take(MAX_FILLET_CHOICES) {
        let amaps: Rc<Vec<Amap>> = Rc::new(amaps);
        for flip in flips_for(&f, 1e-9) {
            let mut p2 = picks.with(&pending, edges_value(&edges)).with(&format!("flip:{pending}"), json!(flip));
            p2.known = Some(amaps.clone());
            if with_fillets(ctx, choices, &p2, sink) {
                return true;
            }
        }
    }
    false
}

/// Planes a mirror may be about: those its record names, then the planar faces of the body built
/// so far whose name fits the face SolidWorks names, then every other planar face, then the
/// three planes through the origin.
fn mirror_planes(ctx: &mut Ctx, f: &Feature, choices: &Choices, picks: &Picks) -> Vec<Value> {
    let mut out: Vec<Value> = Vec::new();
    let mut add = |origin: [f64; 3], x: [f64; 3], y: [f64; 3]| {
        let pl = json!({"origin": origin.map(|c| round(c, 9)), "x_dir": x.map(|c| round(c, 12)), "y_dir": y.map(|c| round(c, 12))});
        if !out.contains(&pl) {
            out.push(pl);
        }
    };
    for ([x, y, _n], t) in &f.mirror_planes {
        add([t[0] * 1000.0, t[1] * 1000.0, t[2] * 1000.0], *x, *y);
    }
    let d = ctx.design(choices, picks, None);
    let faces = fillets::body_faces(&d, ctx.ev);
    let want = want_face(ctx, f, &d);
    let mut planar: Vec<&Value> = faces.iter().filter(|x| x.get("plane_normal").is_some_and(|n| !n.is_null())).collect();
    planar.sort_by_key(|x| !fits_face(x, &want)); // stable
    for face in planar {
        let n = v3(&face["plane_normal"]);
        let a = if n[0].abs() < 0.9 { [1.0, 0.0, 0.0] } else { [0.0, 1.0, 0.0] };
        let dt = a[0] * n[0] + a[1] * n[1] + a[2] * n[2];
        let x = [a[0] - dt * n[0], a[1] - dt * n[1], a[2] - dt * n[2]];
        let ln = (x[0] * x[0] + x[1] * x[1] + x[2] * x[2]).sqrt();
        let x = [x[0] / ln, x[1] / ln, x[2] / ln];
        let y = [n[1] * x[2] - n[2] * x[1], n[2] * x[0] - n[0] * x[2], n[0] * x[1] - n[1] * x[0]];
        add(v3(&face["centroid"]), x, y);
    }
    for (x, y) in [([1.0, 0.0, 0.0], [0.0, 1.0, 0.0]), ([0.0, 1.0, 0.0], [0.0, 0.0, 1.0]), ([0.0, 0.0, 1.0], [1.0, 0.0, 0.0])] {
        add([0.0; 3], x, y);
    }
    out.truncate(24);
    out
}

fn v3(v: &Value) -> [f64; 3] {
    [0, 1, 2].map(|i| v[i].as_f64().unwrap_or(0.0))
}

/// (kind, design id) of the face SolidWorks names for a mirror or shell, when its feature is in
/// the design.
fn want_face(ctx: &Ctx, f: &Feature, d: &Value) -> Option<(&'static str, Option<i64>)> {
    let mf = f.mirror_face?;
    let src = ctx.feats.iter().find(|x| x.fid == mf.fid).map(|x| x.name.clone());
    let id = src.and_then(|s| d["features"].as_array()?.iter().find(|g| g["name"] == s.as_str()).and_then(|g| g["id"].as_i64()));
    Some((mf.kind(), id))
}

fn fits_face(face: &Value, want: &Option<(&'static str, Option<i64>)>) -> bool {
    let Some((kind, id)) = want else { return false };
    let Some(name) = face.get("name").and_then(Value::as_str) else { return false };
    let Some(fc) = fillets::faces(&format!("{name}|{name}")) else { return false };
    fc.0 .0 == *kind && Some(fc.0 .1) == *id
}

/// Complete designs, built feature by feature (see the Python's `_sequential`).
fn sequential(ctx: &mut Ctx, choices: &Choices, sink: &mut Sink) -> bool {
    use std::f64::consts::PI;
    let order: Vec<Feature> = ctx
        .feats
        .iter()
        .filter(|f| ["boss", "cut", "fillet", "chamfer", "hole", "mirror", "thread", "pattern", "dome", "sweep", "sweepcut", "shell", "scale"].contains(&f.kind.as_str()))
        .cloned()
        .collect();
    let most = |f: &Feature, feats: &[Feature]| -> Option<f64> {
        let sk = feats.iter().find(|x| Some(&x.name) == f.profile.as_ref()).and_then(|x| x.sketch.as_ref())?;
        if !(f.kind == "boss" || f.kind == "cut") || f.through_all || f.depth_mm.is_none_or(|d| d == 0.0) {
            return None;
        }
        let mut area = 0.0;
        for (_ids, poly) in design::loops(sk) {
            let n = poly.len();
            let a: f64 = (0..n).map(|i| poly[i].0 * poly[(i + 1) % n].1 - poly[(i + 1) % n].0 * poly[i].1).sum::<f64>().abs() / 2.0;
            area += a * 1e6;
        }
        let p = &sk.points;
        area += sk.arcs.iter().map(|(a, _b, c)| PI * ((p[a].0 - p[c].0).hypot(p[a].1 - p[c].1) * 1000.0).powi(2) / 2.0).sum::<f64>();
        area += sk.circles.iter().map(|(_c, r)| PI * (r * 1000.0).powi(2)).sum::<f64>();
        Some(area * f.depth_mm.unwrap() * 1.05)
    };
    let mut adds: Vec<Option<f64>> = Vec::new();
    let mut takes: Vec<Option<f64>> = Vec::new();
    for i in 0..=order.len() {
        let rest = &order[i..];
        let a: Vec<Option<f64>> = rest.iter().filter(|f| f.kind == "boss" || f.alt_kind.as_deref() == Some("boss")).map(|f| most(f, ctx.feats)).collect();
        let t: Vec<Option<f64>> = rest.iter().filter(|f| f.kind == "cut" || f.kind == "hole" || f.alt_kind.as_deref() == Some("cut")).map(|f| most(f, ctx.feats)).collect();
        adds.push(if a.iter().any(Option::is_none) { None } else { Some(a.iter().map(|x| x.unwrap()).sum()) });
        takes.push(if t.iter().any(Option::is_none) || rest.iter().any(|f| f.kind == "hole") { None } else { Some(t.iter().map(|x| x.unwrap()).sum()) });
    }
    // a scale changes the solid's size and place: before it, neither the volume bounds nor the
    // part's box say anything about the solid built so far
    let first_scale = order.iter().position(|f| f.kind == "scale").unwrap_or(order.len());
    // whether a cut is still to come after each step: material outside the part's box can still go
    let cut_after: Vec<bool> = order
        .iter()
        .map(|f| {
            let at = ctx.feats.iter().position(|x| x.name == f.name).unwrap_or(0);
            ctx.feats[at + 1..].iter().any(|x| ["cut", "hole", "revcut", "sweepcut"].contains(&x.kind.as_str()) || x.alt_kind.as_deref() == Some("cut"))
        })
        .collect();
    // whether anything still to come after each step can add material (and so grow the solid's
    // box): cuts, holes, fillets, chamfers and shells never reach past the solid they work on
    let add_after: Vec<bool> = order
        .iter()
        .map(|f| {
            let at = ctx.feats.iter().position(|x| x.name == f.name).unwrap_or(0);
            ctx.feats[at + 1..].iter().any(|x| {
                ["boss", "revolve", "sweep", "mirror", "pattern", "thread", "dome", "scale", "import"].contains(&x.kind.as_str())
                    || x.alt_kind.as_deref() == Some("boss")
            })
        })
        .collect();
    let shared = Shared { order, adds, takes, first_scale, cut_after, add_after };
    step(ctx, &shared, 0, choices, &Picks::new(), None, sink)
}

struct Shared {
    first_scale: usize,
    cut_after: Vec<bool>,
    add_after: Vec<bool>,
    order: Vec<Feature>,
    adds: Vec<Option<f64>>,
    takes: Vec<Option<f64>>,
}

impl Shared {
    /// The part's own numbers for the box check at step i, or none while a scale is still to
    /// come (or, in the second pass, a cut that could trim it).
    fn box_rf<'a>(&self, rf: Option<&'a Eval>, i: usize, relax: bool) -> Option<&'a Eval> {
        if self.first_scale != self.order.len() || (relax && self.cut_after[i]) { None } else { rf }
    }

    /// Can the solid after step i still become the part?
    fn reachable(&self, rf: Option<&Eval>, r: &Eval, i: usize) -> bool {
        if i < self.first_scale {
            return true;
        }
        let Some(target) = rf.and_then(|x| x.volume).filter(|v| *v != 0.0) else { return true };
        let v = r.volume.unwrap_or(0.0);
        if let Some(a) = self.adds[i + 1] {
            if v + a < target * (1.0 - REL) {
                return false;
            }
        }
        if let Some(t) = self.takes[i + 1] {
            if !self.order[i + 1..].iter().any(|f| f.kind == "fillet" || f.kind == "chamfer") && v - t > target * (1.0 + REL) {
                return false;
            }
        }
        true
    }
}

/// `ok` at step i, noting when the box check alone stopped a build a later cut could trim.
fn ok_at(ctx: &mut Ctx, sh: &Shared, r: &Option<Eval>, i: usize) -> bool {
    let rf = ctx.rf.clone();
    if ok(sh.box_rf(rf.as_ref(), i, ctx.relax_box), r) {
        // with nothing left that adds material, a build that falls short of the part's box can't
        // become the part (a boss read as a cut: the part goes on past it)
        if let (Some(rf), Some(r)) = (rf.as_ref(), r.as_ref()) {
            if let (Some(rlo), Some(rhi), Some(lo), Some(hi)) = (rf.lo, rf.hi, r.lo, r.hi) {
                if sh.first_scale == sh.order.len() && !sh.add_after[i] {
                    let tol = REL * (0..3).map(|k| rhi[k] - rlo[k]).fold(f64::NEG_INFINITY, f64::max).max(1.0);
                    if (0..3).any(|k| lo[k] > rlo[k] + tol || hi[k] < rhi[k] - tol) {
                        return false;
                    }
                }
            }
        }
        return true;
    }
    if sh.cut_after[i] && ok(None, r) {
        ctx.box_blocked = true;
    }
    false
}

/// A partial build that can still become the part: it built, and lies inside the part's box.
fn ok(rf: Option<&Eval>, r: &Option<Eval>) -> bool {
    let Some(r) = r else { return false };
    if !r.errors.is_empty() || r.volume.is_none_or(|v| v == 0.0) {
        return false;
    }
    if let (Some(rf), Some(lo), Some(hi)) = (rf, r.lo, r.hi) {
        if let (Some(rlo), Some(rhi)) = (rf.lo, rf.hi) {
            let size = (0..3).map(|k| rhi[k] - rlo[k]).fold(f64::NEG_INFINITY, f64::max).max(1.0);
            let tol = REL * size;
            if (0..3).any(|k| lo[k] < rlo[k] - tol || hi[k] > rhi[k] + tol) {
                return false;
            }
        }
    }
    true
}

/// Try a pick for step i: build up to the feature, and go on with it when it is a new solid that
/// can still become the part. Returns true to stop.
#[allow(clippy::too_many_arguments)]
fn try_pick(ctx: &mut Ctx, sh: &Shared, i: usize, choices: &Choices, p2: Picks, seen: &mut Vec<(i64, i64)>, reach: bool, sink: &mut Sink) -> bool {
    let f = &sh.order[i];
    let (_d, r) = ctx.prefix(choices, &p2, &f.name.clone());
    if !ok_at(ctx, sh, &r, i) {
        return false;
    }
    let r = r.unwrap();
    if reach && !sh.reachable(ctx.rf.as_ref(), &r, i) {
        return false;
    }
    let key = (k6(r.volume), k6(r.area));
    if seen.contains(&key) {
        return false;
    }
    seen.push(key);
    step(ctx, sh, i + 1, choices, &p2, r.volume, sink)
}

#[allow(clippy::too_many_arguments)]
fn step(ctx: &mut Ctx, sh: &Shared, i: usize, choices: &Choices, picks: &Picks, vol: Option<f64>, sink: &mut Sink) -> bool {
    if ctx.late() {
        return false;
    }
    let at = if i < sh.order.len() { ctx.feats.iter().position(|x| x.name == sh.order[i].name).unwrap_or(0) } else { ctx.feats.len() };
    ctx.reach = Some(ctx.reach.map_or(at, |r| r.max(at)));
    if i == sh.order.len() {
        let d = ctx.design(choices, picks, None);
        return sink(ctx, d);
    }
    let f = sh.order[i].clone();
    let rf = ctx.rf.clone();
    match f.kind.as_str() {
        "boss" | "cut" => {
            let mut seen: Vec<(i64, i64, Vec<i64>)> = Vec::new();
            let at = ctx.feats.iter().position(|x| x.name == f.name).unwrap_or(0);
            let first = !sh.order[..i].iter().any(|x| ["boss", "cut", "revolve", "revcut", "sweep"].contains(&x.kind.as_str()))
                && !ctx.feats[..at].iter().any(|x| x.kind == "import");
            let mut ops: Vec<Option<&str>> = vec![None];
            if let Some(alt) = f.alt_kind.as_deref() {
                if !first {
                    ops.push(Some(if alt == "boss" { "join" } else { "cut" }));
                }
            }
            // no depth in the file: through all, or up to a flat face of the body so far
            let mut tos: Vec<Option<Value>> = vec![None];
            if f.through_all && !first {
                let d0 = ctx.design(choices, picks, None);
                let faces = fillets::body_faces(&d0, ctx.ev);
                tos.extend(faces.iter().filter(|x| x.get("plane_normal").is_some_and(|n| !n.is_null())).take(16).map(|x| Some(x["point"].clone())));
            }
            // a boss through all reaches as far as the body does: the distance from its sketch
            // plane to the body's box
            let mut spans: HashMap<&str, f64> = HashMap::new();
            if f.through_all && !first && f.kind == "boss" {
                let prev = sh.order[i - 1].name.clone();
                let (_d0, r0) = ctx.prefix(choices, picks, &prev);
                let sk_f = ctx.by_fname(f.profile.as_deref().unwrap_or("")).cloned();
                if let (Some(r0), Some(sk_f)) = (r0, sk_f) {
                    let sk = sk_f.sketch.as_ref().unwrap();
                    if let (Some(lo), Some(hi), false) = (r0.lo, r0.hi, sk.planes.is_empty()) {
                        let pl = &sk.planes[ctx.planes.get(&sk_f.name).copied().unwrap_or(0).min(sk.planes.len() - 1)];
                        let ([_x, _y, n], t) = pl.0;
                        let o = [t[0] * 1000.0, t[1] * 1000.0, t[2] * 1000.0];
                        let mut reach = Vec::new();
                        for a in [lo[0], hi[0]] {
                            for b in [lo[1], hi[1]] {
                                for c in [lo[2], hi[2]] {
                                    reach.push((a - o[0]) * n[0] + (b - o[1]) * n[1] + (c - o[2]) * n[2]);
                                }
                            }
                        }
                        let up = reach.iter().copied().fold(f64::NEG_INFINITY, f64::max);
                        let down = -reach.iter().copied().fold(f64::INFINITY, f64::min);
                        spans.insert("positive", up);
                        spans.insert("negative", down);
                        spans.insert("symmetric", 2.0 * up.max(down));
                    }
                }
            }
            // a sketch whose plane reads through the origin may be on a face of the body so far
            // whose plane wasn't stored: it is tried from each side of the body's box along its normal
            let mut starts: Vec<f64> = Vec::new();
            if !first && !f.through_all && f.depth_mm.is_some_and(|d| d != 0.0) {
                let sk_f = ctx.by_fname(f.profile.as_deref().unwrap_or("")).cloned();
                let pl = sk_f.as_ref().and_then(|x| {
                    let sk = x.sketch.as_ref()?;
                    (!sk.planes.is_empty()).then(|| sk.planes[ctx.planes.get(&x.name).copied().unwrap_or(0).min(sk.planes.len() - 1)].0)
                });
                if let Some(([_x, _y, n], t)) = pl.filter(|p| p.1.iter().all(|c| c.abs() < 1e-12)) {
                    let _ = t;
                    let prev = sh.order[i - 1].name.clone();
                    let (d_pre, r0) = ctx.prefix(choices, picks, &prev);
                    if let Some((Some(lo), Some(hi))) = r0.map(|r| (r.lo, r.hi)) {
                        let mut along = Vec::new();
                        for a in [lo[0], hi[0]] {
                            for b in [lo[1], hi[1]] {
                                for c in [lo[2], hi[2]] {
                                    along.push(a * n[0] + b * n[1] + c * n[2]);
                                }
                            }
                        }
                        let up = along.iter().copied().fold(f64::NEG_INFINITY, f64::max);
                        let down = along.iter().copied().fold(f64::INFINITY, f64::min);
                        // the sides of the body's box, then its flat faces parallel to the sketch (a
                        // pocket's floor), at most 8
                        let mut cands = vec![up, down];
                        if !d_pre.is_null() {
                            for x in fillets::body_faces(&d_pre, ctx.ev) {
                                let Some(pn) = x.get("plane_normal").and_then(Value::as_array) else { continue };
                                let pn: Vec<f64> = pn.iter().filter_map(Value::as_f64).collect();
                                let pt: Vec<f64> = x.get("point").and_then(Value::as_array).map(|a| a.iter().filter_map(Value::as_f64).collect()).unwrap_or_default();
                                if pn.len() == 3 && pt.len() == 3 && (pn[0] * n[0] + pn[1] * n[1] + pn[2] * n[2]).abs() > 1.0 - 1e-9 {
                                    cands.push(pt[0] * n[0] + pt[1] * n[1] + pt[2] * n[2]);
                                }
                            }
                        }
                        for v in cands {
                            if v.abs() > 1e-6 && starts.iter().all(|w| (v - w).abs() > 1e-6) && starts.len() < 8 {
                                starts.push(v);
                            }
                        }
                    }
                }
            }
            let sides: Vec<Option<&str>> = if f.thin_mm.is_some_and(|t| t != 0.0) { vec![Some("center"), Some("inside"), Some("outside")] } else { vec![None] };
            for side in &sides {
                for to in &tos {
                    for op in &ops {
                        for opt in ["positive", "negative", "symmetric"] {
                            let mut sps: Vec<Option<f64>> = vec![None];
                            if let Some(&s) = spans.get(opt).filter(|s| **s > 1e-6) {
                                sps.push(Some(s));
                            }
                            for (sp, st) in sps.iter().flat_map(|sp| std::iter::once(None).chain(starts.iter().map(|s| Some(*s))).map(move |st| (*sp, st))) {
                                if to.is_some() && (opt == "symmetric" || sp.is_some()) {
                                    continue;
                                }
                                if st.is_some() && (to.is_some() || sp.is_some()) {
                                    continue;
                                }
                                let mut c2 = choices.clone();
                                c2.insert(f.name.clone(), json!([opt, op]));
                                let mut p_to = picks.clone();
                                if let Some(to) = to {
                                    p_to = p_to.with(&format!("to:{}", f.name), to.clone());
                                }
                                if let Some(sp) = sp {
                                    p_to = p_to.with(&format!("span:{}", f.name), json!(sp));
                                }
                                if let Some(st) = st {
                                    p_to = p_to.with(&format!("start:{}", f.name), json!(st));
                                }
                                if let Some(side) = side {
                                    p_to = p_to.with(&format!("thin:{}", f.name), json!(side));
                                }
                                let (_d, r) = ctx.prefix(&c2, &p_to, &f.name);
                                if !ok_at(ctx, sh, &r, i) {
                                    continue;
                                }
                                let r = r.unwrap();
                                let v = r.volume.unwrap_or(0.0);
                                if let Some(vol) = vol {
                                    if (v - vol).abs() <= SAME * vol.max(1.0) {
                                        continue;
                                    }
                                }
                                if !sh.reachable(rf.as_ref(), &r, i) {
                                    continue;
                                }
                                let bx: Vec<i64> = r.lo.iter().chain(r.hi.iter()).flat_map(|a| a.iter().map(|x| k6(Some(*x)))).collect();
                                let key = (k6(r.volume), k6(r.area), bx);
                                if seen.contains(&key) {
                                    continue; // the same solid another way: one is enough
                                }
                                seen.push(key);
                                if step(ctx, sh, i + 1, &c2, &p_to, r.volume, sink) {
                                    return true;
                                }
                            }
                        }
                    }
                }
            }
            false
        }
        "shell" => {
            // open at each flat face of the body so far (those fitting the face SolidWorks names first)
            let d0 = ctx.design(choices, picks, None);
            let want = want_face(ctx, &f, &d0).map(|(k, id)| (k, id));
            let faces = fillets::body_faces(&d0, ctx.ev);
            let mut flat: Vec<&Value> = faces.iter().filter(|x| x.get("plane_normal").is_some_and(|n| !n.is_null())).collect();
            flat.sort_by_key(|x| !fits_face(x, &want));
            let mut seen = Vec::new();
            for face in flat.into_iter().take(16) {
                let p2 = picks.with(&format!("shell:{}", f.name), json!([face["point"]]));
                if try_pick(ctx, sh, i, choices, p2, &mut seen, true, sink) {
                    return true;
                }
            }
            false
        }
        "sweep" | "sweepcut" => {
            let mut seen = Vec::new();
            for swap in [false, true] {
                let p2 = picks.with(&format!("swap:{}", f.name), json!(swap));
                if try_pick(ctx, sh, i, choices, p2, &mut seen, true, sink) {
                    return true;
                }
            }
            false
        }
        "scale" => {
            // about the origin, the centre of mass or the middle of the box of the solid so far
            let mut origins: Vec<Value> = vec![json!([0.0, 0.0, 0.0])];
            if i > 0 {
                let prev = sh.order[i - 1].name.clone();
                if let (_, Some(r0)) = ctx.prefix(choices, picks, &prev) {
                    if let Some(c) = r0.com {
                        origins.push(json!(c));
                    }
                    if let (Some(lo), Some(hi)) = (r0.lo, r0.hi) {
                        origins.push(json!([0, 1, 2].map(|k| (lo[k] + hi[k]) / 2.0)));
                    }
                }
            }
            let mut seen: Vec<(i64, i64)> = Vec::new();
            let mut boxes: Vec<Vec<i64>> = Vec::new();
            for o in origins {
                let p2 = picks.with(&format!("scale:{}", f.name), o);
                let (_d, r) = ctx.prefix(choices, &p2, &f.name);
                if !ok_at(ctx, sh, &r, i) {
                    continue;
                }
                let r = r.unwrap();
                if !sh.reachable(rf.as_ref(), &r, i) {
                    continue;
                }
                let bx: Vec<i64> = r.lo.iter().flat_map(|a| a.iter().map(|x| k6(Some(*x)))).collect();
                let key = (k6(r.volume), k6(r.area));
                if seen.iter().zip(&boxes).any(|(s, b)| *s == key && *b == bx) {
                    continue;
                }
                seen.push(key);
                boxes.push(bx);
                if step(ctx, sh, i + 1, choices, &p2, r.volume, sink) {
                    return true;
                }
            }
            false
        }
        "dome" => {
            // on a flat face (the area decides its radius)
            let d0 = ctx.design(choices, picks, None);
            let faces = fillets::body_faces(&d0, ctx.ev);
            let mut seen = Vec::new();
            for face in &faces {
                let Some(n) = face.get("plane_normal").filter(|n| !n.is_null()) else { continue };
                let n = v3(n);
                let c = face["centroid"].clone();
                let r = (face["area"].as_f64().unwrap_or(0.0) / std::f64::consts::PI).sqrt();
                for sgn in [1.0, -1.0] {
                    let nn = [sgn * n[0], sgn * n[1], sgn * n[2]];
                    let p2 = picks.with(&format!("dome:{}", f.name), json!([c, nn, r]));
                    if try_pick(ctx, sh, i, choices, p2, &mut seen, true, sink) {
                        return true;
                    }
                }
            }
            false
        }
        "pattern" => {
            let solid: Vec<&Feature> = sh.order[..i].iter().filter(|x| ["boss", "cut", "hole", "fillet", "chamfer"].contains(&x.kind.as_str())).collect();
            let last_boss = solid.iter().enumerate().filter(|(_, x)| x.kind == "boss").map(|(k, _)| k).max().unwrap_or(0);
            let names = |s: &[&Feature]| s.iter().map(|x| x.name.clone()).collect::<Vec<_>>();
            let sets = [names(&solid[solid.len().saturating_sub(1)..]), names(&solid[(last_boss + 1).min(solid.len())..]), names(&solid[last_boss.min(solid.len())..])];
            let mut whats: Vec<Vec<String>> = Vec::new();
            for (k, s) in sets.iter().enumerate() {
                if !s.is_empty() && !sets[..k].contains(s) {
                    whats.push(s.clone());
                }
            }
            let pt = &f.pattern;
            let num = |k: &str| pt.get(k).and_then(Value::as_f64);
            let mut pats: Vec<Value> = Vec::new();
            if pt.get("kind").and_then(Value::as_str) == Some("linear") {
                let axes: [[f64; 3]; 6] = [[1.0, 0.0, 0.0], [-1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, 1.0], [0.0, 0.0, -1.0]];
                let int_repr = |x: f64| format!("{}", x.trunc() as i64);
                for a in axes {
                    let p = json!({"type": "rectangular", "dir1": a.map(|x| x as i64), "count1": int_repr(num("count1").unwrap_or(0.0)), "spacing1": repr(num("spacing1").unwrap_or(0.0))});
                    if num("count2").is_some_and(|c| c != 0.0) && num("spacing2").is_some_and(|s| s != 0.0) {
                        for a2 in axes {
                            if (a[0] * a2[0] + a[1] * a2[1] + a[2] * a2[2]).abs() < 1e-9 {
                                let mut q = p.clone();
                                q["dir2"] = json!(a2.map(|x| x as i64));
                                q["count2"] = json!(int_repr(num("count2").unwrap()));
                                q["spacing2"] = json!(repr(num("spacing2").unwrap()));
                                pats.push(q);
                            }
                        }
                    } else {
                        pats.push(p);
                    }
                }
            } else {
                let d0 = ctx.design(choices, picks, None);
                let faces = fillets::body_faces(&d0, ctx.ev);
                let mut lines: Vec<([f64; 3], [f64; 3])> =
                    faces.iter().filter_map(|c| c.get("cylinder").filter(|v| !v.is_null()).map(|cy| (v3(&cy["origin"]), v3(&cy["axis"])))).collect();
                lines.extend([([0.0; 3], [1.0, 0.0, 0.0]), ([0.0; 3], [0.0, 1.0, 0.0]), ([0.0; 3], [0.0, 0.0, 1.0])]);
                let n = num("count1").unwrap_or(0.0).trunc() as i64;
                let ang = num("angle").unwrap_or(0.0);
                let mut totals = vec![ang];
                if ang * (n - 1) as f64 <= 360.0 && n > 1 && ang < 360.0 {
                    totals.push(ang * (n - 1) as f64);
                }
                for (o, a) in &lines {
                    for tot in &totals {
                        let pc = json!({"type": "circular", "origin": o.map(|c| round(c, 9)), "axis": a.map(|c| round(c, 12)), "count": n.to_string(), "angle": format!("{} deg", g(*tot))});
                        if !pats.contains(&pc) {
                            pats.push(pc);
                        }
                    }
                }
            }
            let mut seen = Vec::new();
            for what in &whats {
                for p in pats.iter().take(40) {
                    let p2 = picks.with(&format!("pattern:{}", f.name), json!([p, what]));
                    if try_pick(ctx, sh, i, choices, p2, &mut seen, true, sink) {
                        return true;
                    }
                }
            }
            false
        }
        "thread" => {
            // on a cylinder of the body so far about its size, from either end
            let d0 = ctx.design(choices, picks, None);
            let faces = fillets::body_faces(&d0, ctx.ev);
            let r_major = f.thread.get("diameter").and_then(Value::as_f64).unwrap_or(0.0) / 2.0;
            let mut seen = Vec::new();
            for face in &faces {
                let Some(cyl) = face.get("cylinder").filter(|c| !c.is_null()) else { continue };
                let rad = cyl["radius"].as_f64().unwrap_or(0.0);
                if !(0.7 * r_major <= rad && rad <= 1.05 * r_major) {
                    continue;
                }
                let (ax, c, pt) = (v3(&cyl["axis"]), v3(&face["centroid"]), v3(&face["point"]));
                let h = face["area"].as_f64().unwrap_or(0.0) / (2.0 * std::f64::consts::PI * rad);
                let along: f64 = (0..3).map(|k| (pt[k] - c[k]) * ax[k]).sum();
                let rim = [0, 1, 2].map(|k| pt[k] - along * ax[k]);
                for sgn in [1.0, -1.0] {
                    let start = [0, 1, 2].map(|k| rim[k] + sgn * (h / 2.0 - 1e-3) * ax[k]);
                    let p2 = picks.with(&format!("thread:{}", f.name), json!([pt, start]));
                    if try_pick(ctx, sh, i, choices, p2, &mut seen, true, sink) {
                        return true;
                    }
                }
            }
            false
        }
        "mirror" => {
            let solid: Vec<&Feature> = sh.order[..i].iter().filter(|x| ["boss", "cut", "hole", "fillet", "chamfer"].contains(&x.kind.as_str())).collect();
            let last_boss = solid.iter().enumerate().filter(|(_, x)| x.kind == "boss").map(|(k, _)| k).max().unwrap_or(0);
            let names = |s: &[&Feature]| s.iter().map(|x| x.name.clone()).collect::<Vec<_>>();
            let sets = [names(&solid[(last_boss + 1).min(solid.len())..]), names(&solid[1.min(solid.len())..]), names(&solid[solid.len().saturating_sub(1)..])];
            let mut whats: Vec<Value> = Vec::new();
            for (k, s) in sets.iter().enumerate() {
                if !s.is_empty() && !sets[..k].contains(s) {
                    whats.push(json!(s));
                }
            }
            whats.push(json!("body"));
            let planes = mirror_planes(ctx, &f, choices, picks);
            let mut seen = Vec::new();
            for what in &whats {
                for plane in &planes {
                    let p2 = picks.with(&format!("mirror:{}", f.name), json!([plane, what]));
                    if try_pick(ctx, sh, i, choices, p2, &mut seen, true, sink) {
                        return true;
                    }
                }
            }
            false
        }
        "hole" => {
            // blind or through all, drilled one way or the other, at which of its sketch's points
            let sk = ctx.by_fname(f.profile.as_deref().unwrap_or("")).and_then(|x| x.sketch.clone()).unwrap();
            let mut ids: Vec<u32> = sk.points.keys().copied().collect();
            ids.sort();
            let mut uniq: Vec<((i64, i64), u32)> = Vec::new();
            for pid in ids {
                let (u, v) = sk.points[&pid];
                let key = ((round(u, 9) * 1e9).round() as i64, (round(v, 9) * 1e9).round() as i64);
                if !uniq.iter().any(|x| x.0 == key) {
                    uniq.push((key, pid));
                }
            }
            let keep: BTreeSet<u32> = uniq.iter().map(|x| x.1).collect();
            let flag = |p: &u32| sk.point_flags.get(p).copied();
            let cands = [
                keep.iter().filter(|p| flag(p) == Some(2)).copied().collect::<BTreeSet<_>>(),
                keep.iter().filter(|p| matches!(flag(p), Some(1) | Some(2))).copied().collect(),
                keep.iter().filter(|p| flag(p) == Some(1)).copied().collect(),
                keep.clone(),
            ];
            let mut sets: Vec<BTreeSet<u32>> = Vec::new();
            for (k, s) in cands.iter().enumerate() {
                if !s.is_empty() && !cands[..k].contains(s) {
                    sets.push(s.clone());
                }
            }
            let mut seen: Vec<(i64, i64)> = Vec::new();
            for s in &sets {
                for (a, c) in [(false, false), (false, true), (true, false), (true, true)] {
                    if a && !f.hole.contains_key("depth") && !seen.is_empty() {
                        return false; // (the Python's break leaves the hole's loop)
                    }
                    let p2 = picks.with(&format!("hole:{}", f.name), json!([a, c])).with(&format!("holepts:{}", f.name), json!(s));
                    let (_d, r) = ctx.prefix(choices, &p2, &f.name);
                    if !ok_at(ctx, sh, &r, i) {
                        continue;
                    }
                    let r = r.unwrap();
                    if let Some(vol) = vol {
                        if r.volume.unwrap_or(0.0) >= vol - SAME * vol.max(1.0) {
                            continue;
                        }
                    }
                    let key = (k6(r.volume), k6(r.area));
                    if seen.contains(&key) {
                        continue;
                    }
                    seen.push(key);
                    if step(ctx, sh, i + 1, choices, &p2, r.volume, sink) {
                        return true;
                    }
                }
            }
            false
        }
        _ => {
            // a fillet or chamfer: each edge set that fits, both sides for a one-sided chamfer
            let mut d = design(&ctx.name, ctx.feats, choices, &ctx.planes, ctx.constraints, picks, None);
            let pending = d.as_object_mut().and_then(|o| o.remove("pending"));
            if pending.as_ref().and_then(Value::as_str) != Some(f.name.as_str()) {
                return false;
            }
            let known = picks.known.clone();
            let cands = fillets::candidates(&d, &f, ctx.feats, ctx.ev, known.as_deref().map(|v| v.as_slice()));
            for (edges, amaps) in cands.into_iter().take(MAX_FILLET_CHOICES) {
                let amaps = Rc::new(amaps);
                for flip in flips_for(&f, 1e-6) {
                    let mut p2 = picks.with(&f.name, edges_value(&edges)).with(&format!("flip:{}", f.name), json!(flip));
                    p2.known = Some(amaps.clone());
                    let (_d, r) = ctx.prefix(choices, &p2, &f.name);
                    if !ok_at(ctx, sh, &r, i) || !sh.reachable(rf.as_ref(), r.as_ref().unwrap(), i) {
                        continue;
                    }
                    if step(ctx, sh, i + 1, choices, &p2, r.unwrap().volume, sink) {
                        return true;
                    }
                }
            }
            false
        }
    }
}
