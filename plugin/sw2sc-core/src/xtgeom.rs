//! A parsed Parasolid partition as a neutral B-rep that STEP can carry (port of
//! `sw2sc/xtgeom.py`).
//!
//! Exact where STEP has the same geometry: planes, cylinders, cones, spheres, tori, B-spline
//! surfaces and curves, lines, circles, ellipses, offsets of analytic surfaces. Approximated with
//! fitted B-splines where it doesn't: intersection curves, SP-curves, rolling-ball blends,
//! offsets of free-form surfaces, swept and spun surfaces. Lengths stay in metres here.

use std::cell::Cell;
use std::collections::{HashMap, HashSet};
use std::f64::consts::PI;
use std::rc::Rc;

use crate::nurbs::{self, Curve, Surface};
use crate::parasolid::{Node, Partition, F};

pub const NULL_DOUBLE: f64 = -3.14158e13;

pub type V = [f64; 3];

pub fn add(a: V, b: V) -> V {
    [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
}
pub fn sub(a: V, b: V) -> V {
    [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
}
pub fn mul(a: V, s: f64) -> V {
    [a[0] * s, a[1] * s, a[2] * s]
}
pub fn dot(a: V, b: V) -> f64 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}
pub fn cross(a: V, b: V) -> V {
    [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
}
pub fn norm(a: V) -> f64 {
    dot(a, a).sqrt()
}
pub fn unit(a: V) -> V {
    let n = norm(a);
    if n > 1e-300 { mul(a, 1.0 / n) } else { [0.0; 3] }
}
pub fn dist(a: V, b: V) -> f64 {
    norm(sub(a, b))
}
fn v3(p: &[f64]) -> V {
    [p[0], p[1], p[2]]
}
fn is_null(x: f64) -> bool {
    (x - NULL_DOUBLE).abs() < 1e3
}

#[derive(Debug)]
pub struct GeomError(pub String);

impl From<nurbs::NurbsError> for GeomError {
    fn from(e: nurbs::NurbsError) -> Self {
        GeomError(e.0)
    }
}

fn gerr<T>(m: impl Into<String>) -> Result<T, GeomError> {
    Err(GeomError(m.into()))
}

/// Python's float division: dividing by zero is an error, not infinity.
fn div(a: f64, b: f64) -> Result<f64, GeomError> {
    if b == 0.0 { gerr("float division by zero") } else { Ok(a / b) }
}

// --- neutral B-rep ------------------------------------------------------------------------
static NEXT_ID: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(1);
fn new_id() -> usize {
    NEXT_ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
}

#[derive(Debug)]
pub struct Vertex {
    pub id: usize,
    pub point: V,
}

#[derive(Clone, Debug)]
pub enum CurveSpec {
    Line(V, V),
    Circle(V, V, V, f64),
    Ellipse(V, V, V, f64, f64),
    BSpline(Curve),
}

#[derive(Debug)]
pub struct Edge {
    pub id: usize,
    pub start: Option<Rc<Vertex>>,
    pub end: Option<Rc<Vertex>>,
    pub curve: CurveSpec,
    pub same_sense: bool,
    pub approx: bool,
}

#[derive(Clone, Debug)]
pub struct Loop {
    pub edges: Vec<(Rc<Edge>, bool)>,
    pub vertex: Option<Rc<Vertex>>,
}

#[derive(Clone, Debug)]
pub enum SurfSpec {
    Plane(V, V, V),
    Cylinder(V, V, V, f64),
    Cone(V, V, V, f64, f64),
    Sphere(V, V, V, f64),
    Torus(V, V, V, f64, f64),
    BSpline(Surface),
    Blend(i64),
}

#[derive(Clone, Debug)]
pub struct Face {
    pub surface: SurfSpec,
    pub same_sense: bool,
    pub loops: Vec<Loop>,
    pub approx: bool,
    pub source: String,
}

#[derive(Clone, Debug)]
pub struct Shell {
    pub faces: Vec<Face>,
    pub closed: bool,
}

#[derive(Clone, Debug)]
pub struct Body {
    pub kind: String,
    pub outer: Vec<Shell>,
    pub voids: Vec<Shell>,
    pub name: String,
}

// --- NURBS from nodes -----------------------------------------------------------------------
fn reals(n: Option<&Node>, k: &str) -> Result<Vec<f64>, GeomError> {
    let n = n.ok_or(GeomError("missing NURBS data".into()))?;
    Ok(n.get(k).map_or(vec![], |f| f.list().iter().map(F::real).collect()))
}

fn ints(n: Option<&Node>, k: &str) -> Result<Vec<i64>, GeomError> {
    let n = n.ok_or(GeomError("missing NURBS data".into()))?;
    Ok(n.get(k).map_or(vec![], |f| f.list().iter().map(F::int).collect()))
}

fn bcurve(part: &Partition, node: &Node) -> Result<Curve, GeomError> {
    let Some(nc) = part.get(node.p("nurbs")) else { return gerr("B-curve without NURBS data") };
    let dim = nc.i("vertex_dim") as usize;
    let raw = reals(part.get(nc.p("bspline_vertices")), "vertices")?;
    let knots = reals(part.get(nc.p("knots")), "knots")?;
    let mults = ints(part.get(nc.p("knot_mult")), "mult")?;
    let rational = nc.get("rational").is_some_and(F::truthy);
    let (mut pts, mut w) = (Vec::new(), Vec::new());
    for i in 0..nc.i("n_vertices").max(0) as usize {
        let v = raw.get(i * dim..(i + 1) * dim).ok_or(GeomError("short vertex list".into()))?;
        if rational {
            let ww = if v[dim - 1] != 0.0 { v[dim - 1] } else { 1.0 };
            w.push(ww);
            pts.push(v[..dim - 1].iter().map(|c| c / ww).collect());
        } else {
            pts.push(v.to_vec());
        }
    }
    let u = nurbs::expand_knots(&knots, &mults);
    Ok(Curve::new(nc.i("degree") as usize, u, pts, if rational { Some(w) } else { None })?)
}

fn bsurface(part: &Partition, node: &Node) -> Result<Surface, GeomError> {
    let Some(ns) = part.get(node.p("nurbs")) else { return gerr("B-surface without NURBS data") };
    let dim = ns.i("vertex_dim") as usize;
    let raw = reals(part.get(ns.p("bspline_vertices")), "vertices")?;
    let (nu, nv) = (ns.i("n_u_vertices").max(0) as usize, ns.i("n_v_vertices").max(0) as usize);
    let rational = ns.get("rational").is_some_and(F::truthy);
    let u = nurbs::expand_knots(&reals(part.get(ns.p("u_knots")), "knots")?, &ints(part.get(ns.p("u_knot_mult")), "mult")?);
    let v = nurbs::expand_knots(&reals(part.get(ns.p("v_knots")), "knots")?, &ints(part.get(ns.p("v_knot_mult")), "mult")?);
    let (mut grid, mut wgrid) = (Vec::new(), Vec::new());
    // vertices are stored with v varying fastest
    for i in 0..nu {
        let (mut row, mut wrow) = (Vec::new(), Vec::new());
        for j in 0..nv {
            let k = (i * nv + j) * dim;
            let p = raw.get(k..k + dim).ok_or(GeomError("short vertex list".into()))?;
            if rational {
                let ww = if p[dim - 1] != 0.0 { p[dim - 1] } else { 1.0 };
                wrow.push(ww);
                row.push([p[0] / ww, p[1] / ww, p[2] / ww]);
            } else {
                row.push([p[0], p[1], p[2]]);
            }
        }
        grid.push(row);
        wgrid.push(wrow);
    }
    Ok(Surface::new(ns.i("u_degree") as usize, ns.i("v_degree") as usize, u, v, grid, if rational { Some(wgrid) } else { None })?)
}

// --- evaluators (the Python's closures) ---------------------------------------------------
pub enum CurveFn {
    Line(V, V),
    Circle(V, V, V, f64),
    Ellipse(V, V, V, f64, f64),
    B(Curve),
    Sp(Rc<SurfFn>, Curve),
}

impl CurveFn {
    pub fn at(&self, s: f64) -> V {
        match self {
            CurveFn::Line(p, d) => add(*p, mul(*d, s)),
            CurveFn::Circle(c, x, y, r) => add(*c, add(mul(*x, r * s.cos()), mul(*y, r * s.sin()))),
            CurveFn::Ellipse(c, x, y, a, b) => add(*c, add(mul(*x, a * s.cos()), mul(*y, b * s.sin()))),
            CurveFn::B(c) => v3(&c.at(s)),
            CurveFn::Sp(sf, c2) => {
                let q = c2.at(s);
                sf.at(q[0], q[1])
            }
        }
    }
}

pub type Dom = Option<(f64, f64)>;

pub enum SurfFn {
    Plane(V, V, V),
    Cylinder(V, V, V, V, f64),
    Cone(V, V, V, V, f64, f64),
    Sphere(V, V, V, V, f64),
    Torus(V, V, V, V, f64, f64),
    B(Surface),
    Offset(Rc<SurfFn>, f64),
    Spun(Rc<CurveFn>, V, V),
    Swept(Rc<CurveFn>, V),
}

impl SurfFn {
    pub fn at(&self, u: f64, v: f64) -> V {
        match self {
            SurfFn::Plane(p, x, y) => add(*p, add(mul(*x, u), mul(*y, v))),
            SurfFn::Cylinder(p, a, x, y, r) => add(add(*p, mul(*x, r * u.cos())), add(mul(*y, r * u.sin()), mul(*a, v))),
            SurfFn::Cone(p, a, x, y, r, tn) => add(add(*p, mul(*a, v)), mul(add(mul(*x, u.cos()), mul(*y, u.sin())), r + v * tn)),
            SurfFn::Sphere(c, a, x, y, r) => add(*c, add(mul(add(mul(*x, u.cos()), mul(*y, u.sin())), r * v.cos()), mul(*a, r * v.sin()))),
            SurfFn::Torus(c, a, x, y, ma, mi) => add(*c, add(mul(add(mul(*x, u.cos()), mul(*y, u.sin())), ma + mi * v.cos()), mul(*a, mi * v.sin()))),
            SurfFn::B(s) => s.at(u, v),
            SurfFn::Offset(base, d) => add(base.at(u, v), mul(fd_normal(base, u, v, 1e-6), *d)),
            SurfFn::Spun(prof, b, a) => {
                let q = sub(prof.at(v), *b);
                let along = mul(*a, dot(q, *a));
                let rad = sub(q, along);
                add(*b, add(along, add(mul(rad, u.cos()), mul(cross(*a, rad), u.sin()))))
            }
            SurfFn::Swept(sec, d) => add(sec.at(u), mul(*d, v)),
        }
    }
}

fn fd_normal(f: &SurfFn, u: f64, v: f64, h: f64) -> V {
    let p = f.at(u, v);
    unit(cross(sub(f.at(u + h, v), p), sub(f.at(u, v + h), p)))
}

pub type SDom = (Dom, Dom);

pub struct Converter<'a> {
    pub p: &'a Partition,
    pub warnings: Vec<String>,
    vertices: HashMap<i64, Rc<Vertex>>,
    edges: Vec<(i64, Rc<Edge>)>,
    edge_at: HashMap<i64, usize>,
    surf_eval: HashMap<i64, (Rc<SurfFn>, SDom)>,
    charts: HashMap<i64, Vec<V>>,
    grids: HashMap<i64, Vec<(f64, f64, V)>>,
    spines: HashMap<i64, Vec<V>>,
    depth: Cell<u32>,
}

fn sense_plus(n: &Node) -> bool {
    n.get("sense").map_or(true, |s| s.ch() != '-')
}

impl<'a> Converter<'a> {
    pub fn new(p: &'a Partition) -> Self {
        Converter {
            p,
            warnings: vec![],
            vertices: HashMap::new(),
            edges: vec![],
            edge_at: HashMap::new(),
            surf_eval: HashMap::new(),
            charts: HashMap::new(),
            grids: HashMap::new(),
            spines: HashMap::new(),
            depth: Cell::new(0),
        }
    }

    fn node(&self, idx: i64, what: &str) -> Result<&'a Node, GeomError> {
        self.p.get(idx).ok_or(GeomError(what.into()))
    }

    pub fn warn(&mut self, msg: String) {
        if !self.warnings.contains(&msg) && self.warnings.len() < 200 {
            self.warnings.push(msg);
        }
    }

    /// (point(u, v), domain) for a surface node; a domain side may be None (unbounded).
    pub fn surface_fn(&mut self, idx: i64) -> Result<(Rc<SurfFn>, SDom), GeomError> {
        if let Some(x) = self.surf_eval.get(&idx) {
            return Ok((x.0.clone(), x.1));
        }
        let n = self.node(idx, "missing surface")?;
        let tau = Some((0.0, 2.0 * PI));
        let (fnc, dom): (SurfFn, SDom) = match n.name.as_str() {
            "PLANE" => {
                let (p, nn, x) = (n.v("pvec"), n.v("normal"), n.v("x_axis"));
                (SurfFn::Plane(p, x, cross(nn, x)), (None, None))
            }
            "CYLINDER" => {
                let (p, a, x, r) = (n.v("pvec"), n.v("axis"), n.v("x_axis"), n.r("radius"));
                (SurfFn::Cylinder(p, a, x, cross(a, x), r), (tau, None))
            }
            "CONE" => {
                let (p, a, x, r) = (n.v("pvec"), n.v("axis"), n.v("x_axis"), n.r("radius"));
                let tn = div(n.r("sin_half_angle"), n.r("cos_half_angle"))?;
                (SurfFn::Cone(p, a, x, cross(a, x), r, tn), (tau, None))
            }
            "SPHERE" => {
                let (c, a, x, r) = (n.v("centre"), n.v("axis"), n.v("x_axis"), n.r("radius"));
                (SurfFn::Sphere(c, a, x, cross(a, x), r), (tau, Some((-PI / 2.0, PI / 2.0))))
            }
            "TORUS" => {
                let (c, a, x) = (n.v("centre"), n.v("axis"), n.v("x_axis"));
                (SurfFn::Torus(c, a, x, cross(a, x), n.r("major_radius"), n.r("minor_radius")), (tau, Some((-PI, PI))))
            }
            "B_SURFACE" => {
                let s = bsurface(self.p, n)?;
                let d = s.domain();
                (SurfFn::B(s), (Some(d.0), Some(d.1)))
            }
            "OFFSET_SURF" => {
                let (base, bdom) = self.surface_fn(n.p("surface"))?;
                let bnode = self.node(n.p("surface"), "missing surface")?;
                let sign = if bnode.get("sense").is_some_and(|s| s.ch() == '-') { -1.0 } else { 1.0 };
                (SurfFn::Offset(base, n.r("offset") * sign), bdom)
            }
            "SPUN_SURF" => {
                let (prof, pd) = self.curve_fn(n.p("profile"))?;
                (SurfFn::Spun(Rc::new(prof), n.v("base"), unit(n.v("axis"))), (tau, pd))
            }
            "SWEPT_SURF" => {
                let (sec, sd) = self.curve_fn(n.p("section"))?;
                (SurfFn::Swept(Rc::new(sec), unit(n.v("sweep"))), (sd, None))
            }
            t => return gerr(format!("surface type {t} not supported")),
        };
        let fnc = Rc::new(fnc);
        self.surf_eval.insert(idx, (fnc.clone(), dom));
        Ok((fnc, dom))
    }

    pub fn curve_fn(&mut self, idx: i64) -> Result<(CurveFn, Dom), GeomError> {
        let n = self.node(idx, "missing curve")?;
        let tau = Some((0.0, 2.0 * PI));
        Ok(match n.name.as_str() {
            "LINE" => (CurveFn::Line(n.v("pvec"), n.v("direction")), None),
            "CIRCLE" => {
                let (c, nn, x) = (n.v("centre"), n.v("normal"), n.v("x_axis"));
                (CurveFn::Circle(c, x, cross(nn, x), n.r("radius")), tau)
            }
            "ELLIPSE" => {
                let (c, nn, x) = (n.v("centre"), n.v("normal"), n.v("x_axis"));
                (CurveFn::Ellipse(c, x, cross(nn, x), n.r("major_radius"), n.r("minor_radius")), tau)
            }
            "B_CURVE" => {
                let c = bcurve(self.p, n)?;
                if c.pts[0].len() != 3 {
                    return gerr("2D B-curve used as a 3D curve");
                }
                let d = c.domain();
                (CurveFn::B(c), Some(d))
            }
            "TRIMMED_CURVE" => return self.curve_fn(n.p("basis_curve")),
            "SP_CURVE" => {
                let (sfn, _) = self.surface_fn(n.p("surface"))?;
                let c2 = bcurve(self.p, self.node(n.p("b_curve"), "missing curve")?)?;
                let d = c2.domain();
                (CurveFn::Sp(sfn, c2), Some(d))
            }
            "INTERSECTION" => {
                let pts = self.chart_points(n)?;
                if pts.len() <= 1 {
                    return gerr("empty intersection chart");
                }
                let c = interp(&pts)?;
                let d = c.domain();
                (CurveFn::B(c), Some(d))
            }
            t => return gerr(format!("curve type {t} not supported")),
        })
    }

    /// An intersection curve's chart, densified, every point put exactly on the curve.
    fn refined_chart(&mut self, idx: i64) -> Vec<V> {
        if let Some(c) = self.charts.get(&idx) {
            return c.clone();
        }
        let n = self.p.get(idx);
        let pts = n.map_or(Ok(vec![]), |n| self.chart_points(n)).unwrap_or_default();
        let out = self.refine(n, &pts).unwrap_or_else(|_| pts.clone());
        self.charts.insert(idx, out.clone());
        out
    }

    fn refine(&mut self, n: Option<&Node>, pts: &[V]) -> Result<Vec<V>, GeomError> {
        let n = n.ok_or(GeomError("no node".into()))?;
        if pts.len() < 2 {
            return Ok(pts.to_vec());
        }
        let mut dense = pts.to_vec();
        let closed = dist(pts[0], pts[pts.len() - 1]) < 1e-9;
        while dense.len() < 33 && !closed {
            let c = interp(&dense)?;
            let (lo, hi) = c.domain();
            let k = 2 * (dense.len() - 1);
            dense = (0..=k).map(|i| v3(&c.at(lo + (hi - lo) * i as f64 / k as f64))).collect();
        }
        let step = dense.windows(2).map(|w| dist(w[0], w[1])).fold(f64::NEG_INFINITY, f64::max);
        let s = n.get("surface").map(|f| f.list().to_vec()).unwrap_or_default();
        if s.len() < 2 {
            return gerr("intersection without two surfaces");
        }
        let (s0, s1) = (s[0].ptr(), s[1].ptr());
        let (n0, n1) = (self.p.get(s0), self.p.get(s1));
        let bb = if n0.is_some_and(|x| x.name == "BLEND_BOUND") { n0 } else if n1.is_some_and(|x| x.name == "BLEND_BOUND") { n1 } else { None };
        let mut fixed = Vec::new();
        for q in dense {
            let q2 = if let Some(bb) = bb {
                let blend = self.node(bb.p("blend"), "no blend")?;
                let c = self.spine_point(blend.index, q)?;
                let mut cands = Vec::new();
                for si in blend.get("surface").map(|f| f.list().to_vec()).unwrap_or_default() {
                    cands.push(self.foot(si.ptr(), c, 0)?.0);
                }
                *cands.iter().min_by(|a, b| dist(**a, q).total_cmp(&dist(**b, q))).ok_or(GeomError("no supports".into()))?
            } else {
                self.solve_two(q, s0, 0.0, s1, 0.0, 12)?
            };
            fixed.push(if dist(q, q2) <= step { q2 } else { q });
        }
        Ok(fixed)
    }

    fn chart_points(&self, n: &Node) -> Result<Vec<V>, GeomError> {
        let ch = self.p.get(n.p("chart")).ok_or(GeomError("intersection without chart".into()))?;
        Ok(ch.get("hvec").map_or(vec![], |f| f.list().iter().map(F::v3).collect()))
    }

    /// Closest point on a surface: (foot, natural unit normal at the foot).
    pub fn foot(&mut self, idx: i64, p: V, depth: u32) -> Result<(V, V), GeomError> {
        let n = match self.p.get(idx) {
            Some(n) if depth <= 6 => n,
            _ => return gerr("no surface to project onto"),
        };
        match n.name.as_str() {
            "PLANE" => {
                let nn = unit(n.v("normal"));
                Ok((sub(p, mul(nn, dot(sub(p, n.v("pvec")), nn))), nn))
            }
            "CYLINDER" => {
                let a = unit(n.v("axis"));
                let q = sub(p, n.v("pvec"));
                let h = dot(q, a);
                let r = unit(sub(q, mul(a, h)));
                Ok((add(n.v("pvec"), add(mul(a, h), mul(r, n.r("radius")))), r))
            }
            "CONE" => {
                let a = unit(n.v("axis"));
                let (ca, sa) = (n.r("cos_half_angle"), n.r("sin_half_angle"));
                let q = sub(p, n.v("pvec"));
                let h = dot(q, a);
                let radial = sub(q, mul(a, h));
                let rho = norm(radial);
                let r = unit(radial);
                let d = (rho - n.r("radius") - h * div(sa, ca)?) * ca;
                let (h2, rho2) = (h + d * sa, rho - d * ca);
                Ok((add(n.v("pvec"), add(mul(a, h2), mul(r, rho2))), unit(sub(mul(r, ca), mul(a, sa)))))
            }
            "SPHERE" => {
                let r = unit(sub(p, n.v("centre")));
                Ok((add(n.v("centre"), mul(r, n.r("radius"))), r))
            }
            "TORUS" => {
                let a = unit(n.v("axis"));
                let q = sub(p, n.v("centre"));
                let h = dot(q, a);
                let r = unit(sub(q, mul(a, h)));
                let c = add(n.v("centre"), mul(r, n.r("major_radius")));
                let nn = unit(sub(p, c));
                Ok((add(c, mul(nn, n.r("minor_radius"))), nn))
            }
            "OFFSET_SURF" => {
                let base = self.node(n.p("surface"), "missing surface")?;
                let sign = if base.get("sense").is_some_and(|s| s.ch() == '-') { -1.0 } else { 1.0 };
                let d = n.r("offset") * sign;
                let (fb, nb) = self.foot(n.p("surface"), p, depth + 1)?;
                Ok((add(fb, mul(nb, d)), nb))
            }
            "BLENDED_EDGE" => {
                let c = self.spine_point(idx, p)?;
                let nn = unit(sub(p, c));
                Ok((add(c, mul(nn, self.blend_radius(n))), nn))
            }
            "BLEND_BOUND" => {
                let blend = self.node(n.p("blend"), "no blend")?;
                let s = blend.get("surface").map(|f| f.list().to_vec()).unwrap_or_default();
                let k = 1 - n.i("boundary");
                let si = s.get(k as usize).ok_or(GeomError("blend bound".into()))?.ptr();
                self.foot(si, p, depth + 1)
            }
            "B_SURFACE" | "SWEPT_SURF" | "SPUN_SURF" => self.foot_numeric(idx, p),
            t => gerr(format!("cannot project onto {t}")),
        }
    }

    fn foot_numeric(&mut self, idx: i64, p: V) -> Result<(V, V), GeomError> {
        let (f, dom) = self.surface_fn(idx)?;
        let ((u0, u1), (v0, v1)) = match dom {
            (Some(a), Some(b)) => (a, b),
            _ => return gerr("cannot project onto an unbounded swept surface"),
        };
        if !self.grids.contains_key(&idx) {
            let m = 14;
            let mut g = Vec::new();
            for i in 0..=m {
                for j in 0..=m {
                    let (u, v) = (u0 + (u1 - u0) * i as f64 / m as f64, v0 + (v1 - v0) * j as f64 / m as f64);
                    g.push((u, v, f.at(u, v)));
                }
            }
            self.grids.insert(idx, g);
        }
        let g = &self.grids[&idx];
        let d2 = |q: &V| (q[0] - p[0]).powi(2) + (q[1] - p[1]).powi(2) + (q[2] - p[2]).powi(2);
        let best = g.iter().fold(None::<&(f64, f64, V)>, |b, x| match b {
            Some(bb) if d2(&bb.2) <= d2(&x.2) => Some(bb),
            _ => Some(x),
        });
        let (mut u, mut v, _) = *best.unwrap();
        let (hu, hv) = ((u1 - u0) * 1e-6, (v1 - v0) * 1e-6);
        let tangents = |u: f64, v: f64| -> Result<(V, V), GeomError> {
            let (ua, ub) = ((u - hu).max(u0), (u + hu).min(u1));
            let (va, vb) = ((v - hv).max(v0), (v + hv).min(v1));
            Ok((mul(sub(f.at(ub, v), f.at(ua, v)), div(1.0, ub - ua)?), mul(sub(f.at(u, vb), f.at(u, va)), div(1.0, vb - va)?)))
        };
        let ext = |u: f64, v: f64| -> Result<(V, Option<(V, V)>), GeomError> {
            let (uc, vc) = (u.max(u0).min(u1), v.max(v0).min(v1));
            let q = f.at(uc, vc);
            if uc == u && vc == v {
                return Ok((q, None));
            }
            let (su, sv) = tangents(uc, vc)?;
            Ok((add(q, add(mul(su, u - uc), mul(sv, v - vc))), Some((su, sv))))
        };
        let (lim_u, lim_v) = (0.5 * (u1 - u0), 0.5 * (v1 - v0));
        for _ in 0..30 {
            let (q, t) = ext(u, v)?;
            let (su, sv) = match t {
                Some(t) => t,
                None => tangents(u, v)?,
            };
            let r = sub(p, q);
            let (a, b, c) = (dot(su, su), dot(su, sv), dot(sv, sv));
            let det = a * c - b * b;
            if det.abs() < 1e-300 {
                break;
            }
            let du = (c * dot(r, su) - b * dot(r, sv)) / det;
            let dv = (a * dot(r, sv) - b * dot(r, su)) / det;
            u = (u + du).max(u0 - lim_u).min(u1 + lim_u);
            v = (v + dv).max(v0 - lim_v).min(v1 + lim_v);
            if du.abs() < (u1 - u0) * 1e-13 && dv.abs() < (v1 - v0) * 1e-13 {
                break;
            }
        }
        let (q, t) = ext(u, v)?;
        let (su, sv) = match t {
            Some(t) => t,
            None => tangents(u, v)?,
        };
        Ok((q, unit(cross(su, sv))))
    }

    fn blend_radius(&self, n: &Node) -> f64 {
        let r = n.get("range").and_then(|f| f.list().first().map(F::real)).unwrap_or(f64::NAN);
        if !is_null(r) { r.abs() } else { 0.0 }
    }

    fn range(&self, n: &Node, i: usize) -> f64 {
        n.get("range").and_then(|f| f.list().get(i).map(F::real)).unwrap_or(f64::NAN)
    }

    fn surfaces(n: &Node) -> Result<(i64, i64), GeomError> {
        let s = n.get("surface").map(|f| f.list().to_vec()).unwrap_or_default();
        if s.len() < 2 {
            return gerr("blend without two surfaces");
        }
        Ok((s[0].ptr(), s[1].ptr()))
    }

    /// Signed distances of the spine from the two supporting surfaces.
    fn blend_targets(&self, n: &Node) -> Result<(f64, f64), GeomError> {
        let (a, b) = Self::surfaces(n)?;
        let mut out = [0.0; 2];
        for (i, si) in [a, b].iter().enumerate() {
            let s = self.p.get(*si);
            let sign = if s.is_some_and(|s| s.get("sense").is_some_and(|x| x.ch() == '-')) { -1.0 } else { 1.0 };
            out[i] = if s.is_some_and(|s| s.name == "BLENDED_EDGE" && self.blend_radius(s) == 0.0) {
                self.range(n, i).abs() // distance from a cliff edge has no sign
            } else {
                self.range(n, i) * sign
            };
        }
        Ok((out[0], out[1]))
    }

    /// Move p (the least distance) so that its signed distance from s0 is d0 and from s1 is d1.
    fn solve_two(&mut self, mut p: V, s0: i64, d0: f64, s1: i64, d1: f64, iters: usize) -> Result<V, GeomError> {
        for _ in 0..iters {
            let (f0, n0) = self.foot(s0, p, 0)?;
            let (f1, n1) = self.foot(s1, p, 0)?;
            let e0 = d0 - dot(sub(p, f0), n0);
            let e1 = d1 - dot(sub(p, f1), n1);
            if e0.abs() < 1e-13 && e1.abs() < 1e-13 {
                break;
            }
            let g = dot(n0, n1);
            let det = 1.0 - g * g;
            if det < 1e-10 {
                p = add(p, mul(n0, e0));
                break;
            }
            let a = (e0 - g * e1) / det;
            let b = (e1 - g * e0) / det;
            p = add(p, add(mul(n0, a), mul(n1, b)));
        }
        Ok(p)
    }

    /// Dense points on a blend's spine, exactly at the blend's offsets from its supports.
    fn spine_polyline(&mut self, idx: i64) -> Result<Vec<V>, GeomError> {
        if let Some(s) = self.spines.get(&idx) {
            return Ok(s.clone());
        }
        let n = self.node(idx, "missing blend")?;
        let spine = self.p.get(n.p("spine")).ok_or(GeomError("blend without spine".into()))?;
        let mut pts = if spine.name == "INTERSECTION" {
            self.chart_points(spine)?
        } else {
            let (cfn, dom) = self.curve_fn(n.p("spine"))?;
            let (a, b) = dom.ok_or(GeomError("unbounded spine".into()))?;
            (0..49).map(|i| cfn.at(a + (b - a) * i as f64 / 48.0)).collect()
        };
        self.spines.insert(idx, pts.clone()); // guards against a blend that supports itself
        if self.blend_radius(n) == 0.0 {
            return Ok(pts);
        }
        let (s0, s1) = Self::surfaces(n)?;
        let (d0, d1) = self.blend_targets(n)?;
        let got = (|| -> Result<Vec<V>, GeomError> {
            while 2 <= pts.len() && pts.len() < 49 {
                let c = interp(&pts)?;
                let (lo, hi) = c.domain();
                let k = 2 * (pts.len() - 1);
                pts = (0..=k).map(|i| v3(&c.at(lo + (hi - lo) * i as f64 / k as f64))).collect();
            }
            let mut out = Vec::new();
            for q in &pts {
                out.push(self.solve_two(*q, s0, d0, s1, d1, 30)?);
            }
            Ok(out)
        })();
        let pts = got.unwrap_or_else(|_| self.spines[&idx].clone());
        self.spines.insert(idx, pts.clone());
        Ok(pts)
    }

    /// The spine point whose cross-section circle passes nearest p.
    fn spine_point(&mut self, idx: i64, p: V) -> Result<V, GeomError> {
        let n = self.node(idx, "missing blend")?;
        let mut sp = self.p.get(n.p("spine"));
        while let Some(s) = sp.filter(|s| s.name == "TRIMMED_CURVE") {
            sp = self.p.get(s.p("basis_curve"));
        }
        if let Some(s) = sp {
            if s.name == "LINE" {
                let d = unit(s.v("direction"));
                return Ok(add(s.v("pvec"), mul(d, dot(sub(p, s.v("pvec")), d))));
            }
            if s.name == "CIRCLE" {
                let nn = unit(s.v("normal"));
                let q = sub(p, s.v("centre"));
                let radial = sub(q, mul(nn, dot(q, nn)));
                if norm(radial) > 1e-12 {
                    return Ok(add(s.v("centre"), mul(unit(radial), s.r("radius"))));
                }
            }
        }
        let pts = self.spine_polyline(idx)?;
        let (s, _) = project_param(&pts, p);
        let mut q = at(&pts, s);
        if self.depth.get() < 3 && self.blend_radius(n) > 0.0 {
            self.depth.set(self.depth.get() + 1);
            let got = (|| -> Result<V, GeomError> {
                let (s0, s1) = Self::surfaces(n)?;
                let (d0, d1) = self.blend_targets(n)?;
                self.solve_two(q, s0, d0, s1, d1, 6)
            })();
            if let Ok(q2) = got {
                let span = if pts.len() > 1 { dist(pts[0], pts[1]) } else { 0.0 };
                if dist(q, q2) <= span.max(1e-9) {
                    q = q2;
                }
            }
            self.depth.set(self.depth.get() - 1);
        }
        Ok(q)
    }

    fn line_spine(sp: &Node, bpts: &[V]) -> Vec<V> {
        let d = unit(sp.v("direction"));
        let ts: Vec<f64> = bpts.iter().map(|q| dot(sub(*q, sp.v("pvec")), d)).collect();
        let lo = ts.iter().copied().fold(f64::INFINITY, f64::min);
        let hi = ts.iter().copied().fold(f64::NEG_INFINITY, f64::max);
        let pad = 0.05 * (hi - lo) + 1e-6;
        (0..9).map(|i| add(sp.v("pvec"), mul(d, lo - pad + (hi - lo + 2.0 * pad) * i as f64 / 8.0))).collect()
    }

    /// (curve spec, same_sense, approx) for an edge running start -> end.
    fn edge_curve(&mut self, cidx: i64, start: Option<V>, end: Option<V>) -> Result<(CurveSpec, bool, bool), GeomError> {
        let n = self.node(cidx, "edge without curve")?;
        let sense = sense_plus(n);
        match n.name.as_str() {
            "TRIMMED_CURVE" => {
                let basis = self.node(n.p("basis_curve"), "missing curve")?;
                let bsense = sense_plus(basis);
                let (spec, ss, approx) = self.edge_curve(n.p("basis_curve"), start, end)?;
                if approx {
                    return Ok((spec, ss, approx));
                }
                return Ok((spec, sense == bsense, false));
            }
            "LINE" => return Ok((CurveSpec::Line(n.v("pvec"), unit(n.v("direction"))), sense, false)),
            "CIRCLE" => return Ok((CurveSpec::Circle(n.v("centre"), unit(n.v("normal")), unit(n.v("x_axis")), n.r("radius")), sense, false)),
            "ELLIPSE" => {
                return Ok((CurveSpec::Ellipse(n.v("centre"), unit(n.v("normal")), unit(n.v("x_axis")), n.r("major_radius"), n.r("minor_radius")), sense, false))
            }
            "B_CURVE" => {
                let c = bcurve(self.p, n)?;
                if c.pts[0].len() == 3 {
                    return Ok((CurveSpec::BSpline(c), sense, false));
                }
            }
            _ => {}
        }
        // approximate: a dense polyline in the curve's own direction, then cut to the edge
        let mut pts: Vec<V> = if n.name == "INTERSECTION" {
            self.refined_chart(cidx)
        } else {
            let (f, dom) = self.curve_fn(cidx)?;
            let (a, b) = dom.ok_or(GeomError(format!("unbounded {}", n.name)))?;
            (0..=64).map(|i| f.at(a + (b - a) * i as f64 / 64.0)).collect()
        };
        if !sense {
            pts.reverse();
        }
        Ok((CurveSpec::BSpline(fit_between(&pts, start, end)?), true, true))
    }

    /// (spec, flip, approx): flip when the STEP surface's normal is the opposite of the
    /// Parasolid surface's natural normal (None for a blend, oriented later).
    fn face_surface(&mut self, idx: i64, loops: &[Loop]) -> Result<(SurfSpec, Option<bool>, bool), GeomError> {
        let n = self.node(idx, "face without surface")?;
        Ok(match n.name.as_str() {
            "PLANE" => (SurfSpec::Plane(n.v("pvec"), unit(n.v("normal")), unit(n.v("x_axis"))), Some(false), false),
            "CYLINDER" => (SurfSpec::Cylinder(n.v("pvec"), unit(n.v("axis")), unit(n.v("x_axis")), n.r("radius")), Some(false), false),
            "CONE" => {
                let semi = n.r("sin_half_angle").atan2(n.r("cos_half_angle"));
                (SurfSpec::Cone(n.v("pvec"), unit(n.v("axis")), unit(n.v("x_axis")), n.r("radius"), semi), Some(false), false)
            }
            "SPHERE" => (SurfSpec::Sphere(n.v("centre"), unit(n.v("axis")), unit(n.v("x_axis")), n.r("radius")), Some(false), false),
            "TORUS" => {
                if n.r("major_radius") <= n.r("minor_radius") {
                    (self.sampled(idx, loops)?, Some(false), true)
                } else {
                    (SurfSpec::Torus(n.v("centre"), unit(n.v("axis")), unit(n.v("x_axis")), n.r("major_radius"), n.r("minor_radius")), Some(false), false)
                }
            }
            "B_SURFACE" => (SurfSpec::BSpline(bsurface(self.p, n)?), Some(false), false),
            "OFFSET_SURF" => {
                let base = self.p.get(n.p("surface"));
                if base.is_some_and(|b| b.name == "BLENDED_EDGE") {
                    // an offset rolling-ball blend is a rolling-ball blend about the same spine
                    return Ok((SurfSpec::Blend(n.p("surface")), None, true));
                }
                if let Some(e) = self.offset_exact(n) {
                    return Ok(e);
                }
                (self.sampled(idx, loops)?, Some(false), true)
            }
            "SPUN_SURF" | "SWEPT_SURF" => (self.sampled(idx, loops)?, Some(false), true),
            "BLENDED_EDGE" => (SurfSpec::Blend(idx), None, true),
            t => return gerr(format!("surface type {t} not supported")),
        })
    }

    fn offset_exact(&self, n: &Node) -> Option<(SurfSpec, Option<bool>, bool)> {
        let b = self.p.get(n.p("surface"))?;
        let sign = if b.get("sense").is_some_and(|s| s.ch() == '-') { -1.0 } else { 1.0 };
        let d = n.r("offset") * sign;
        let ok = |s: SurfSpec| Some((s, Some(false), false));
        match b.name.as_str() {
            "PLANE" => {
                let nn = unit(b.v("normal"));
                ok(SurfSpec::Plane(add(b.v("pvec"), mul(nn, d)), nn, unit(b.v("x_axis"))))
            }
            "CYLINDER" if b.r("radius") + d > 1e-9 => ok(SurfSpec::Cylinder(b.v("pvec"), unit(b.v("axis")), unit(b.v("x_axis")), b.r("radius") + d)),
            "SPHERE" if b.r("radius") + d > 1e-9 => ok(SurfSpec::Sphere(b.v("centre"), unit(b.v("axis")), unit(b.v("x_axis")), b.r("radius") + d)),
            "TORUS" if b.r("minor_radius") + d > 1e-9 && b.r("major_radius") > b.r("minor_radius") + d => {
                ok(SurfSpec::Torus(b.v("centre"), unit(b.v("axis")), unit(b.v("x_axis")), b.r("major_radius"), b.r("minor_radius") + d))
            }
            "CONE" => {
                let (ca, sa) = (b.r("cos_half_angle"), b.r("sin_half_angle"));
                if ca == 0.0 {
                    return None; // (the Python raises here, and the face is left out)
                }
                let r = b.r("radius") + d / ca;
                if r > 1e-9 {
                    ok(SurfSpec::Cone(b.v("pvec"), unit(b.v("axis")), unit(b.v("x_axis")), r, sa.atan2(ca)))
                } else {
                    None
                }
            }
            _ => None,
        }
    }

    fn sampled(&mut self, idx: i64, loops: &[Loop]) -> Result<SurfSpec, GeomError> {
        let (f, dom) = self.surface_fn(idx)?;
        let node = self.node(idx, "missing surface")?;
        let (du, mut dv) = dom;
        if du.is_none() && dv.is_none() {
            return gerr(format!("unbounded {} surface", node.name));
        }
        if dv.is_none() && node.name == "SWEPT_SURF" && !loops.is_empty() {
            if let Some(du) = du {
                let d = unit(node.v("sweep"));
                let pts: Vec<V> = loops.iter().flat_map(|lp| lp.edges.iter().flat_map(|(e, _)| edge_samples(e, 8))).collect();
                let sec: Vec<f64> = (0..33).map(|i| dot(f.at(du.0 + (du.1 - du.0) * i as f64 / 32.0, 0.0), d)).collect();
                let mx = |v: &mut dyn Iterator<Item = f64>| v.fold(f64::NEG_INFINITY, f64::max);
                let mn = |v: &mut dyn Iterator<Item = f64>| v.fold(f64::INFINITY, f64::min);
                if pts.is_empty() {
                    return gerr("min() arg is an empty sequence");
                }
                let lo = mn(&mut pts.iter().map(|p| dot(*p, d))) - mx(&mut sec.iter().copied());
                let hi = mx(&mut pts.iter().map(|p| dot(*p, d))) - mn(&mut sec.iter().copied());
                let pad = 0.05 * (hi - lo) + 1e-6;
                dv = Some((lo - pad, hi + pad));
            }
        }
        let (Some(du), Some(dv)) = (du, dv) else { return gerr(format!("unbounded {} surface", node.name)) };
        Ok(SurfSpec::BSpline(sample_surface(&f, du, dv, 24, 24)?))
    }

    fn vertex(&mut self, idx: i64) -> Result<Option<Rc<Vertex>>, GeomError> {
        if idx == 0 {
            return Ok(None);
        }
        if let Some(v) = self.vertices.get(&idx) {
            return Ok(Some(v.clone()));
        }
        let vn = self.p.get(idx);
        let pt = vn.and_then(|v| self.p.get(v.p("point"))).ok_or(GeomError("vertex without point".into()))?;
        let v = Rc::new(Vertex { id: new_id(), point: pt.v("pvec") });
        self.vertices.insert(idx, v.clone());
        Ok(Some(v))
    }

    fn edge(&mut self, idx: i64) -> Result<Rc<Edge>, GeomError> {
        if let Some(&i) = self.edge_at.get(&idx) {
            return Ok(self.edges[i].1.clone());
        }
        let en = self.node(idx, "missing edge")?;
        let fin = self.p.get(en.p("fin")).ok_or(GeomError("edge without fin".into()))?;
        let other = self.p.get(fin.p("other"));
        // edge->fin is a positive fin: its vertex ends the edge; the next fin's vertex starts it
        let end = self.vertex(fin.p("vertex"))?;
        let start = match other {
            Some(o) => self.vertex(o.p("vertex"))?,
            None => end.clone(),
        };
        let mut cidx = en.p("curve");
        if cidx == 0 {
            // tolerant edge: use the SP-curve of a fin
            let (mut f2, mut guard) = (Some(fin), 0);
            while let Some(f) = f2.filter(|f| f.p("curve") == 0) {
                if guard >= 64 {
                    break;
                }
                f2 = self.p.get(f.p("other"));
                guard += 1;
            }
            cidx = f2.map_or(0, |f| f.p("curve"));
            if cidx == 0 {
                return gerr("edge without curve");
            }
        }
        let (mut spec, ss, approx) = self.edge_curve(cidx, start.as_ref().map(|v| v.point), end.as_ref().map(|v| v.point))?;
        if let (CurveSpec::BSpline(c), false, Some(s), Some(e)) = (&spec, approx, &start, &end) {
            spec = CurveSpec::BSpline(trim_to_edge(c, s.point, e.point, ss));
        }
        let (start, end) = if start.is_none() && end.is_none() {
            // ring edge: STEP needs a vertex, on a face of revolution at that surface's seam
            let v = Rc::new(Vertex { id: new_id(), point: self.ring_vertex_point(en, &spec) });
            (Some(v.clone()), Some(v))
        } else {
            (start, end)
        };
        let e = Rc::new(Edge { id: new_id(), start, end, curve: spec, same_sense: ss, approx });
        self.edge_at.insert(idx, self.edges.len());
        self.edges.push((idx, e.clone()));
        Ok(e)
    }

    fn ring_vertex_point(&self, en: &Node, spec: &CurveSpec) -> V {
        let (c, nn, xe, a, b, is_circle) = match spec {
            CurveSpec::Circle(c, n, x, r) => (*c, *n, *x, *r, *r, true),
            CurveSpec::Ellipse(c, n, x, a, b) => (*c, *n, *x, *a, *b, false),
            _ => return curve_point(spec),
        };
        let (mut fin, mut guard) = (self.p.get(en.p("fin")), 0);
        while let Some(f) = fin {
            if guard >= 16 {
                break;
            }
            if let Some(lp) = self.p.get(f.p("loop")) {
                let sn = self.p.get(lp.p("face")).and_then(|fc| self.p.get(fc.p("surface")));
                if let Some(sn) = sn.filter(|s| ["CYLINDER", "CONE", "SPHERE", "TORUS"].contains(&s.name.as_str())) {
                    let x = sn.v("x_axis");
                    let xp = sub(x, mul(nn, dot(x, nn)));
                    if norm(xp) > 1e-9 {
                        let xp = unit(xp);
                        if is_circle {
                            return add(c, mul(xp, a));
                        }
                        let ye = cross(nn, xe);
                        let ang = dot(xp, ye).atan2(dot(xp, xe));
                        return add(c, add(mul(xe, a * ang.cos()), mul(ye, b * ang.sin())));
                    }
                }
            }
            fin = self.p.get(f.p("other"));
            guard += 1;
        }
        curve_point(spec)
    }

    fn lp(&mut self, idx: i64) -> Result<Loop, GeomError> {
        let ln = self.node(idx, "missing loop")?;
        let first = ln.p("fin");
        if let Some(fnode) = self.p.get(first) {
            if fnode.p("edge") == 0 {
                return Ok(Loop { edges: vec![], vertex: self.vertex(fnode.p("vertex"))? });
            }
        }
        let (mut out, mut cur, mut guard) = (Vec::new(), first, 0);
        loop {
            let f = self.p.get(cur).ok_or(GeomError("broken fin ring".into()))?;
            out.push((self.edge(f.p("edge"))?, f.c("sense") != '-'));
            cur = f.p("forward");
            guard += 1;
            if cur == first || cur == 0 || guard > 100000 {
                break;
            }
        }
        Ok(Loop { edges: out, vertex: None })
    }

    fn face(&mut self, idx: i64) -> Result<Face, GeomError> {
        let fnode = self.node(idx, "missing face")?;
        let sidx = fnode.p("surface");
        let snode = self.p.get(sidx).ok_or(GeomError("face without surface".into()))?;
        let mut loops = Vec::new();
        let (mut li, mut guard) = (fnode.p("loop"), 0);
        while li != 0 && guard < 100000 {
            loops.push(self.lp(li)?);
            li = self.node(li, "missing loop")?.p("next");
            guard += 1;
        }
        let (spec, flip, approx) = self.face_surface(sidx, &loops)?;
        let natural = (fnode.c("sense") != '-') == sense_plus(snode);
        if let SurfSpec::Blend(b) = spec {
            let bn = self.node(b, "missing blend")?;
            let s = self.blend_surface(bn, &loops)?;
            let spec = SurfSpec::BSpline(s);
            let same = self.orient_by_neighbours(&spec, &loops, idx);
            return Ok(Face { surface: spec, same_sense: same, loops, approx: true, source: snode.name.clone() });
        }
        Ok(Face { surface: spec, same_sense: natural != flip.unwrap_or(false), loops, approx, source: snode.name.clone() })
    }

    fn blend_surface(&mut self, sn: &Node, loops: &[Loop]) -> Result<Surface, GeomError> {
        match self.blend_surface_exact(sn, loops) {
            Ok(s) => Ok(s),
            Err(e) => {
                let id = sn.i("node_id");
                self.warn(format!("fillet {id}: exact construction failed ({}); fitted instead", e.0));
                self.blend_surface_fit(sn, loops)
            }
        }
    }

    /// Rolling-ball blend: for each spine point C, the arc of radius r about C from its foot on
    /// one supporting surface to its foot on the other.
    fn blend_surface_exact(&mut self, sn: &Node, loops: &[Loop]) -> Result<Surface, GeomError> {
        let idx = sn.index;
        let r = self.blend_radius(sn);
        if r <= 0.0 {
            return gerr("no radius");
        }
        let bpts: Vec<V> = loops.iter().flat_map(|lp| lp.edges.iter().flat_map(|(e, _)| edge_samples(e, 9))).collect();
        if bpts.len() < 3 {
            return gerr("no boundary");
        }
        let sp = self.p.get(sn.p("spine"));
        let spine = match sp {
            Some(s) if s.name == "LINE" => Self::line_spine(s, &bpts),
            _ => self.spine_polyline(idx)?,
        };
        if spine.len() < 2 {
            return gerr("no spine");
        }
        let mut gaps: Vec<f64> = bpts.iter().map(|q| project_param(&spine, *q).1).collect();
        gaps.sort_by(f64::total_cmp);
        let mut r_face = gaps[gaps.len() / 2];
        if (r_face - r).abs() > 0.02 * r {
            if r_face <= 0.0 {
                return gerr("face lies on the spine");
            }
        } else {
            r_face = r;
        }
        let params: Vec<f64> = bpts.iter().map(|q| project_param(&spine, *q).0).collect();
        let n_seg = (spine.len() - 1) as f64;
        let closed = dist(spine[0], spine[spine.len() - 1]) < 1e-9;
        let mut lo = params.iter().copied().fold(f64::INFINITY, f64::min);
        let mut hi = params.iter().copied().fold(f64::NEG_INFINITY, f64::max);
        let whole = if closed && hi - lo > 0.9 * n_seg {
            lo = 0.0;
            hi = n_seg;
            true
        } else {
            let pad = 0.03 * (hi - lo) + 0.25;
            lo = (lo - pad).max(0.0);
            hi = (hi + pad).min(n_seg);
            false
        };
        if hi - lo < 1e-9 {
            return gerr("face covers no spine");
        }
        let (s0, s1) = Self::surfaces(sn)?;
        let (d0, d1) = self.blend_targets(sn)?;
        let (rows_n, cols_n) = (49usize, 25usize);
        let mut rows = Vec::new();
        for i in 0..rows_n {
            let c = at(&spine, lo + (hi - lo) * i as f64 / (rows_n - 1) as f64);
            let c = self.solve_two(c, s0, d0, s1, d1, 12)?;
            let (f0, _) = self.foot(s0, c, 0)?;
            let (f1, _) = self.foot(s1, c, 0)?;
            if (dist(f0, c) - r).abs() > 1e-4 * r || (dist(f1, c) - r).abs() > 1e-4 * r {
                return gerr("supports are not at the blend radius from the spine");
            }
            let (a, b) = (unit(sub(f0, c)), unit(sub(f1, c)));
            let mut ang = dot(a, b).clamp(-1.0, 1.0).acos();
            let ta = at(&spine, lo + (hi - lo) * i.saturating_sub(1) as f64 / (rows_n - 1) as f64);
            let tb = at(&spine, lo + (hi - lo) * (i + 1).min(rows_n - 1) as f64 / (rows_n - 1) as f64);
            let tdir = unit(sub(tb, ta));
            if ang < 1e-7 {
                // the feet one point: the ball fills both supports (a pipe of the blend's radius bent
                // round a corner): the tube of that radius round the spine (see the Python)
                let mut g: V = match sp {
                    Some(s) if s.get("normal").is_some() => s.v("normal"),
                    _ => [0.0, 0.0, 1.0],
                };
                if dot(g, tdir).abs() > 0.999 {
                    g = if tdir[0].abs() < 0.9 { [1.0, 0.0, 0.0] } else { [0.0, 1.0, 0.0] };
                }
                let u1 = unit(sub(g, mul(tdir, dot(g, tdir))));
                let u2 = cross(tdir, u1);
                rows.push(
                    (0..cols_n)
                        .map(|k| {
                            let t = 2.0 * PI * k as f64 / (cols_n - 1) as f64;
                            add(c, mul(add(mul(u1, t.cos()), mul(u2, t.sin())), r_face))
                        })
                        .collect::<Vec<V>>(),
                );
                continue;
            }
            let bperp = if ang > PI - 1e-7 {
                // the feet opposite each other (a full round between parallel faces): the half
                // circle square to the spine, on the side the face's own boundary is (see the Python)
                let yv = unit(cross(tdir, a));
                let near = |p: V| bpts.iter().map(|q| dist(p, *q)).fold(f64::INFINITY, f64::min);
                let (up, down) = (near(add(c, mul(yv, r_face))), near(add(c, mul(yv, -r_face))));
                ang = PI;
                if up <= down { yv } else { mul(yv, -1.0) }
            } else {
                unit(sub(b, mul(a, dot(a, b))))
            };
            let ext = 0.04 * ang;
            rows.push(
                (0..cols_n)
                    .map(|k| {
                        let t = -ext + (ang + 2.0 * ext) * k as f64 / (cols_n - 1) as f64;
                        add(c, mul(add(mul(a, t.cos()), mul(bperp, t.sin())), r_face))
                    })
                    .collect::<Vec<V>>(),
            );
        }
        if !whole {
            rows = extend_rows(rows, 0.02);
        }
        Ok(nurbs::interpolate_grid(&rows, 3)?)
    }

    fn blend_surface_fit(&mut self, sn: &Node, loops: &[Loop]) -> Result<Surface, GeomError> {
        let r0 = self.range(sn, 0);
        let mut r = if !is_null(r0) { r0.abs() } else { 0.0 };
        let spine_idx = sn.p("spine");
        let spine = self.p.get(spine_idx).ok_or(GeomError("blend without spine".into()))?;
        let centres = if spine.name == "INTERSECTION" {
            self.chart_points(spine)?
        } else {
            let (cfn, dom) = self.curve_fn(spine_idx)?;
            let dom = match dom {
                Some(d) => d,
                None => {
                    // limit to the face's extent along a line spine
                    let pts: Vec<V> = loops.iter().flat_map(|lp| lp.edges.iter().filter_map(|(e, _)| e.start.as_ref().map(|s| s.point))).collect();
                    let p0 = cfn.at(0.0);
                    let d = sub(cfn.at(1.0), p0);
                    let mut ts = Vec::new();
                    for p in &pts {
                        ts.push(div(dot(sub(*p, p0), d), dot(d, d))?);
                    }
                    if ts.is_empty() {
                        ts = vec![0.0, 1.0];
                    }
                    (ts.iter().copied().fold(f64::INFINITY, f64::min), ts.iter().copied().fold(f64::NEG_INFINITY, f64::max))
                }
            };
            (0..33).map(|i| cfn.at(dom.0 + (dom.1 - dom.0) * i as f64 / 32.0)).collect()
        };
        let centres = resample(&centres, 48);
        let bpts: Vec<V> = loops.iter().flat_map(|lp| lp.edges.iter().flat_map(|(e, _)| edge_samples(e, 12))).collect();
        if bpts.len() < 4 {
            return gerr("blend face without boundary");
        }
        let stride = 1.max(centres.len() / 12);
        let mut dists: Vec<f64> = centres.iter().step_by(stride).map(|c| bpts.iter().map(|p| dist(*c, *p)).fold(f64::INFINITY, f64::min)).collect();
        dists.sort_by(f64::total_cmp);
        let measured = if dists.is_empty() { r } else { dists[dists.len() / 2] };
        if r <= 0.0 || (measured - r).abs() > 0.02 * r {
            r = measured;
        }
        if r <= 0.0 {
            return gerr("blend radius is zero");
        }
        let mut rows = Vec::new();
        for c in &centres {
            let mut near: Vec<V> = bpts.iter().copied().filter(|p| (dist(*p, *c) - r).abs() < (0.02 * r).max(1e-7)).collect();
            if near.len() < 2 {
                let mut s = bpts.clone();
                s.sort_by(|a, b| (dist(*a, *c) - r).abs().total_cmp(&(dist(*b, *c) - r).abs()));
                near = s.into_iter().take(6).collect();
            }
            let dirs: Vec<V> = near.iter().map(|p| unit(sub(*p, *c))).collect();
            let mut best: Option<(V, V)> = None;
            let mut best_key = f64::NEG_INFINITY;
            for i in 0..dirs.len() {
                for y in &dirs[i + 1..] {
                    let k = -dot(dirs[i], *y);
                    if best.is_none() || k > best_key {
                        best = Some((dirs[i], *y));
                        best_key = k;
                    }
                }
            }
            let (a, b) = best.unwrap_or((dirs[0], dirs[dirs.len() - 1]));
            let ang = dot(a, b).clamp(-1.0, 1.0).acos();
            if ang < 1e-6 {
                rows.push(vec![add(*c, mul(a, r)); 9]);
                continue;
            }
            let ax = unit(cross(a, b));
            let bperp = cross(ax, a);
            let ext = 0.08 * ang;
            rows.push(
                (0..9)
                    .map(|k| {
                        let th = -ext + (ang + 2.0 * ext) * k as f64 / 8.0;
                        add(*c, mul(add(mul(a, th.cos()), mul(bperp, th.sin())), r))
                    })
                    .collect(),
            );
        }
        let rows = extend_rows(rows, 0.04);
        Ok(nurbs::interpolate_grid(&rows, 3)?)
    }

    /// Orientation of a fitted surface: match the outward normal of a tangent neighbour.
    fn orient_by_neighbours(&self, spec: &SurfSpec, loops: &[Loop], face_idx: i64) -> bool {
        let SurfSpec::BSpline(surf) = spec else { return true };
        let mut votes = 0i64;
        for lp in loops {
            for (e, _) in &lp.edges {
                let Some((p, n_out)) = self.neighbour_normal(e, face_idx) else { continue };
                let Some(n_fit) = surface_normal_near(surf, p, 12) else { continue };
                votes += if dot(n_fit, n_out) > 0.0 { 1 } else { -1 };
            }
        }
        votes >= 0
    }

    fn neighbour_normal(&self, edge: &Rc<Edge>, face_idx: i64) -> Option<(V, V)> {
        let eidx = self.edges.iter().find(|(_, e)| Rc::ptr_eq(e, edge))?.0;
        let en = self.p.get(eidx)?;
        let (mut fin, mut guard) = (self.p.get(en.p("fin")), 0);
        while let Some(f) = fin {
            if guard >= 16 {
                break;
            }
            if let Some(lp) = self.p.get(f.p("loop")) {
                if lp.p("face") != face_idx {
                    let fnode = self.p.get(lp.p("face"))?;
                    if let Some(sn) = self.p.get(fnode.p("surface")) {
                        if ["PLANE", "CYLINDER", "SPHERE", "TORUS", "CONE", "B_SURFACE"].contains(&sn.name.as_str()) {
                            let p = edge_samples(edge, 2)[1];
                            if let Some(n) = self.exact_normal(sn, p) {
                                let natural = (fnode.c("sense") != '-') == sense_plus(sn);
                                return Some((p, if natural { n } else { mul(n, -1.0) }));
                            }
                        }
                    }
                }
            }
            fin = self.p.get(f.p("other"));
            guard += 1;
        }
        None
    }

    fn exact_normal(&self, s: &Node, p: V) -> Option<V> {
        match s.name.as_str() {
            "PLANE" => Some(unit(s.v("normal"))),
            "CYLINDER" => {
                let a = unit(s.v("axis"));
                let q = sub(p, s.v("pvec"));
                Some(unit(sub(q, mul(a, dot(q, a)))))
            }
            "SPHERE" => Some(unit(sub(p, s.v("centre")))),
            "TORUS" => {
                let a = unit(s.v("axis"));
                let q = sub(p, s.v("centre"));
                let rad = unit(sub(q, mul(a, dot(q, a))));
                let c = add(s.v("centre"), mul(rad, s.r("major_radius")));
                Some(unit(sub(p, c)))
            }
            "CONE" => {
                let a = unit(s.v("axis"));
                let q = sub(p, s.v("pvec"));
                let r = unit(sub(q, mul(a, dot(q, a))));
                let (ca, sa) = (s.r("cos_half_angle"), s.r("sin_half_angle"));
                Some(unit(sub(mul(r, ca), mul(a, sa))))
            }
            "B_SURFACE" => bsurface(self.p, s).ok().and_then(|b| surface_normal_near(&b, p, 12)),
            _ => None,
        }
    }

    fn body(&mut self, bn: &Node) -> Result<Vec<Body>, GeomError> {
        let btype = match bn.i("body_type") {
            1 => "solid",
            2 => "wire",
            3 => "sheet",
            _ => "general",
        };
        let mut out = Vec::new();
        let mut seen: HashSet<i64> = HashSet::new();
        let mut sheet_shells: Vec<Shell> = Vec::new();
        let (mut ri, mut guard) = (bn.p("region"), 0);
        while ri != 0 && guard < 100000 {
            let rn = self.node(ri, "missing region")?;
            guard += 1;
            let solid_region = rn.c("type") == 'S';
            if btype == "solid" && !solid_region {
                ri = rn.p("next");
                continue;
            }
            let mut shells: Vec<Shell> = Vec::new();
            let (mut si, mut g1) = (rn.p("shell"), 0);
            while si != 0 && g1 < 100000 {
                let snode = self.node(si, "missing shell")?;
                g1 += 1;
                let mut faces = Vec::new();
                for (chain, nxt) in [("face", "next"), ("front_face", "next_front")] {
                    let (mut fi, mut g2) = (snode.get(chain).map_or(0, F::ptr), 0);
                    while fi != 0 && g2 < 1_000_000 {
                        g2 += 1;
                        if seen.insert(fi) {
                            match self.face(fi) {
                                Ok(f) => faces.push(f),
                                Err(e) => {
                                    let id = self.p.get(fi).map_or(0, |n| n.i("node_id"));
                                    self.warn(format!("face {id} left out: GeomError: {}", e.0));
                                }
                            }
                        }
                        fi = self.node(fi, "missing face")?.p(nxt);
                    }
                }
                if !faces.is_empty() {
                    shells.push(Shell { faces, closed: btype == "solid" });
                }
                si = snode.p("next");
            }
            if btype == "solid" && !shells.is_empty() {
                shells.sort_by(|a, b| shell_size(b).total_cmp(&shell_size(a))); // stable, largest first
                let rest = shells.split_off(1);
                out.push(Body { kind: "solid".into(), outer: shells, voids: rest, name: String::new() });
            } else {
                sheet_shells.extend(shells);
            }
            ri = rn.p("next");
        }
        if !sheet_shells.is_empty() {
            out.push(Body { kind: if btype != "solid" { "sheet".into() } else { "solid".into() }, outer: sheet_shells, voids: vec![], name: String::new() });
        }
        Ok(out)
    }

    pub fn bodies(&mut self) -> Vec<Body> {
        let mut out = Vec::new();
        for bn in self.p.of_type("BODY") {
            match self.body(bn) {
                Ok(b) => out.extend(b),
                Err(e) => self.warn(format!("body skipped: {}", e.0)),
            }
        }
        out
    }
}

fn shell_size(sh: &Shell) -> f64 {
    let pts: Vec<V> = sh.faces.iter().flat_map(|f| f.loops.iter().flat_map(|lp| lp.edges.iter().filter_map(|(e, _)| e.start.as_ref().map(|s| s.point)))).collect();
    if pts.is_empty() {
        return 0.0;
    }
    let lo = [0, 1, 2].map(|i| pts.iter().map(|p| p[i]).fold(f64::INFINITY, f64::min));
    let hi = [0, 1, 2].map(|i| pts.iter().map(|p| p[i]).fold(f64::NEG_INFINITY, f64::max));
    dist(lo, hi)
}

fn interp(pts: &[V]) -> Result<Curve, GeomError> {
    Ok(nurbs::interpolate(&pts.iter().map(|p| p.to_vec()).collect::<Vec<_>>(), 3, None, true)?)
}

fn sample_surface(f: &SurfFn, du: (f64, f64), dv: (f64, f64), nu: usize, nv: usize) -> Result<Surface, GeomError> {
    let grid: Vec<Vec<V>> = (0..nu)
        .map(|i| (0..nv).map(|j| f.at(du.0 + (du.1 - du.0) * i as f64 / (nu - 1) as f64, dv.0 + (dv.1 - dv.0) * j as f64 / (nv - 1) as f64)).collect())
        .collect();
    Ok(nurbs::interpolate_grid(&grid, 3)?)
}

fn surface_normal_near(s: &Surface, p: V, n: usize) -> Option<V> {
    let ((u0, u1), (v0, v1)) = s.domain();
    let mut best: Option<(f64, f64, f64)> = None;
    for i in 0..=n {
        for j in 0..=n {
            let u = u0 + (u1 - u0) * i as f64 / n as f64;
            let v = v0 + (v1 - v0) * j as f64 / n as f64;
            let d = dist(s.at(u, v), p);
            if best.is_none_or(|b| d < b.0) {
                best = Some((d, u, v));
            }
        }
    }
    let (_, u, v) = best?;
    let (hu, hv) = ((u1 - u0) * 1e-5, (v1 - v0) * 1e-5);
    let uu = u.max(u0 + hu).min(u1 - hu);
    let vv = v.max(v0 + hv).min(v1 - hv);
    Some(unit(cross(sub(s.at(uu + hu, vv), s.at(uu - hu, vv)), sub(s.at(uu, vv + hv), s.at(uu, vv - hv)))))
}

fn curve_point(spec: &CurveSpec) -> V {
    match spec {
        CurveSpec::Line(p, _) => *p,
        CurveSpec::Circle(c, _, x, r) => add(*c, mul(*x, *r)),
        CurveSpec::Ellipse(c, _, x, a, _) => add(*c, mul(*x, *a)),
        CurveSpec::BSpline(c) => v3(&c.at(c.domain().0)),
    }
}

pub fn edge_samples(e: &Edge, k: usize) -> Vec<V> {
    let (s, t) = match (&e.start, &e.end) {
        (Some(a), Some(b)) => (a.point, b.point),
        _ => return vec![],
    };
    match &e.curve {
        CurveSpec::Line(..) => (0..k).map(|i| add(s, mul(sub(t, s), i as f64 / (k - 1) as f64))).collect(),
        CurveSpec::Circle(c, n, x, r) => arc_samples(*c, *n, *x, *r, *r, s, t, e.same_sense, k),
        CurveSpec::Ellipse(c, n, x, a, b) => arc_samples(*c, *n, *x, *a, *b, s, t, e.same_sense, k),
        CurveSpec::BSpline(c) => {
            let (u0, u1) = c.domain();
            let mut pts: Vec<V> = (0..k).map(|i| v3(&c.at(u0 + (u1 - u0) * i as f64 / (k - 1) as f64))).collect();
            if !e.same_sense {
                pts.reverse();
            }
            pts
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn arc_samples(c: V, n: V, x: V, a: f64, b: f64, s: V, t: V, same: bool, k: usize) -> Vec<V> {
    let y = cross(n, x);
    let ang = |p: V| {
        let q = sub(p, c);
        (dot(q, y) / b).atan2(dot(q, x) / a)
    };
    let (a0, mut a1) = (ang(s), ang(t));
    if same {
        if a1 <= a0 + 1e-12 {
            a1 += 2.0 * PI;
        }
    } else if a1 >= a0 - 1e-12 {
        a1 -= 2.0 * PI;
    }
    (0..k)
        .map(|i| {
            let t = a0 + (a1 - a0) * i as f64 / (k - 1) as f64;
            add(c, add(mul(x, a * t.cos()), mul(y, b * t.sin())))
        })
        .collect()
}

/// An edge may use only a piece of its B-curve: cut the curve to the piece between its vertices.
fn trim_to_edge(c: &Curve, start: V, end: V, same: bool) -> Curve {
    let (lo, hi) = c.domain();
    let tol = 1e-8;
    let (p_lo, p_hi) = (v3(&c.at(lo)), v3(&c.at(hi)));
    let (a, b) = if same { (start, end) } else { (end, start) };
    if dist(p_lo, a) < tol && dist(p_hi, b) < tol {
        return c.clone();
    }
    if dist(a, b) < tol {
        return c.clone(); // closed edge on the whole curve
    }
    let (mut ua, da) = c.closest(&a, 0);
    let (mut ub, db) = c.closest(&b, 0);
    if dist(p_lo, a) < tol {
        ua = lo;
    }
    if dist(p_hi, b) < tol {
        ub = hi;
    }
    if ub - ua <= 1e-12 * 1f64.max(hi - lo) || da.max(db) > 1e-5 {
        return c.clone();
    }
    c.sub(ua, ub).unwrap_or_else(|_| c.clone())
}

fn resample(pts: &[V], k: usize) -> Vec<V> {
    if pts.len() <= k {
        return pts.to_vec();
    }
    let step = (pts.len() - 1) as f64 / (k - 1) as f64;
    (0..k).map(|i| pts[py_round_half_even(i as f64 * step)]).collect()
}

/// Python's `round(x)` (half to even).
fn py_round_half_even(x: f64) -> usize {
    let r = x.round();
    let r = if (x - x.trunc()).abs() == 0.5 && r % 2.0 != 0.0 { r - x.signum() } else { r };
    r as usize
}

fn extend_rows(rows: Vec<Vec<V>>, frac: f64) -> Vec<Vec<V>> {
    if rows.len() < 2 {
        return rows;
    }
    let n = (rows.len() - 1) as f64;
    let first: Vec<V> = rows[0].iter().zip(&rows[1]).map(|(a, b)| add(*a, mul(sub(*a, *b), frac * n))).collect();
    let last: Vec<V> = rows[rows.len() - 1].iter().zip(&rows[rows.len() - 2]).map(|(a, b)| add(*a, mul(sub(*a, *b), frac * n))).collect();
    let mut out = vec![first];
    out.extend(rows);
    out.push(last);
    out
}

/// Closest position on a polyline: (segment index + fraction, distance).
fn project_param(pts: &[V], q: V) -> (f64, f64) {
    let mut best = (0.0, f64::INFINITY);
    for i in 0..pts.len().saturating_sub(1) {
        let (a, b) = (pts[i], pts[i + 1]);
        let ab = sub(b, a);
        let l = dot(ab, ab);
        let t = if l == 0.0 { 0.0 } else { (dot(sub(q, a), ab) / l).clamp(0.0, 1.0) };
        let d = dist(add(a, mul(ab, t)), q);
        if d < best.1 {
            best = (i as f64 + t, d);
        }
    }
    best
}

fn at(pts: &[V], s: f64) -> V {
    let i = (s as usize).min(pts.len() - 2);
    let t = s - i as f64;
    add(pts[i], mul(sub(pts[i + 1], pts[i]), t))
}

/// B-spline through the part of a polyline (in curve direction) from start to end.
fn fit_between(pts: &[V], start: Option<V>, end: Option<V>) -> Result<Curve, GeomError> {
    let mut q: Vec<V> = match (start, end) {
        (Some(start), Some(end)) => {
            let closed = dist(pts[0], pts[pts.len() - 1]) < 1e-7;
            let (s0, _) = project_param(pts, start);
            let (s1, _) = project_param(pts, end);
            let sl = |a: usize, b: usize| -> Vec<V> { if a < b && a <= pts.len() { pts[a..b.min(pts.len())].to_vec() } else { vec![] } };
            if dist(start, end) < 1e-9 && closed {
                let i = s0 as usize;
                let lp = &pts[..pts.len() - 1];
                let mut q = vec![start];
                q.extend_from_slice(&lp[(i + 1).min(lp.len())..]);
                q.extend_from_slice(&lp[..(i + 1).min(lp.len())]);
                q.push(start);
                q
            } else if s1 > s0 {
                let mut q = vec![start];
                q.extend(sl(s0 as usize + 1, s1.ceil() as usize));
                q.push(end);
                q
            } else if closed {
                let mut q = vec![start];
                q.extend(sl(s0 as usize + 1, pts.len() - 1));
                q.extend(sl(0, s1.ceil() as usize));
                q.push(end);
                q
            } else {
                // edge runs against the polyline: reverse
                let rp: Vec<V> = pts.iter().rev().copied().collect();
                let n = (pts.len() - 1) as f64;
                let (r0, r1) = (n - s0, n - s1);
                let mut q = vec![start];
                let (a, b) = (r0 as usize + 1, r1.ceil() as usize);
                if a < b {
                    q.extend_from_slice(&rp[a.min(rp.len())..b.min(rp.len())]);
                }
                q.push(end);
                q
            }
        }
        _ => pts.to_vec(),
    };
    if q.len() > 240 {
        q = resample(&q, 240);
    }
    if q.len() == 2 {
        let mid = add(q[0], mul(sub(q[1], q[0]), 0.5));
        q = vec![q[0], mid, q[1]];
    }
    interp(&q)
}
