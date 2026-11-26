//! The part's own solid as STEP AP214 text (port of `sw2sc/step.py` and `sw2sc/geometry.py`).
//! Used as the reference the rebuilt feature tree must match, and as the import a part keeps
//! where its tree can't be rebuilt yet. Coordinates in millimetres.

use std::collections::HashMap;

use crate::nurbs::{compress_knots, Curve, Surface};
use crate::pyfmt::{repr, round};
use crate::swfile::{find, unzlb, zlb_sections, SwFile};
use crate::xtgeom::{Body, Converter, CurveSpec, Edge, Face, Loop, Shell, SurfSpec, Vertex, V};

/// The converter's version (the Python package's, which the port follows).
pub const VERSION: &str = include_str!("../../../VERSION");
const SCALE: f64 = 1000.0;

fn r(x: f64) -> String {
    let s = repr(x);
    if let Some((m, e)) = s.split_once('e') {
        let m = if m.contains('.') { m.to_string() } else { format!("{m}.") };
        return format!("{m}E{}", e.parse::<i32>().unwrap_or(0));
    }
    if s.contains('.') { s } else { s + "." }
}

/// A coordinate: 12 significant digits (as `_c` in step.py).
fn coord(x: f64) -> String {
    r(format!("{x:.11e}").parse().unwrap_or(x))
}

/// Knots at 12 digits, unless that would make two of them equal (as `_ks` in step.py).
fn knots_text(v: &[f64]) -> String {
    let out: Vec<String> = v.iter().map(|x| coord(*x)).collect();
    let bad = out.windows(2).any(|w| w[0].parse::<f64>().unwrap_or(0.0) >= w[1].parse::<f64>().unwrap_or(0.0));
    let out: Vec<String> = if bad { v.iter().map(|x| r(*x)).collect() } else { out };
    out.join(",")
}

fn st(s: &str) -> String {
    let mut out = String::from("'");
    for ch in s.chars() {
        match ch {
            '\'' => out.push_str("''"),
            '\\' => out.push_str("\\\\"),
            c if (32..127).contains(&(c as u32)) => out.push(c),
            c if (c as u32) < 0x10000 => out.push_str(&format!("\\X2\\{:04X}\\X0\\", c as u32)),
            _ => out.push('_'),
        }
    }
    out.push('\'');
    out
}

fn tf(b: bool) -> &'static str {
    if b { ".T." } else { ".F." }
}

struct Writer {
    lines: Vec<String>,
    points: HashMap<(i64, i64, i64), String>,
    dirs: HashMap<(i64, i64, i64), String>,
    vertices: HashMap<usize, String>,
    edges: HashMap<usize, String>,
    face_styles: Vec<(String, V)>,
    styles: HashMap<[u64; 3], String>,
}

fn k(x: f64, nd: usize) -> i64 {
    // Python's round(x, nd) as a key (exact enough to tell points apart as the dict does)
    (round(x, nd) * 10f64.powi(nd as i32)).round() as i64
}

impl Writer {
    fn add(&mut self, text: String) -> String {
        self.lines.push(text);
        format!("#{}", self.lines.len())
    }

    fn point(&mut self, p: V) -> String {
        let q = [p[0] * SCALE, p[1] * SCALE, p[2] * SCALE];
        let key = (k(q[0], 12), k(q[1], 12), k(q[2], 12));
        if let Some(s) = self.points.get(&key) {
            return s.clone();
        }
        let s = self.add(format!("CARTESIAN_POINT('',({},{},{}))", coord(q[0]), coord(q[1]), coord(q[2])));
        self.points.insert(key, s.clone());
        s
    }

    fn direction(&mut self, d: V) -> String {
        let key = (k(d[0], 14), k(d[1], 14), k(d[2], 14));
        if let Some(s) = self.dirs.get(&key) {
            return s.clone();
        }
        let s = self.add(format!("DIRECTION('',({},{},{}))", r(d[0]), r(d[1]), r(d[2])));
        self.dirs.insert(key, s.clone());
        s
    }

    fn axis2(&mut self, p: V, z: V, x: V) -> String {
        let dz = x[0] * z[0] + x[1] * z[1] + x[2] * z[2];
        let x = [x[0] - dz * z[0], x[1] - dz * z[1], x[2] - dz * z[2]];
        let n = (x[0] * x[0] + x[1] * x[1] + x[2] * x[2]).sqrt();
        let n = if n != 0.0 { n } else { 1.0 };
        let x = [x[0] / n, x[1] / n, x[2] / n];
        let (pp, zz, xx) = (self.point(p), self.direction(z), self.direction(x));
        self.add(format!("AXIS2_PLACEMENT_3D('',{pp},{zz},{xx})"))
    }

    fn curve(&mut self, spec: &CurveSpec) -> String {
        match spec {
            CurveSpec::Line(p, d) => {
                let dd = self.direction(*d);
                let v = self.add(format!("VECTOR('',{dd},1.)"));
                let pp = self.point(*p);
                self.add(format!("LINE('',{pp},{v})"))
            }
            CurveSpec::Circle(c, n, x, rad) => {
                let a = self.axis2(*c, *n, *x);
                self.add(format!("CIRCLE('',{a},{})", r(rad * SCALE)))
            }
            CurveSpec::Ellipse(c, n, x, a1, a2) => {
                let a = self.axis2(*c, *n, *x);
                self.add(format!("ELLIPSE('',{a},{},{})", r(a1 * SCALE), r(a2 * SCALE)))
            }
            CurveSpec::BSpline(c) => self.bcurve(c),
        }
    }

    fn bcurve(&mut self, c: &Curve) -> String {
        let (ks, ms) = compress_knots(&c.u, crate::nurbs::knot_eps(&c.u));
        let pts: Vec<String> = c.pts.iter().map(|p| self.point([p[0], p[1], p[2]])).collect();
        let (pts, knots) = (pts.join(","), knots_text(&ks));
        let mults = ms.iter().map(|m| m.to_string()).collect::<Vec<_>>().join(",");
        match &c.w {
            None => self.add(format!("B_SPLINE_CURVE_WITH_KNOTS('',{},({pts}),.UNSPECIFIED.,.F.,.F.,({mults}),({knots}),.UNSPECIFIED.)", c.p)),
            Some(w) => {
                let w = w.iter().map(|x| coord(*x)).collect::<Vec<_>>().join(",");
                self.add(format!(
                    "(BOUNDED_CURVE()B_SPLINE_CURVE({},({pts}),.UNSPECIFIED.,.F.,.F.)B_SPLINE_CURVE_WITH_KNOTS(({mults}),({knots}),.UNSPECIFIED.)CURVE()GEOMETRIC_REPRESENTATION_ITEM()RATIONAL_B_SPLINE_CURVE(({w}))REPRESENTATION_ITEM(''))",
                    c.p
                ))
            }
        }
    }

    fn surface(&mut self, spec: &SurfSpec) -> String {
        match spec {
            SurfSpec::Plane(p, n, x) => {
                let a = self.axis2(*p, *n, *x);
                self.add(format!("PLANE('',{a})"))
            }
            SurfSpec::Cylinder(p, ax, x, rad) => {
                let a = self.axis2(*p, *ax, *x);
                self.add(format!("CYLINDRICAL_SURFACE('',{a},{})", r(rad * SCALE)))
            }
            SurfSpec::Cone(p, ax, x, rad, semi) => {
                let a = self.axis2(*p, *ax, *x);
                self.add(format!("CONICAL_SURFACE('',{a},{},{})", r(rad * SCALE), r(*semi)))
            }
            SurfSpec::Sphere(c, ax, x, rad) => {
                let a = self.axis2(*c, *ax, *x);
                self.add(format!("SPHERICAL_SURFACE('',{a},{})", r(rad * SCALE)))
            }
            SurfSpec::Torus(c, ax, x, ma, mi) => {
                let a = self.axis2(*c, *ax, *x);
                self.add(format!("TOROIDAL_SURFACE('',{a},{},{})", r(ma * SCALE), r(mi * SCALE)))
            }
            SurfSpec::BSpline(s) => self.bsurface(s),
            SurfSpec::Blend(_) => self.add("PLANE('',$)".into()), // (never: blends are built before writing)
        }
    }

    fn bsurface(&mut self, s: &Surface) -> String {
        let (uk, um) = compress_knots(&s.u, crate::nurbs::knot_eps(&s.u));
        let (vk, vm) = compress_knots(&s.v, crate::nurbs::knot_eps(&s.v));
        let mut rows = Vec::new();
        for row in &s.g {
            let ps: Vec<String> = row.iter().map(|p| self.point(*p)).collect();
            rows.push(format!("({})", ps.join(",")));
        }
        let rows = rows.join(",");
        let js = |v: &[i64]| v.iter().map(|m| m.to_string()).collect::<Vec<_>>().join(",");
        let jr = |v: &[f64]| v.iter().map(|x| coord(*x)).collect::<Vec<_>>().join(",");
        let common = format!("({}),({}),({}),({}),.UNSPECIFIED.", js(&um), js(&vm), knots_text(&uk), knots_text(&vk));
        match &s.w {
            None => self.add(format!("B_SPLINE_SURFACE_WITH_KNOTS('',{},{},({rows}),.UNSPECIFIED.,.F.,.F.,.F.,{common})", s.pu, s.pv)),
            Some(w) => {
                let w = w.iter().map(|row| format!("({})", jr(row))).collect::<Vec<_>>().join(",");
                self.add(format!(
                    "(BOUNDED_SURFACE()B_SPLINE_SURFACE({},{},({rows}),.UNSPECIFIED.,.F.,.F.,.F.)B_SPLINE_SURFACE_WITH_KNOTS({common})GEOMETRIC_REPRESENTATION_ITEM()RATIONAL_B_SPLINE_SURFACE(({w}))REPRESENTATION_ITEM('')SURFACE())",
                    s.pu, s.pv
                ))
            }
        }
    }

    fn vertex(&mut self, v: &Vertex) -> String {
        if let Some(s) = self.vertices.get(&v.id) {
            return s.clone();
        }
        let p = self.point(v.point);
        let s = self.add(format!("VERTEX_POINT('',{p})"));
        self.vertices.insert(v.id, s.clone());
        s
    }

    fn edge(&mut self, e: &Edge) -> String {
        if let Some(s) = self.edges.get(&e.id) {
            return s.clone();
        }
        let c = self.curve(&e.curve);
        let a = self.vertex(e.start.as_ref().unwrap());
        let b = self.vertex(e.end.as_ref().unwrap());
        let s = self.add(format!("EDGE_CURVE('',{a},{b},{c},{})", tf(e.same_sense)));
        self.edges.insert(e.id, s.clone());
        s
    }

    fn lp(&mut self, l: &Loop) -> String {
        if let Some(v) = &l.vertex {
            let vv = self.vertex(v);
            return self.add(format!("VERTEX_LOOP('',{vv})"));
        }
        let mut oes = Vec::new();
        for (e, o) in &l.edges {
            let ee = self.edge(e);
            oes.push(self.add(format!("ORIENTED_EDGE('',*,*,{ee},{})", tf(*o))));
        }
        self.add(format!("EDGE_LOOP('',({}))", oes.join(",")))
    }

    fn face(&mut self, f: &Face) -> String {
        let mut bounds = Vec::new();
        for l in &f.loops {
            let ll = self.lp(l);
            bounds.push(self.add(format!("FACE_BOUND('',{ll},.T.)")));
        }
        let s = self.surface(&f.surface);
        let fid = self.add(format!("ADVANCED_FACE('',({}),{s},{})", bounds.join(","), tf(f.same_sense)));
        if let Some(rgb) = f.colour {
            self.face_styles.push((fid.clone(), rgb));
        }
        fid
    }

    fn styled_item(&mut self, item: String, rgb: V) {
        let key = rgb.map(f64::to_bits);
        let style = if let Some(style) = self.styles.get(&key) {
            style.clone()
        } else {
            let colour = self.add(format!("COLOUR_RGB('',{},{},{})", r(rgb[0]), r(rgb[1]), r(rgb[2])));
            let fill_colour = self.add(format!("FILL_AREA_STYLE_COLOUR('',{colour})"));
            let fill = self.add(format!("FILL_AREA_STYLE('',({fill_colour}))"));
            let fill_area = self.add(format!("SURFACE_STYLE_FILL_AREA({fill})"));
            let side = self.add(format!("SURFACE_SIDE_STYLE('',({fill_area}))"));
            let usage = self.add(format!("SURFACE_STYLE_USAGE(.BOTH.,{side})"));
            let style = self.add(format!("PRESENTATION_STYLE_ASSIGNMENT(({usage}))"));
            self.styles.insert(key, style.clone());
            style
        };
        self.add(format!("STYLED_ITEM('',({style}),{item})"));
    }

    fn shell(&mut self, sh: &Shell, closed: bool) -> String {
        let faces: Vec<String> = sh.faces.iter().map(|f| self.face(f)).collect();
        self.add(format!("{}('',({}))", if closed { "CLOSED_SHELL" } else { "OPEN_SHELL" }, faces.join(",")))
    }
}

pub fn write(bodies: &[Body], name: &str) -> String {
    let mut w = Writer { lines: vec![], points: HashMap::new(), dirs: HashMap::new(), vertices: HashMap::new(), edges: HashMap::new(), face_styles: vec![], styles: HashMap::new() };
    let ctx = w.add("APPLICATION_CONTEXT('automotive design')".into());
    w.add(format!("APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,{ctx})"));
    let pctx = w.add(format!("PRODUCT_CONTEXT('',{ctx},'mechanical')"));
    let prod = w.add(format!("PRODUCT({},{},'',({pctx}))", st(name), st(name)));
    w.add(format!("PRODUCT_RELATED_PRODUCT_CATEGORY('part',$,({prod}))"));
    let pdf = w.add(format!("PRODUCT_DEFINITION_FORMATION('','',{prod})"));
    let pdc = w.add(format!("PRODUCT_DEFINITION_CONTEXT('part definition',{ctx},'design')"));
    let pd = w.add(format!("PRODUCT_DEFINITION('design','',{pdf},{pdc})"));
    let pds = w.add(format!("PRODUCT_DEFINITION_SHAPE('','',{pd})"));
    let mm = w.add("(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.))".into());
    let rad = w.add("(NAMED_UNIT(*)PLANE_ANGLE_UNIT()SI_UNIT($,.RADIAN.))".into());
    let sr = w.add("(NAMED_UNIT(*)SI_UNIT($,.STERADIAN.)SOLID_ANGLE_UNIT())".into());
    let unc = w.add(format!("UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-05),{mm},'distance_accuracy_value','')"));
    let gctx = w.add(format!(
        "(GEOMETRIC_REPRESENTATION_CONTEXT(3)GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT(({unc}))GLOBAL_UNIT_ASSIGNED_CONTEXT(({mm},{rad},{sr}))REPRESENTATION_CONTEXT('',''))"
    ));
    let origin = w.axis2([0.0; 3], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0]);
    let (mut solids, mut sheets, mut body_styles) = (Vec::new(), Vec::new(), Vec::new());
    for (i, b) in bodies.iter().enumerate() {
        let label = if !b.name.is_empty() {
            st(&b.name)
        } else if bodies.len() > 1 {
            st(&format!("{name} body {}", i + 1))
        } else {
            st(name)
        };
        let mut item = None;
        if b.kind == "solid" && !b.outer.is_empty() {
            let outer = w.shell(&b.outer[0], true);
            if !b.voids.is_empty() {
                let mut vs = Vec::new();
                for v in &b.voids {
                    let s = w.shell(v, true);
                    vs.push(w.add(format!("ORIENTED_CLOSED_SHELL('',*,{s},.F.)")));
                }
                item = Some(w.add(format!("BREP_WITH_VOIDS({label},{outer},({}))", vs.join(","))));
            } else {
                item = Some(w.add(format!("MANIFOLD_SOLID_BREP({label},{outer})")));
            }
            solids.push(item.clone().unwrap_or_default());
        } else if !b.outer.is_empty() {
            let shells: Vec<String> = b.outer.iter().map(|sh| w.shell(sh, false)).collect();
            item = Some(w.add(format!("SHELL_BASED_SURFACE_MODEL({label},({}))", shells.join(","))));
            sheets.push(item.clone().unwrap_or_default());
        }
        if let (Some(item), Some(rgb)) = (item, b.colour) {
            body_styles.push((item, rgb));
        }
    }
    let items: Vec<String> = std::iter::once(origin.clone()).chain(solids).collect();
    let rep = w.add(format!("ADVANCED_BREP_SHAPE_REPRESENTATION({},({}),{gctx})", st(name), items.join(",")));
    w.add(format!("SHAPE_DEFINITION_REPRESENTATION({pds},{rep})"));
    if !sheets.is_empty() {
        let items: Vec<String> = std::iter::once(origin).chain(sheets).collect();
        let srep = w.add(format!("MANIFOLD_SURFACE_SHAPE_REPRESENTATION({},({}),{gctx})", st(name), items.join(",")));
        w.add(format!("SHAPE_REPRESENTATION_RELATIONSHIP('','',{rep},{srep})"));
    }
    body_styles.extend(w.face_styles.clone());
    for (item, rgb) in body_styles {
        w.styled_item(item, rgb);
    }
    let mut out = vec![
        "ISO-10303-21;".to_string(),
        "HEADER;".into(),
        "FILE_DESCRIPTION(('converted by sw2sc'),'2;1');".into(),
        format!("FILE_NAME({},'1970-01-01T00:00:00',(''),(''),'sw2sc {}','sw2sc','');", st(&format!("{name}.step")), VERSION.trim()),
        "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 3 1 1 }'));".into(),
        "ENDSEC;".into(),
        "DATA;".into(),
    ];
    out.extend(w.lines.iter().enumerate().map(|(i, l)| format!("#{}={l};", i + 1)));
    out.push("ENDSEC;".into());
    out.push("END-ISO-10303-21;".into());
    out.push(String::new());
    out.join("\n")
}

// --- where a part keeps its bodies (port of sw2sc/geometry.py) ------------------------------
fn config_of(name: &str) -> usize {
    let lower = name.to_ascii_lowercase();
    lower.find("config-").and_then(|i| {
        let rest = &name[i + 7..];
        let digits: String = rest.chars().take_while(|c| c.is_ascii_digit()).collect();
        (!digits.is_empty() && rest[digits.len()..].starts_with('-')).then(|| digits.parse().ok()).flatten()
    }).unwrap_or(1 << 30)
}

fn sw_string_before(blob: &[u8], end: usize) -> String {
    let lo = end.saturating_sub(600);
    let mut i = None;
    let mut from = lo;
    while let Some(j) = find(&blob[..end.min(blob.len())], &[0xff, 0xfe, 0xff], from) {
        i = Some(j);
        from = j + 1;
    }
    let Some(i) = i else { return String::new() };
    let n = blob[i + 3] as usize;
    let raw = &blob[(i + 4).min(blob.len())..(i + 4 + 2 * n).min(blob.len())];
    if raw.len() != 2 * n {
        return String::new();
    }
    crate::features::planes::utf16(raw)
}

fn has_body(sec: &[u8]) -> bool {
    sec.len() > 400 || find(&sec[..sec.len().min(80)], b"(partition)", 0).is_none()
}

/// [(body name or "", transmit bytes)] for the first configuration that has geometry.
pub fn parasolid_sources(sw: &SwFile) -> Vec<(String, Vec<u8>)> {
    let mut by_config: std::collections::BTreeMap<usize, Vec<(String, Vec<u8>)>> = Default::default();
    for (n, blob) in &sw.streams {
        let cfg = config_of(n);
        if n.starts_with("Contents/") && n.to_lowercase().ends_with("-partition") {
            for sec in zlb_sections(blob).unwrap_or_default() {
                if sec.starts_with(b"PS\0\0") && find(&sec[..sec.len().min(80)], b"(partition)", 0).is_some() {
                    by_config.entry(cfg).or_default().push((String::new(), sec));
                }
            }
        } else if n.ends_with("FeatureBodies/LocalBodies") {
            let guid = [0x23, 0x1d, 0xd5, 0x71, 0xda, 0x81, 0x48, 0xa2, 0xa8, 0x58, 0x98, 0xb2, 0x1b, 0x89, 0xef, 0x99];
            let mut i = find(blob, &guid, 0);
            while let Some(at) = i {
                let sec = unzlb(&blob[at..]).unwrap_or_default();
                if sec.starts_with(b"PS\0\0") && find(&sec[..sec.len().min(80)], b"(deltas)", 0).is_none() {
                    let name = sw_string_before(blob, at);
                    let name = match name.rfind('_') {
                        Some(k) if !name[k + 1..].is_empty() && name[k + 1..].chars().all(|c| c.is_ascii_digit()) => name[..k].to_string(),
                        _ => name,
                    };
                    by_config.entry(cfg).or_default().push((name, sec));
                }
                i = find(blob, &guid, at + 16);
            }
        }
    }
    for (_, v) in by_config {
        let mut found: Vec<(String, Vec<u8>)> = v.into_iter().filter(|(_, s)| has_body(s)).collect();
        // where the partition holds the part's solid, the named local bodies beside it are bodies
        // as they were imported (an import feature's own)
        if found.iter().any(|(n, _)| n.is_empty()) {
            found.retain(|(n, _)| n.is_empty());
        }
        if !found.is_empty() {
            return found;
        }
    }
    vec![]
}

/// The named bodies of `FeatureBodies/LocalBodies`, first configuration first: name -> the
/// Parasolid transmit bytes. An imported body is kept here under its feature's name.
pub fn local_bodies(sw: &SwFile) -> std::collections::HashMap<String, Vec<u8>> {
    let mut out = std::collections::HashMap::new();
    let mut names: Vec<&String> = sw.streams.keys().filter(|n| n.ends_with("FeatureBodies/LocalBodies")).collect();
    names.sort_by_key(|n| config_of(n));
    let guid = [0x23, 0x1d, 0xd5, 0x71, 0xda, 0x81, 0x48, 0xa2, 0xa8, 0x58, 0x98, 0xb2, 0x1b, 0x89, 0xef, 0x99];
    for n in names {
        let blob = &sw.streams[n];
        let mut i = find(blob, &guid, 0);
        while let Some(at) = i {
            let sec = unzlb(&blob[at..]).unwrap_or_default();
            if sec.starts_with(b"PS\0\0") && find(&sec[..sec.len().min(80)], b"(deltas)", 0).is_none() {
                let name = sw_string_before(blob, at);
                let name = match name.rfind('_') {
                    Some(k) if !name[k + 1..].is_empty() && name[k + 1..].chars().all(|c| c.is_ascii_digit()) => name[..k].to_string(),
                    _ => name,
                };
                if !name.is_empty() {
                    out.entry(name).or_insert(sec);
                }
            }
            i = find(blob, &guid, at + 16);
        }
    }
    out
}

/// One Parasolid body as STEP text (None if it doesn't convert).
pub fn body_step(data: &[u8], name: &str) -> Option<String> {
    let part = crate::parasolid::read(data).ok()?;
    let mut conv = Converter::new(&part);
    let mut bodies = conv.bodies();
    for b in bodies.iter_mut() {
        b.name = name.to_string();
    }
    (!bodies.is_empty()).then(|| write(&bodies, name))
}

/// The part's solid as STEP: (text or None, warnings, faces left out).
pub fn part_to_step(sw: &SwFile, name: &str) -> (Option<String>, Vec<String>, usize) {
    let sources = parasolid_sources(sw);
    if sources.is_empty() {
        return (None, vec!["no Parasolid geometry found in the part".into()], 0);
    }
    let mut bodies = Vec::new();
    let mut warnings = Vec::new();
    for (body_name, data) in sources {
        let part = match crate::parasolid::read(&data) {
            Ok(p) => p,
            Err(e) => {
                warnings.push(format!("geometry unreadable: {}", e.0));
                continue;
            }
        };
        let mut conv = Converter::new(&part);
        let mut got = conv.bodies();
        for b in got.iter_mut() {
            b.name = body_name.clone();
        }
        bodies.extend(got);
        warnings.extend(conv.warnings);
    }
    let left_out = warnings.iter().filter(|w| w.starts_with("face ")).count();
    if bodies.is_empty() {
        warnings.push("no bodies converted".into());
        return (None, warnings, left_out);
    }
    (Some(write(&bodies, name)), warnings, left_out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn step_styles_body_and_face() {
        let face = Face {
            surface: SurfSpec::Plane([0.0; 3], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0]),
            same_sense: true,
            loops: vec![],
            approx: false,
            source: "PLANE".into(),
            colour: Some([0.0, 0.5, 1.0]),
        };
        let body = Body {
            kind: "solid".into(),
            outer: vec![Shell { faces: vec![face], closed: true }],
            voids: vec![],
            name: String::new(),
            colour: Some([1.0, 0.25, 0.0]),
        };
        let text = write(&[body], "part");
        assert_eq!(text.matches("STYLED_ITEM(").count(), 2);
        assert_eq!(text.matches("PRESENTATION_STYLE_ASSIGNMENT(").count(), 2);
        assert!(text.contains("COLOUR_RGB('',1.0,0.25,0.0)"));
        assert!(text.contains("COLOUR_RGB('',0.0,0.5,1.0)"));
    }
}
