//! Reader for Parasolid neutral-binary transmit data, the geometry inside SolidWorks files (port
//! of `sw2sc/parasolid.py`). Written from the published "Parasolid XT Format Reference" (node
//! layouts, field types, binary encoding, embedded-schema edit sequences); no Parasolid code.
//!
//! The data is a sequence of nodes. Every node type has a list of fields; newer files describe,
//! the first time each node type appears, how its field list differs from the base schema
//! (SCH_13006). Result: `Partition::nodes` (index -> node), pointer fields as indices (0 null).

use std::collections::{BTreeMap, HashMap};
use std::sync::OnceLock;

pub const MAX_NODES: usize = 5_000_000;
pub const MAX_VAR: i32 = 50_000_000;

const ANY_CURVE: &str = "node_id:d attributes_groups:p owner:p next:p previous:p geometric_owner:p sense:c";

fn base_spec() -> Vec<(i32, &'static str, String)> {
    let c = ANY_CURVE;
    vec![
        (10, "ASSEMBLY", "highest_node_id:d attributes_groups:p attribute_chains:p list:p surface:p curve:p point:p key:p res_size:f res_linear:f ref_instance:p next:p previous:p state:u owner:p type:u sub_instance:p".into()),
        (11, "INSTANCE", "node_id:d attributes_groups:p type:u part:p transform:p assembly:p next_in_part:p prev_in_part:p next_of_part:p prev_of_part:p".into()),
        (12, "BODY", "highest_node_id:d attributes_groups:p attribute_chains:p surface:p curve:p point:p key:p res_size:f res_linear:f ref_instance:p next:p previous:p state:u owner:p body_type:u nom_geom_state:u shell:p boundary_surface:p boundary_curve:p boundary_point:p region:p edge:p vertex:p".into()),
        (13, "SHELL", "node_id:d attributes_groups:p body:p next:p face:p edge:p vertex:p region:p front_face:p".into()),
        (14, "FACE", "node_id:d attributes_groups:p tolerance:f next:p previous:p loop:p shell:p surface:p sense:c next_on_surface:p previous_on_surface:p next_front:p previous_front:p front_shell:p".into()),
        (15, "LOOP", "node_id:d attributes_groups:p fin:p face:p next:p".into()),
        (16, "EDGE", "node_id:d attributes_groups:p tolerance:f fin:p previous:p next:p curve:p next_on_curve:p previous_on_curve:p owner:p".into()),
        (17, "FIN", "attributes_groups:p loop:p forward:p backward:p vertex:p other:p edge:p curve:p next_at_vx:p sense:c".into()),
        (18, "VERTEX", "node_id:d attributes_groups:p fin:p previous:p next:p point:p tolerance:f owner:p".into()),
        (19, "REGION", "node_id:d attributes_groups:p body:p next:p previous:p shell:p type:c".into()),
        (29, "POINT", "node_id:d attributes_groups:p owner:p next:p previous:p pvec:v".into()),
        (30, "LINE", format!("{c} pvec:v direction:v")),
        (31, "CIRCLE", format!("{c} centre:v normal:v x_axis:v radius:f")),
        (32, "ELLIPSE", format!("{c} centre:v normal:v x_axis:v major_radius:f minor_radius:f")),
        (38, "INTERSECTION", format!("{c} surface:p[2] chart:p start:p end:p")),
        (40, "CHART", "base_parameter:f base_scale:f chart_count:d chordal_error:f angular_error:f parameter_error:f[2] hvec:h[]".into()),
        (41, "LIMIT", "type:c hvec:h[]".into()),
        (45, "BSPLINE_VERTICES", "vertices:f[]".into()),
        (50, "PLANE", format!("{c} pvec:v normal:v x_axis:v")),
        (51, "CYLINDER", format!("{c} pvec:v axis:v radius:f x_axis:v")),
        (52, "CONE", format!("{c} pvec:v axis:v radius:f sin_half_angle:f cos_half_angle:f x_axis:v")),
        (53, "SPHERE", format!("{c} centre:v radius:f axis:v x_axis:v")),
        (54, "TORUS", format!("{c} centre:v axis:v major_radius:f minor_radius:f x_axis:v")),
        (56, "BLENDED_EDGE", format!("{c} blend_type:c surface:p[2] spine:p range:f[2] thumb_weight:f[2] boundary:p[2] start:p end:p")),
        (59, "BLEND_BOUND", format!("{c} boundary:n blend:p")),
        (60, "OFFSET_SURF", format!("{c} check:c true_offset:l surface:p offset:f scale:f")),
        (67, "SWEPT_SURF", format!("{c} section:p sweep:v scale:f")),
        (68, "SPUN_SURF", format!("{c} profile:p base:v axis:v start:v end:v start_param:f end_param:f x_axis:v scale:f")),
        (70, "LIST", "node_id:d owner:p next:p previous:p list_type:d list_length:d block_length:d size_of_entry:d list_block:p".into()),
        (74, "POINTER_LIS_BLOCK", "n_entries:d next_block:p entries:p[]".into()),
        (79, "ATT_DEF_ID", "string:c[]".into()),
        (80, "ATTRIB_DEF", "next:p identifier:p type_id:d actions:u[8] field_names:p legal_owners:l[14] fields:u[]".into()),
        (81, "ATTRIBUTE", "node_id:d definition:p owner:p next:p previous:p next_of_type:p previous_of_type:p fields:p[]".into()),
        (82, "INT_VALUES", "values:d[]".into()),
        (83, "REAL_VALUES", "values:f[]".into()),
        (84, "CHAR_VALUES", "values:c[]".into()),
        (85, "POINT_VALUES", "values:v[]".into()),
        (86, "VECTOR_VALUES", "values:v[]".into()),
        (87, "AXIS_VALUES", "values:v[]".into()),
        (88, "TAG_VALUES", "values:t[]".into()),
        (89, "DIRECTION_VALUES", "values:v[]".into()),
        (90, "GROUP", "node_id:d attributes_groups:p owner:p next:p previous:p type:u first_member:p".into()),
        (91, "MEMBER_OF_GROUP", "dummy_node_id:d owning_group:p owner:p next:p previous:p next_member:p previous_member:p".into()),
        (98, "UNICODE_VALUES", "values:w[]".into()),
        (99, "FIELD_NAMES", "names:p[]".into()),
        (100, "TRANSFORM", "node_id:d owner:p next:p previous:p rotation_matrix:f[9] translation_vector:v scale:f flag:d perspective_vector:v".into()),
        (101, "WORLD", "assembly:p attribute:p body:p transform:p surface:p curve:p point:p alive:l attrib_def:p highest_id:d current_id:d".into()),
        (102, "KEY", "string:c[]".into()),
        (120, "PE_SURF", format!("{c} type:c data:p tf:p internal_geom:p[]")),
        (121, "INT_PE_DATA", "geom_type:d real_array:p int_array:p".into()),
        (122, "EXT_PE_DATA", "key:p real_array:p int_array:p".into()),
        (124, "B_SURFACE", format!("{c} nurbs:p data:p")),
        (125, "SURFACE_DATA", "original_uint:i original_vint:i extended_uint:i extended_vint:i self_int:u original_u_start:c original_u_end:c original_v_start:c original_v_end:c extended_u_start:c extended_u_end:c extended_v_start:c extended_v_end:c analytic_form_type:c swept_form_type:c spun_form_type:c blend_form_type:c analytic_form:p swept_form:p spun_form:p blend_form:p".into()),
        (126, "NURBS_SURF", "u_periodic:l v_periodic:l u_degree:n v_degree:n n_u_vertices:d n_v_vertices:d u_knot_type:u v_knot_type:u n_u_knots:d n_v_knots:d rational:l u_closed:l v_closed:l surface_form:u vertex_dim:n bspline_vertices:p u_knot_mult:p v_knot_mult:p u_knots:p v_knots:p".into()),
        (127, "KNOT_MULT", "mult:n[]".into()),
        (128, "KNOT_SET", "knots:f[]".into()),
        (130, "PE_CURVE", format!("{c} type:c data:p tf:p internal_geom:p[]")),
        (133, "TRIMMED_CURVE", format!("{c} basis_curve:p point_1:v point_2:v parm_1:f parm_2:f")),
        (134, "B_CURVE", format!("{c} nurbs:p data:p")),
        (135, "CURVE_DATA", "self_int:u analytic_form:p".into()),
        (136, "NURBS_CURVE", "degree:n n_vertices:d vertex_dim:n n_knots:d knot_type:u periodic:l closed:l rational:l curve_form:u bspline_vertices:p knot_mult:p knots:p".into()),
        (137, "SP_CURVE", format!("{c} surface:p b_curve:p original:p tolerance_to_original:f")),
        (141, "GEOMETRIC_OWNER", "owner:p next:p previous:p shared_geometry:p".into()),
        // the reference lists 163 as the curve form and 184 as the surface form, but sample files
        // show node 163 with the surface layout, referenced from SURFACE_DATA
        (163, "HELIX_SU_FORM", "axis_pt:v axis_dir:v hand:c turns:i pitch:f gap:f tol:f".into()),
        (184, "HELIX_CU_FORM", "axis_pt:v axis_dir:v point:v hand:c turns:i pitch:f tol:f".into()),
    ]
}

#[derive(Clone, Debug)]
pub struct FieldDef {
    pub name: String,
    pub ty: String,
    /// 0 scalar, 1 variable, >1 array
    pub n: i64,
    pub xmt: bool,
}

fn parse_spec(s: &str) -> Vec<FieldDef> {
    s.split_whitespace()
        .map(|tok| {
            let (name, t) = tok.split_once(':').unwrap();
            let (ty, n) = if let Some(t) = t.strip_suffix("[]") {
                (t.to_string(), 1)
            } else if let Some((t, k)) = t.strip_suffix(']').and_then(|x| x.split_once('[')) {
                (t.to_string(), k.parse().unwrap())
            } else {
                (t.to_string(), 0)
            };
            FieldDef { name: name.into(), ty, n, xmt: true }
        })
        .collect()
}

type Schema = (String, Vec<FieldDef>);

fn base() -> &'static HashMap<i32, Schema> {
    static B: OnceLock<HashMap<i32, Schema>> = OnceLock::new();
    B.get_or_init(|| base_spec().into_iter().map(|(k, n, s)| (k, (n.to_string(), parse_spec(&s)))).collect())
}

#[derive(Debug)]
pub struct XtError(pub String);

impl std::fmt::Display for XtError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

/// A field's value.
#[derive(Clone, Debug, PartialEq)]
pub enum F {
    Int(i64),
    Real(f64),
    Char(char),
    Bool(bool),
    Ptr(i64),
    V3([f64; 3]),
    V2([f64; 2]),
    Box([f64; 6]),
    List(Vec<F>),
}

impl F {
    pub fn ptr(&self) -> i64 {
        match self {
            F::Ptr(p) | F::Int(p) => *p,
            _ => 0,
        }
    }
    pub fn real(&self) -> f64 {
        match self {
            F::Real(x) => *x,
            F::Int(i) | F::Ptr(i) => *i as f64,
            _ => f64::NAN,
        }
    }
    pub fn int(&self) -> i64 {
        match self {
            F::Int(i) | F::Ptr(i) => *i,
            F::Real(x) => *x as i64,
            F::Bool(b) => *b as i64,
            F::Char(c) => *c as i64,
            _ => 0,
        }
    }
    pub fn v3(&self) -> [f64; 3] {
        match self {
            F::V3(v) => *v,
            _ => [f64::NAN; 3],
        }
    }
    pub fn ch(&self) -> char {
        match self {
            F::Char(c) => *c,
            _ => '\0',
        }
    }
    pub fn truthy(&self) -> bool {
        match self {
            F::Bool(b) => *b,
            F::Int(i) | F::Ptr(i) => *i != 0,
            F::Char(c) => *c != '\0',
            F::Real(x) => *x != 0.0,
            F::List(l) => !l.is_empty(),
            _ => true,
        }
    }
    pub fn list(&self) -> &[F] {
        match self {
            F::List(l) => l,
            _ => &[],
        }
    }
}

#[derive(Clone, Debug)]
pub struct Node {
    pub ty: i32,
    pub name: String,
    pub index: i64,
    pub f: HashMap<String, F>,
}

impl Node {
    pub fn get(&self, k: &str) -> Option<&F> {
        self.f.get(k)
    }
    pub fn p(&self, k: &str) -> i64 {
        self.f.get(k).map_or(0, F::ptr)
    }
    pub fn r(&self, k: &str) -> f64 {
        self.f.get(k).map_or(f64::NAN, F::real)
    }
    pub fn v(&self, k: &str) -> [f64; 3] {
        self.f.get(k).map_or([f64::NAN; 3], F::v3)
    }
    pub fn c(&self, k: &str) -> char {
        self.f.get(k).map_or('\0', F::ch)
    }
    pub fn i(&self, k: &str) -> i64 {
        self.f.get(k).map_or(0, F::int)
    }
}

pub struct Partition {
    pub modeller: String,
    pub schema: String,
    pub nodes: BTreeMap<i64, Node>,
    /// The order nodes were read in (the Python dict's order).
    pub order: Vec<i64>,
    pub warnings: Vec<String>,
}

impl Partition {
    pub fn of_type(&self, name: &str) -> Vec<&Node> {
        self.order.iter().filter_map(|i| self.nodes.get(i)).filter(|n| n.name == name).collect()
    }
    pub fn get(&self, idx: i64) -> Option<&Node> {
        if idx == 0 { None } else { self.nodes.get(&idx) }
    }
}

struct Reader<'a> {
    d: &'a [u8],
    p: usize,
}

impl Reader<'_> {
    fn take(&mut self, n: usize) -> Result<&[u8], XtError> {
        if self.p + n > self.d.len() {
            return Err(XtError(format!("unexpected end of data at {}", self.p)));
        }
        let b = &self.d[self.p..self.p + n];
        self.p += n;
        Ok(b)
    }
    fn u8(&mut self) -> Result<u8, XtError> {
        Ok(self.take(1)?[0])
    }
    fn i16(&mut self) -> Result<i16, XtError> {
        let b = self.take(2)?;
        Ok(i16::from_be_bytes([b[0], b[1]]))
    }
    fn i32(&mut self) -> Result<i32, XtError> {
        let b = self.take(4)?;
        Ok(i32::from_be_bytes([b[0], b[1], b[2], b[3]]))
    }
    fn f64(&mut self) -> Result<f64, XtError> {
        let b = self.take(8)?;
        Ok(f64::from_be_bytes(b.try_into().unwrap()))
    }
    fn ptr(&mut self) -> Result<i64, XtError> {
        let mut r = self.i16()? as i64;
        let mut q = 0i64;
        if r < 0 {
            q = self.i16()? as i64;
            r = -r;
        }
        Ok(q * 32767 + r - 1)
    }
    fn sstr(&mut self) -> Result<String, XtError> {
        let n = self.u8()? as usize;
        Ok(self.take(n)?.iter().map(|&c| c as char).collect())
    }
    fn scalar(&mut self, t: &str) -> Result<F, XtError> {
        Ok(match t {
            "d" | "t" => F::Int(self.i32()? as i64),
            "n" | "w" => F::Int(self.i16()? as i64),
            "u" => F::Int(self.u8()? as i64),
            "c" => F::Char(self.u8()? as char),
            "l" => F::Bool(self.u8()? != 0),
            "p" => F::Ptr(self.ptr()?),
            "f" => F::Real(self.f64()?),
            "v" | "h" => F::V3([self.f64()?, self.f64()?, self.f64()?]),
            "i" => F::V2([self.f64()?, self.f64()?]),
            "b" => F::Box([self.f64()?, self.f64()?, self.f64()?, self.f64()?, self.f64()?, self.f64()?]),
            other => return Err(XtError(format!("unknown field type {other:?}"))),
        })
    }
}

fn read_fielddef(r: &mut Reader) -> Result<FieldDef, XtError> {
    let name = r.sstr()?;
    let ptr_class = r.i16()?;
    let n = r.ptr()?;
    let ty = if ptr_class != 0 { "p".to_string() } else { r.sstr()? };
    let xmt = if n == 1 { r.u8()? != 0 } else { true };
    Ok(FieldDef { name, ty, n, xmt })
}

/// Parse a neutral-binary transmit stream (`PS\0\0` …).
pub fn read(data: &[u8]) -> Result<Partition, XtError> {
    let mut recent: Vec<(String, i64, usize)> = Vec::new();
    read_inner(data, &mut recent).map_err(|e| {
        let trail: Vec<String> = recent.iter().rev().take(4).rev().map(|(n, i, p)| format!("{n}#{i}@{p}")).collect();
        let msg: String = e.0.chars().take(120).collect();
        XtError(format!("{msg} (after {})", trail.join(", ")))
    })
}

fn read_inner(data: &[u8], recent: &mut Vec<(String, i64, usize)>) -> Result<Partition, XtError> {
    if data.len() < 4 || data[..4] != *b"PS\0\0" {
        return Err(XtError("not a neutral binary Parasolid stream".into()));
    }
    let mut r = Reader { d: data, p: 4 };
    let n = r.i16()?;
    let modeller: String = r.take(n.max(0) as usize)?.iter().map(|&c| c as char).collect();
    let n = r.i32()?;
    let schema: String = r.take(n.max(0) as usize)?.iter().map(|&c| c as char).collect();
    let embedded = schema.matches('_').count() >= 3;
    if embedded {
        r.i16()?; // maximum number of node types
    }
    let usfld = r.i32()?;
    if !(0..=16).contains(&usfld) {
        return Err(XtError(format!("bad user field size {usfld}")));
    }
    let mut schemas: HashMap<i32, Schema> = HashMap::new();
    let mut nodes: BTreeMap<i64, Node> = BTreeMap::new();
    let mut order: Vec<i64> = Vec::new();
    let mut warnings = Vec::new();
    loop {
        let start = r.p;
        let ntype = r.i16()? as i32;
        if ntype == 1 {
            break; // terminator
        }
        if !schemas.contains_key(&ntype) {
            let b = base().get(&ntype);
            if !embedded {
                let Some(b) = b else { return Err(XtError(format!("unknown node type {ntype} at {start}"))) };
                schemas.insert(ntype, b.clone());
            } else if let Some(b) = b {
                let flag = r.u8()?;
                if flag == 0xFF {
                    schemas.insert(ntype, b.clone());
                } else {
                    let mut cur: Vec<FieldDef> = Vec::new();
                    let mut bi = 0usize;
                    loop {
                        let op = r.u8()? as char;
                        match op {
                            'C' => {
                                if bi >= b.1.len() {
                                    return Err(XtError(format!("{}: copy past end of base schema", b.0)));
                                }
                                cur.push(b.1[bi].clone());
                                bi += 1;
                            }
                            'D' => bi += 1,
                            'I' | 'A' => cur.push(read_fielddef(&mut r)?),
                            'Z' => break,
                            _ => return Err(XtError(format!("{}: bad schema edit {:?} at {}", b.0, op, r.p - 1))),
                        }
                    }
                    if bi != b.1.len() {
                        return Err(XtError(format!("{}: base schema has {} fields, file used {}", b.0, b.1.len(), bi)));
                    }
                    if cur.len() != flag as usize {
                        warnings.push(format!("{}: expected {} fields, built {}", b.0, flag, cur.len()));
                    }
                    schemas.insert(ntype, (b.0.clone(), cur));
                }
            } else {
                let nf = r.u8()?;
                let name = r.sstr()?;
                r.sstr()?; // description
                let mut fds = Vec::new();
                for _ in 0..nf {
                    fds.push(read_fielddef(&mut r)?);
                }
                schemas.insert(ntype, (name, fds));
            }
        }
        let (name, fdefs) = schemas[&ntype].clone();
        let variable = fdefs.iter().any(|fd| fd.n == 1);
        let vlen = if variable { r.i32()? } else { 0 };
        if !(0..=MAX_VAR).contains(&vlen) {
            return Err(XtError(format!("{name}: bad variable length {vlen} at {start}")));
        }
        let index = r.ptr()?;
        let mut node = Node { ty: ntype, name: name.clone(), index, f: HashMap::new() };
        for fd in &fdefs {
            if !fd.xmt {
                continue;
            }
            let v = if fd.n == 0 {
                r.scalar(&fd.ty).map_err(|e| XtError(format!("{name}.{}: {}", fd.name, e.0)))?
            } else {
                let count = if fd.n == 1 { vlen as i64 } else { fd.n };
                let mut l = Vec::with_capacity(count.clamp(0, 1 << 20) as usize);
                for _ in 0..count {
                    l.push(r.scalar(&fd.ty).map_err(|e| XtError(format!("{name}.{}: {}", fd.name, e.0)))?);
                }
                F::List(l)
            };
            node.f.insert(fd.name.clone(), v);
        }
        if usfld != 0 && index != 0 {
            r.take(4 * usfld as usize)?;
        }
        if !nodes.contains_key(&index) {
            order.push(index);
        }
        nodes.insert(index, node);
        recent.push((name, index, start));
        if recent.len() > 8 {
            recent.remove(0);
        }
        if nodes.len() > MAX_NODES {
            return Err(XtError("too many nodes".into()));
        }
    }
    r.ptr()?; // terminator index
    Ok(Partition { modeller, schema, nodes, order, warnings })
}
