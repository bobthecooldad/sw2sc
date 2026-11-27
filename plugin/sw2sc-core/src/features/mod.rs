//! The feature tree of a SolidWorks part, read from its feature stream (port of
//! `sw2sc/features.py`).
//!
//! Reads `Contents/Config-0-ResolvedFeatures` with the object numbering of `archive` and returns
//! the features in order: sketches (points, lines, arcs, circles and the plane they are on),
//! extrudes, revolves, fillets, chamfers, holes, mirrors, patterns, threads, domes, sweeps,
//! shells, and every other feature as a TBD entry with its name, so it keeps its place in the
//! tree. Only what has been checked is decoded. Lengths come out in millimetres, positions in the
//! part's model space.

pub mod planes;
pub mod read;
pub mod sketch;

use indexmap::IndexMap;
use std::collections::BTreeSet;

pub use read::read;

pub const STREAM: &str = "Contents/Config-0-ResolvedFeatures";
pub const SKETCH: &str = "moProfileFeature_c";
pub const BOSS: &str = "moExtrusion_c";
pub const REVOLVE: &str = "moRevolution_c";
pub const REVCUT: &str = "moRevCut_c";
pub const FILLET: &str = "Fillet_c";
pub const CHAMFER: &str = "Chamfer_c";
pub const HOLE: &str = "moHoleWzd_c";
pub const MIRRORS: [&str; 2] = ["moMirrorPattern_c", "moMirrorSolid_c"];
pub const THREAD: &str = "moSweepThread_c";
pub const CUT: &str = "moICE_c";
/// A body (or surface) imported, or a mirror of another part file: no tree in this file.
pub const IMPORTED: [&str; 5] = ["moBaseBody_c", "moRefSurface_c", "moMirrorStock_c", "moMBimport_c", "moSplitBody_c"];

pub fn pattern_kind(cls: &str) -> Option<&'static str> {
    match cls {
        "moLPattern_c" => Some("linear"),
        "moCirPattern_c" => Some("circular"),
        "moCurvePattern_c" => Some("curve"),
        _ => None,
    }
}

/// A Hole Wizard hole's named parameters (SolidWorks' own names) -> what they are.
pub fn hole_param(name: &str) -> Option<&'static str> {
    Some(match name {
        "Hole Dia." | "Thru Hole Dia." | "Tap Drill Dia." | "Thru Tap Drill Dia." => "diameter",
        "Hole Depth" | "Thru Hole Depth" | "Tap Drill Depth" | "Thru Tap Drill Depth" => "depth",
        // a tapped hole with no drill diameter of its own lists this (the hole as drilled)
        "Thread Major Dia." => "thread_major",
        // names some files use (older Hole Wizard data, Portuguese files' holes)
        "Diameter" => "diameter",
        "Depth" => "depth",
        "C-Bore Diameter" => "cb_diameter",
        "C-Bore Depth" => "cb_depth",
        "C-Sink Diameter" => "cs_diameter",
        "C-Sink Angle" => "cs_angle",
        // Polish
        "Średnica otworu gwintowanego na wylot" => "diameter",
        "Głębokość otworu gwintowanego na wylot" => "depth",
        "C'Sink Dia." | "Near C'Sink Dia." => "cs_diameter",
        "C'Sink Angle" | "Near C'Sink Angle" => "cs_angle",
        "C'Bore Dia." => "cb_diameter",
        "C'Bore Depth" => "cb_depth",
        "Drill Angle" => "tip_angle",
        // French
        "Diamètre du perçage" | "Diamètre du perçage jusqu'au prochain" => "diameter",
        "Profondeur du perçage" | "Profondeur du perçage jusqu'au prochain" => "depth",
        "Diamètre du fraisage entrant" => "cs_diameter",
        "Angle du fraisage entrant" => "cs_angle",
        "Diamètre du lamage" => "cb_diameter",
        "Profondeur du lamage" => "cb_depth",
        "Angle de pointe" => "tip_angle",
        _ => return None,
    })
}

/// Named records that are not features: folders, parameters, dimensions, handles and helper
/// data. Every other named record is a feature, so a feature of a kind not converted yet still
/// keeps its place in the tree as TBD instead of being skipped.
const NOT_FEATURES: [&str; 13] = [
    "moDimTolerance_c", "moAttributeDef_c", "moAttribute_c",
    "moDetailCabinet_c", "moFavoriteHandle_c", "moCompRefPlane_c", "moPointBackedUpData_c",
    "moOriginProfileFeature_c", "moPLine_c", "moVertexRef_c", "moIntegerParameter_c",
    "moScalerParameter_c", "moFoldUpDownSketchFolder_c",
];
const NOT_FEATURE_ENDS: [&str; 19] = [
    "Folder_c", "Parameter_c", "Dim", "Dim_c", "Handle", "Handle_c", "Data_c", "IdRep_c", "Options_c",
    "Region_c", "ValG", "ValG_c", "ValG2_c", "Radial_c", "Chain_c", "Ref_c", "Ref_w", "Spec_c", "IdRepN_c",
];

pub fn is_feature_class(cls: &str) -> bool {
    !(NOT_FEATURES.contains(&cls)
        || cls.starts_with("pre")
        || cls.starts_with("sg")
        || NOT_FEATURE_ENDS.iter().filter(|e| !e.is_empty()).any(|e| cls.ends_with(e)))
}

pub type V3 = [f64; 3];
/// A placement: rotation rows (x, y, normal) and translation (metres).
pub type Frame = ([V3; 3], V3);
pub const FRONT: [V3; 3] = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]];
/// SolidWorks' Front, Top and Right planes as sketch frames (x, y, normal).
pub const STANDARD_PLANES: [[V3; 3]; 3] = [FRONT, [[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]], [[0.0, 0.0, -1.0], [0.0, 1.0, 0.0], [1.0, 0.0, 0.0]]];
pub const TOL: f64 = 1e-9; // metres

/// A face a SolidWorks reference names: (side | end, feature id, entity number | 0/1).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct FaceRef {
    pub side: bool,
    pub fid: u32,
    pub v: u32,
}

impl FaceRef {
    pub fn kind(&self) -> &'static str {
        if self.side { "side" } else { "end" }
    }
}

pub type Edge = (FaceRef, FaceRef);

pub fn straight_pattern_directions(sk: &Sketch, choice: usize) -> Vec<V3> {
    if sk.lines.len() != 1 || sk.planes.is_empty() {
        return Vec::new();
    }
    let (a, c) = sk.lines[0];
    let (Some(&p), Some(&q)) = (sk.points.get(&a), sk.points.get(&c)) else {
        return Vec::new();
    };
    let frame = sk.planes[choice.min(sk.planes.len() - 1)].0.0;
    let (du, dv) = (q.0 - p.0, q.1 - p.1);
    let length = du.hypot(dv);
    if length < 1e-12 {
        return Vec::new();
    }
    let (du, dv) = (du / length, dv / length);
    let direction = [du * frame[0][0] + dv * frame[1][0], du * frame[0][1] + dv * frame[1][1], du * frame[0][2] + dv * frame[1][2]];
    vec![direction, direction.map(|v| -v)]
}

#[derive(Clone, Debug, Default)]
pub struct Sketch {
    pub name: String,
    pub offset: usize,
    /// One past the sketch's records (its feature boundary).
    pub end: usize,
    /// id -> (x, y) in metres, sketch plane, in the order read.
    pub points: IndexMap<u32, (f64, f64)>,
    /// (point id, point id)
    pub lines: Vec<(u32, u32)>,
    /// Indices into lines of construction lines.
    pub construction: BTreeSet<usize>,
    /// Arc index -> the other centre it may have (x, y).
    pub alt_centres: IndexMap<usize, (f64, f64)>,
    /// Curves left out (a line with one end read): the note.
    pub dropped: Vec<String>,
    /// Point id -> the byte after its header's `80 BF`.
    pub point_flags: IndexMap<u32, u8>,
    /// (kind, curve id) the file's region names.
    pub region: Vec<(String, u16)>,
    /// The point ids a chain record names, in order.
    pub chain: Vec<u32>,
    /// (start id, end id, centre id)
    pub arcs: Vec<(u32, u32, u32)>,
    /// (centre id, radius m)
    pub circles: Vec<(u32, f64)>,
    /// Candidates: (frame, how).
    pub planes: Vec<(Frame, String)>,
    pub problems: Vec<String>,
    /// (line/arc, file curve id) -> SolidCraft curve id.
    pub curve_of: IndexMap<(String, u16), String>,
    /// (name, SolidWorks class, value m/rad, handles)
    pub dims: Vec<Dim>,
    /// Dimensions not written (meaning not decoded).
    pub dims_skipped: Vec<String>,
    /// (type, entity groups) as stored.
    pub relations: Vec<Relation>,
    pub relations_skipped: usize,
    /// Model parameters its dimensions drive (filled by the design writer).
    pub params: Vec<serde_json::Value>,
    /// Offset loops: {loop, sources, param, value} (SolidCraft ids).
    pub offsets: Vec<serde_json::Value>,
    /// A later feature has taken its plane reference.
    pub used: bool,
    /// Which candidate plane the design uses.
    pub choice: usize,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Dim {
    pub name: String,
    pub cls: String,
    pub value: f64,
    pub handles: Vec<Handle>,
}

/// A dimension's or relation's handle: (class, curve or point id).
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct Handle {
    pub cls: String,
    pub id: u32,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Relation {
    pub kind: u32,
    pub groups: Vec<Vec<Handle>>,
}

fn same_frame(a: &Frame, b: &Frame) -> bool {
    a.0.iter().zip(b.0.iter()).all(|(u, v)| u.iter().zip(v).all(|(p, q)| (p - q).abs() < 1e-9))
        && a.1.iter().zip(b.1.iter()).all(|(p, q)| (p - q).abs() < 1e-9)
}

impl Sketch {
    pub fn new(name: &str, offset: usize) -> Self {
        Sketch { name: name.into(), offset, ..Default::default() }
    }

    pub fn add_plane(&mut self, plane: &Frame, how: &str, first: bool) {
        if self.planes.iter().any(|(p, _)| same_frame(p, plane)) {
            return;
        }
        let item = (*plane, how.to_string());
        if first {
            self.planes.insert(0, item);
        } else {
            self.planes.push(item);
        }
    }

    /// Candidates (a face whose axes aren't stored), added in order (reversed when `first`, so
    /// they end up in order at the front).
    pub fn add_planes(&mut self, planes: &[Frame], how: &str, first: bool) {
        if first {
            for p in planes.iter().rev() {
                self.add_plane(p, how, true);
            }
        } else {
            for p in planes {
                self.add_plane(p, how, false);
            }
        }
    }

    pub fn plane(&self) -> Option<Frame> {
        self.planes.get(self.choice).map(|p| p.0)
    }

    pub fn plane_how(&self) -> String {
        self.planes.get(self.choice).map_or_else(|| "no plane reference found".into(), |p| p.1.clone())
    }
}

#[derive(Clone, Debug, Default)]
pub struct Feature {
    /// sketch / boss / cut / revolve / revcut / fillet / chamfer / hole / mirror / pattern /
    /// thread / dome / sweep / sweepcut / shell / import / absorbed / tbd
    pub kind: String,
    pub name: String,
    pub offset: usize,
    pub cls: String,
    pub sketch: Option<Sketch>,
    pub depth_mm: Option<f64>,
    /// Name of the sketch an extrude uses.
    pub profile: Option<String>,
    pub reason: String,
    /// A plane feature's placement.
    pub frame: Option<Frame>,
    /// An extrude with no distance in the file.
    pub through_all: bool,
    /// End type 6: the depth is the total distance about the sketch plane.
    pub mid_plane: bool,
    /// A revolve's angle.
    pub angle_deg: f64,
    /// SolidWorks' id of the feature (what face references name).
    pub fid: u32,
    /// A fillet's radius, a chamfer's distance.
    pub radius_mm: Option<f64>,
    /// A chamfer's angle (None: its second distance is chamfer_mm2).
    pub chamfer_deg: Option<f64>,
    pub chamfer_mm2: Option<f64>,
    /// A hole's sizes (mm, degrees) by SolidCraft's names.
    pub hole: IndexMap<String, serde_json::Value>,
    /// An extrude whose name says the other kind (boss / cut): tried too.
    pub alt_kind: Option<String>,
    /// An extrude of a sketch with no curves of its own: a face of the body's outline (chosen in the rebuild).
    pub from_face: bool,
    /// A mirror's (or shell's) face.
    pub mirror_face: Option<FaceRef>,
    /// Planes its record names: frames.
    pub mirror_planes: Vec<Frame>,
    /// A thread's diameter, pitch, length (mm).
    pub thread: IndexMap<String, serde_json::Value>,
    /// A pattern's kind, counts, spacings (mm) or angle (deg).
    pub pattern: IndexMap<String, serde_json::Value>,
    /// A thin extrude's (or shell's) wall thickness.
    pub thin_mm: Option<f64>,
    /// A dome's height.
    pub dome_mm: Option<f64>,
    /// A rib's mid plane (origin, x, y; mm) and free-edge chain (2D points, mm).
    pub rib: Option<([f64; 3], [f64; 3], [f64; 3], Vec<[f64; 2]>)>,
    /// A sweep's path sketch (its profile sketch is `profile`).
    pub path: Option<String>,
    /// A scale's factors (x, y, z).
    pub scale: Option<[f64; 3]>,
    /// A body move's translation (mm).
    pub translate: Option<[f64; 3]>,
    /// A body move's rotation rows (9 values).
    pub rotation: Option<[f64; 9]>,
    /// An import's body as imported (Parasolid), and as STEP once written.
    pub import_body: Option<Vec<u8>>,
    pub import_step: Option<String>,
    /// A fillet's edges.
    pub edges: Vec<Edge>,
    /// For each edge, the two faces at its ends (they border its faces).
    pub edge_ends: Vec<Edge>,
    /// For each fillet / chamfer edge, the line its two flat faces meet on (point, unit direction;
    /// mm), from the part's face tags.
    pub edge_lines: Vec<Option<[[f64; 3]; 2]>>,
    /// A fillet's own faces in the part's solid, where all are cylinders: (point, axis, radius), mm.
    pub round_axes: Vec<([f64; 3], [f64; 3], f64)>,
    /// A draft's angle (degrees).
    pub draft_deg: Option<f64>,
    /// A move face's offset distance (mm).
    pub move_mm: Option<f64>,
    /// A draft's / move face's: the part's own flat faces, (normal, point mm).
    pub final_planes: Vec<([f64; 3], [f64; 3])>,
}

impl Feature {
    pub fn new(kind: &str, name: &str, offset: usize, cls: &str) -> Self {
        Feature { kind: kind.into(), name: name.into(), offset, cls: cls.into(), angle_deg: 360.0, ..Default::default() }
    }
}

// --- little readers ---------------------------------------------------------------------------
pub(crate) fn u16_at(b: &[u8], o: usize) -> u16 {
    crate::cfb::u16_at(b, o)
}

pub(crate) fn u32_at(b: &[u8], o: usize) -> u32 {
    crate::cfb::u32_at(b, o)
}

pub(crate) fn f64_at(b: &[u8], o: usize) -> f64 {
    b.get(o..o + 8).map_or(f64::NAN, |s| f64::from_le_bytes(s.try_into().unwrap()))
}

pub(crate) fn f64s<const N: usize>(b: &[u8], o: usize) -> [f64; N] {
    let mut v = [0.0; N];
    for (i, x) in v.iter_mut().enumerate() {
        *x = f64_at(b, o + 8 * i);
    }
    v
}

/// `b.find(needle, lo, hi)`: the first `needle` wholly inside `b[lo..hi]`.
pub(crate) fn find_in(b: &[u8], needle: &[u8], lo: usize, hi: usize) -> Option<usize> {
    let hi = hi.min(b.len());
    if lo >= hi {
        return None;
    }
    memchr::memmem::find(&b[lo..hi], needle).map(|i| i + lo)
}

/// Python's `round(x, nd)`: the nearest decimal with `nd` places, as formatted.
pub fn py_round(x: f64, nd: usize) -> f64 {
    if !x.is_finite() {
        return x;
    }
    format!("{x:.nd$}").parse().unwrap_or(x)
}
