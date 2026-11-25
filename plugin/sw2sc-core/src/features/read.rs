//! The tree: every feature record in order, read (port of `read` and its helpers in
//! `sw2sc/features.py`).

use std::collections::{HashMap, HashSet};
use std::sync::OnceLock;

use indexmap::IndexMap;
use regex::bytes::Regex as BRegex;
use regex::Regex;
use serde_json::{json, Value};

use super::planes::{self, data_start, plane_frames, plane_from_ref, plane_inside, plane_refs, sketch_plane, Got};
use super::sketch::{class_tags, param_value, read_sketch, Tags};
use super::*;
use crate::archive::{self, Record};
use crate::swfile::SwFile;

// --- KeyWords ---------------------------------------------------------------------------------

/// Python's `html.unescape` for what KeyWords holds: the XML entities and numeric references.
pub fn unescape(s: &str) -> String {
    if !s.contains('&') {
        return s.to_string();
    }
    let mut out = String::with_capacity(s.len());
    let mut rest = s;
    while let Some(i) = rest.find('&') {
        out.push_str(&rest[..i]);
        let tail = &rest[i..];
        let semi = tail.find(';').filter(|&j| j <= 12);
        let ent = semi.map(|j| &tail[1..j]);
        let rep = ent.and_then(|e| match e {
            "amp" => Some('&'),
            "lt" => Some('<'),
            "gt" => Some('>'),
            "quot" => Some('"'),
            "apos" => Some('\''),
            "nbsp" => Some('\u{a0}'),
            "deg" => Some('°'),
            _ if e.starts_with("#x") || e.starts_with("#X") => u32::from_str_radix(&e[2..], 16).ok().and_then(char::from_u32),
            _ if e.starts_with('#') => e[1..].parse::<u32>().ok().and_then(char::from_u32),
            _ => None,
        });
        match (rep, semi) {
            (Some(c), Some(j)) => {
                out.push(c);
                rest = &tail[j + 1..];
            }
            _ => {
                out.push('&');
                rest = &tail[1..];
            }
        }
    }
    out.push_str(rest);
    out
}

/// Python's `html.escape(s)` (quote=True).
pub fn escape(s: &str) -> String {
    s.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;").replace('"', "&quot;").replace('\'', "&#x27;")
}

/// The inside of KeyWords' `<Feature ... Name="nm" ...>...</Feature>` (lazy, as the Python's
/// `<Feature [^>]*Name="%s"[^>]*>(.*?)</Feature>`).
pub fn kw_feature(kw: &str, nm: &str) -> Option<String> {
    let re = Regex::new(&format!(r#"(?s)<Feature [^>]*Name="{}"[^>]*>(.*?)</Feature>"#, regex::escape(&escape(nm)))).ok()?;
    re.captures(kw).map(|c| c[1].to_string())
}

/// The inside of the first `<tag ... Name="nm" ...>...</tag>`, any tag (the Python's
/// `<(\w+) [^>]*Name="%s"[^>]*>(.*?)</\1>`, written without a back-reference).
pub fn kw_element(kw: &str, nm: &str) -> Option<String> {
    let re = Regex::new(&format!(r#"<(\w+) [^>]*Name="{}"[^>]*>"#, regex::escape(&escape(nm)))).ok()?;
    let mut from = 0;
    while let Some(c) = re.captures_at(kw, from) {
        let m = c.get(0).unwrap();
        let close = format!("</{}>", &c[1]);
        if let Some(j) = kw[m.end()..].find(&close) {
            return Some(kw[m.end()..m.end() + j].to_string());
        }
        // no closing tag: Python's regex tries the next place
        from = m.start() + kw[m.start()..].chars().next().map_or(1, |ch| ch.len_utf8());
    }
    None
}

/// KeyWords' `<Dimension Name="Dn">value</Dimension>` inside `inner`, in order.
pub fn kw_dims(inner: &str) -> Vec<(String, String)> {
    static R: OnceLock<Regex> = OnceLock::new();
    let re = R.get_or_init(|| Regex::new(r#"<Dimension Name="(D\d+)">([^<]*)</Dimension>"#).unwrap());
    re.captures_iter(inner).map(|c| (c[1].to_string(), c[2].to_string())).collect()
}

/// The first number in `s` (`\d+(?:\.\d+)?`, or with a sign when `signed`).
pub fn first_number(s: &str, signed: bool) -> Option<f64> {
    static U: OnceLock<Regex> = OnceLock::new();
    static S: OnceLock<Regex> = OnceLock::new();
    let re = if signed {
        S.get_or_init(|| Regex::new(r"-?\d+(?:\.\d+)?").unwrap())
    } else {
        U.get_or_init(|| Regex::new(r"\d+(?:\.\d+)?").unwrap())
    };
    re.find(s).and_then(|m| m.as_str().parse::<f64>().ok())
}

/// The length units KeyWords can show a document's sizes in, as mm: mm, inch, cm, m, foot.
const UNITS: [f64; 5] = [1.0, 25.4, 10.0, 1000.0, 304.8];

/// A number as KeyWords shows it (`-?\d+(?:\.\d+)?`, unescaped): its value and its decimals.
fn shown_number(text: &str) -> Option<(f64, i32)> {
    static R: OnceLock<Regex> = OnceLock::new();
    let re = R.get_or_init(|| Regex::new(r"-?\d+(?:\.(\d+))?").unwrap());
    let t = unescape(text);
    let c = re.captures(&t)?;
    Some((c[0].parse().ok()?, c.get(1).map_or(0, |m| m.as_str().len() as i32)))
}

/// A KeyWords length in mm. KeyWords shows it in the document's units, rounded as it displays
/// it; the feature's record (`b[lo..hi]`) keeps it exact in metres. For the unit found earlier
/// in this file (before one is, mm and inch), the record's doubles that round to the shown
/// value are found; the commonest is the value, and its unit is kept in `unit`. Where none
/// matches, the value as shown, in the unit found earlier (mm if none).
fn kw_length(text: Option<&str>, b: &[u8], lo: usize, hi: usize, unit: &mut Option<f64>) -> Option<f64> {
    let (v, dec) = shown_number(text?)?;
    let order: Vec<f64> = match *unit {
        Some(u) => vec![u],
        None => UNITS[..2].to_vec(),
    };
    for u in order {
        let (want, half) = (v * u, 0.5 * 10f64.powi(-dec) * u + 1e-9);
        let mut found: IndexMap<u64, usize> = IndexMap::new();
        for i in lo..hi.saturating_sub(8).max(lo) {
            let d = f64::from_le_bytes(b[i..i + 8].try_into().unwrap()) * 1000.0;
            if !d.is_nan() && (d - want).abs() <= half && d > 0.0 {
                *found.entry(d.to_bits()).or_insert(0) += 1;
            }
        }
        let mut best: Option<(f64, usize)> = None;
        for (&bits, &n) in &found {
            let d = f64::from_bits(bits);
            let better = match best {
                None => true,
                Some((bd, bn)) => n > bn || (n == bn && (d - want).abs() < (bd - want).abs()),
            };
            if better {
                best = Some((d, n));
            }
        }
        if let Some((d, _)) = best {
            *unit = Some(u);
            return Some(d);
        }
    }
    Some(v * unit.unwrap_or(1.0))
}

/// The unit KeyWords shows lengths in (as mm), from a sketch's dimensions: KeyWords' value of
/// a length dimension against the sketch's own (exact, in metres).
fn sketch_unit(kw: &str, sk: &Sketch) -> Option<f64> {
    let re = Regex::new(&format!(r#"(?s)<Sketch [^>]*Name="{}"[^>/]*>(.*?)</Sketch>"#, regex::escape(&escape(&sk.name)))).ok()?;
    let inner = re.captures(kw)?[1].to_string();
    let shown: HashMap<String, String> = kw_dims(&inner).into_iter().collect();
    for d in &sk.dims {
        let t = unescape(shown.get(&d.name).map_or("", |s| s.as_str()));
        let Some((v, dec)) = shown_number(&t) else { continue };
        if t.contains('°') || d.value == 0.0 || v == 0.0 {
            continue;
        }
        for u in UNITS {
            if (d.value.abs() * 1000.0 - v.abs() * u).abs() <= 0.5 * 10f64.powi(-dec) * u + 1e-9 && v.abs() * u > 10f64.powi(-dec) * u {
                return Some(u);
            }
        }
    }
    None
}

const KW_TYPES: [(&str, &str); 14] = [
    ("Fillet", FILLET), ("Скругление", FILLET), ("Congé", FILLET), ("Verrundung", FILLET),
    ("Filete", FILLET), ("Redondeo", FILLET), ("Raccordo", FILLET),
    ("Chanfro", CHAMFER), ("Chaflán", CHAMFER), ("Smusso", CHAMFER),
    ("Chamfer", CHAMFER), ("Фаска", CHAMFER), ("Chanfrein", CHAMFER), ("Fase", CHAMFER),
];
const BOSS_TYPES: [&str; 7] = ["Boss-Extrude", "Бобышка-Вытянуть", "Boss.-Extru.", "Ressalto-extrusão", "Saliente-Extruir", "Aufsatz-Extrusion", "Estrusione base"];
const CUT_TYPES: [&str; 7] = ["Cut-Extrude", "Enlèv. mat.-Extru.", "Вырез-Вытянуть", "Corte-extrusão", "Cortar-Extruir", "Schnitt-Extrusion", "Taglio estruso"];
const ORIGIN_NAMES: [&str; 5] = ["Origin", "Origine", "Ursprung", "Origen", "Исходная точка"];

/// KeyWords' features: (element, name, type), in its order.
fn kw_features(kw: &str) -> Vec<(String, String, Option<String>)> {
    static E: OnceLock<Regex> = OnceLock::new();
    static N: OnceLock<Regex> = OnceLock::new();
    static T: OnceLock<Regex> = OnceLock::new();
    let e_re = E.get_or_init(|| Regex::new(r"<(Feature|Extrusion|HoleWizard|Cut|Sketch) ([^>]*)>").unwrap());
    let n_re = N.get_or_init(|| Regex::new(r#"Name="([^"]+)""#).unwrap());
    let t_re = T.get_or_init(|| Regex::new(r#"Type="([^"]+)""#).unwrap());
    let mut out = Vec::new();
    for c in e_re.captures_iter(kw) {
        let (e, rest) = (&c[1], &c[2]);
        let Some(n) = n_re.captures(rest) else { continue };
        let name = unescape(&n[1]);
        if e == "Sketch" && (!rest.contains(r#"Dissectable="true""#) || ORIGIN_NAMES.contains(&name.as_str())) {
            continue;
        }
        out.push((e.to_string(), name, t_re.captures(rest).map(|t| unescape(&t[1]))));
    }
    out
}

fn ci(pattern: &str) -> Regex {
    Regex::new(&format!("(?i){pattern}")).unwrap()
}

fn says_cut(nm: &str) -> bool {
    static R: OnceLock<Regex> = OnceLock::new();
    R.get_or_init(|| ci("cut|вырез|enl|corte|cortar|schnitt|taglio|řez")).is_match(nm)
}

fn says_boss(nm: &str) -> bool {
    static R: OnceLock<Regex> = OnceLock::new();
    R.get_or_init(|| ci("boss|бобышка|ressalto|saliente|aufsatz|estrusione|bossage|výstupek")).is_match(nm)
}

/// (record index or None, record, name)
type Named = (Option<usize>, Record, String);

/// Features KeyWords lists that the record numbering missed, found by their name; and boss /
/// cut corrected where KeyWords says which. Returned with the rest, in stream order.
fn recover(b: &[u8], named: Vec<Named>, kw: &str) -> Vec<Named> {
    let listed = kw_features(kw);
    let mut by_name: HashMap<&str, (&str, Option<&str>)> = HashMap::new();
    for (e, n, t) in &listed {
        by_name.insert(n.as_str(), (e.as_str(), t.as_deref())); // (later wins, as a dict)
    }
    let mut fixed = Vec::new();
    for (k, mut r, nm) in named {
        if let Some((e, t)) = by_name.get(nm.as_str()) {
            if (*e == "Extrusion" || *e == "Cut") && r.cls != "moCut_c" {
                let t = t.unwrap_or("");
                let mut want = if BOSS_TYPES.contains(&t) {
                    BOSS.to_string()
                } else if CUT_TYPES.contains(&t) {
                    CUT.to_string()
                } else {
                    r.cls.clone()
                };
                if want != BOSS && want != CUT {
                    want = if *e == "Cut" || says_cut(&nm) {
                        CUT.into()
                    } else if says_boss(&nm) {
                        BOSS.into()
                    } else {
                        want
                    };
                }
                if want != r.cls {
                    r = Record { offset: r.offset, number: r.number, cls: want, new_class: r.new_class };
                }
            }
        }
        fixed.push((k, r, nm));
    }
    let named = fixed;
    let found: HashSet<&str> = named.iter().map(|x| x.2.as_str()).collect();
    let mut learned: HashMap<&str, &str> = HashMap::new();
    for (_k, r, nm) in &named {
        if let Some((_e, Some(t))) = by_name.get(nm.as_str()) {
            learned.insert(t, r.cls.as_str());
        }
    }
    let mut tag_cls: HashMap<u16, &str> = HashMap::new();
    for (_k, r, _nm) in &named {
        if !r.new_class && r.offset + 2 <= b.len() {
            tag_cls.entry(u16_at(b, r.offset)).or_insert(r.cls.as_str());
        }
    }
    let taken: HashSet<usize> = named.iter().map(|x| x.1.offset).collect();
    let mut extra: Vec<Named> = Vec::new();
    for (e, nm, t) in &listed {
        let units: Vec<u16> = nm.encode_utf16().collect();
        let n_chars = nm.chars().count(); // (Python's len: code points)
        if found.contains(nm.as_str()) || n_chars > 255 {
            continue;
        }
        let t = t.as_deref();
        let cls: Option<String> = match (e.as_str(), t) {
            ("HoleWizard", _) => Some(HOLE.into()),
            ("Sketch", _) => Some(SKETCH.into()),
            ("Extrusion", Some(t)) if BOSS_TYPES.contains(&t) => Some(BOSS.into()),
            ("Extrusion", Some(t)) if CUT_TYPES.contains(&t) => Some(CUT.into()),
            (_, Some(t)) => learned
                .get(t)
                .map(|s| s.to_string())
                .or_else(|| KW_TYPES.iter().find(|(k, _)| *k == t).map(|(_, v)| v.to_string())),
            (_, None) => None,
        };
        let mut needle = vec![0xff, 0xfe, 0xff, n_chars as u8];
        for u in &units {
            needle.extend_from_slice(&u.to_le_bytes());
        }
        let mut i = crate::swfile::find(b, &needle, 0);
        while let Some(at) = i {
            if at < 4 {
                break;
            }
            if b[at - 1] & 0x80 != 0 && b[at - 3] & 0x80 != 0 && !taken.contains(&(at - 4)) {
                let mut c = cls.clone().or_else(|| tag_cls.get(&u16_at(b, at - 4)).map(|s| s.to_string()));
                if (e == "Extrusion" || e == "Cut") && !matches!(c.as_deref(), Some(BOSS) | Some(CUT) | Some("moCut_c")) {
                    // an extrude is a boss or a cut, whatever a drifted tag says
                    c = if e == "Cut" || says_cut(nm) {
                        Some(CUT.into())
                    } else if says_boss(nm) {
                        Some(BOSS.into())
                    } else {
                        None
                    };
                }
                if let Some(c) = c {
                    if is_feature_class(&c) {
                        extra.push((None, Record { offset: at - 4, number: -1, cls: c, new_class: false }, nm.clone()));
                    }
                }
                break;
            }
            i = crate::swfile::find(b, &needle, at + 1);
        }
    }
    let mut all: Vec<Named> = named.into_iter().chain(extra).collect();
    all.sort_by_key(|x| x.1.offset); // stable
    all
}

/// A feature's id: the u16 8 bytes after its name (7 zero bytes and a flag byte between).
fn fid(b: &[u8], r: &Record) -> u32 {
    let Some(i) = find_in(b, &[0xff, 0xfe, 0xff], r.offset, r.offset + 40) else { return 0 };
    let j = i + 4 + 2 * *b.get(i + 3).unwrap_or(&0) as usize;
    u16_at(b, j + 8) as u32
}

fn face_ref_re() -> &'static BRegex {
    static R: OnceLock<BRegex> = OnceLock::new();
    R.get_or_init(|| {
        BRegex::new(r"(?s-u)([\x00-\xff][\x80-\xff])\x00\x00([\x00-\xff][\x80-\xff])[\x00-\xff]{2}([\x00-\xff]{4})[\x00-\xff]{4}([\x00-\xff]{4})([\x00-\xff]{4})")
            .unwrap()
    })
}

/// A face reference found: (class tag, feature id, value, next u32, offset).
type RawRef = (u16, u32, u32, u32, usize);

fn face_ref_at(b: &[u8], end: usize, from: usize) -> Option<RawRef> {
    let end = end.min(b.len());
    if from >= end {
        return None;
    }
    let c = face_ref_re().captures_at(&b[..end], from)?;
    let at = c.get(0).unwrap().start();
    let g = |n: usize| c.get(n).unwrap().as_bytes();
    Some((u16_at(g(1), 0), u32_at(g(3), 0), u32_at(g(4), 0), u32_at(g(5), 0), at))
}

const RESULT: [&str; 3] = ["moCompEdge_c", "edgeRadiusObject_c", "moCompFace_c"];

/// The edges a fillet rounds: groups of four face references (the two faces that meet there,
/// then the two at its ends). See the Python for how many and how they are told apart.
fn edge_refs(b: &[u8], recs: &[Record], k: Option<usize>, end: usize, fids: &HashSet<u32>, own: u32, s0: usize) -> Vec<[FaceRef; 4]> {
    let mut raw: Vec<RawRef> = Vec::new();
    let mut i = s0;
    while let Some(m) = face_ref_at(b, end, i) {
        let (tag, fd, v, nxt, at) = m;
        if !fids.contains(&fd) {
            i = at + 1;
            continue;
        }
        if fd != own {
            raw.push((tag, fd, v, nxt, at));
        }
        i = at + 20;
    }
    // its own faces: read at every occurrence of its id
    let first = raw.first().map_or(end, |r| r.4);
    let key = own.to_le_bytes();
    let mut own_faces: Vec<u32> = Vec::new();
    let mut j = s0;
    while let Some(at) = find_in(b, &key, j, first) {
        if at + 12 > b.len() {
            break;
        }
        if at >= 4 && b[at - 3] & 0x80 != 0 {
            own_faces.push(u32_at(b, at + 8));
        }
        j = at + 1;
    }
    if let Some(p) = own_faces.iter().position(|&v| v == 1) {
        own_faces.drain(..p);
    }
    let mut n_faces = 0;
    for (n, &v) in own_faces.iter().enumerate() {
        if v != n as u32 + 1 {
            break;
        }
        n_faces = n + 1;
    }
    let refs: Vec<RawRef> = if n_faces > 0 && raw.len() >= 4 * n_faces {
        raw[..4 * n_faces].to_vec()
    } else if let Some(k) = k {
        let (mut stop, mut started) = (end, false);
        for x in &recs[k + 1..] {
            if x.offset >= end {
                break;
            }
            let ref_rec = x.cls.ends_with("IdRep_c") || x.cls == "moFR_c" || x.cls == "moEdgeRef_c";
            if RESULT.contains(&x.cls.as_str()) || (started && !ref_rec) {
                stop = x.offset;
                break;
            }
            started = started || ref_rec;
        }
        raw.into_iter().filter(|r| r.4 < stop).collect()
    } else {
        return vec![];
    };
    if refs.is_empty() || refs.len() % 4 != 0 {
        return vec![];
    }
    // which class tag is the end face: by name where this stream defines the class, else the tag
    // whose references are all 0 or 1
    let tags = class_tags(recs);
    let mut named: HashSet<u16> = refs.iter().filter(|r| tags.get(&(r.0 as u32)).is_some_and(|c| c == "moEndFaceSurfIdRep_c")).map(|r| r.0).collect();
    if named.is_empty() {
        let all: HashSet<u16> = refs.iter().map(|r| r.0).collect();
        let big: HashSet<u16> = refs.iter().filter(|r| r.2 > 1).map(|r| r.0).collect();
        let small: HashSet<u16> = all.difference(&big).copied().collect();
        named = if small.len() == 1 { small } else { refs.iter().filter(|r| r.2 <= 1 && r.3 < 16).map(|r| r.0).collect() };
    }
    let faces: Vec<FaceRef> = refs.iter().map(|r| FaceRef { side: !named.contains(&r.0), fid: r.1, v: r.2 }).collect();
    faces.chunks_exact(4).map(|c| [c[0], c[1], c[2], c[3]]).collect()
}

/// An extrude's depth: the value of its first length parameter, or else of its first distance
/// dimension (`ParallelPlaneDistanceDim_c`).
fn depth(b: &[u8], recs: &[Record], k: usize, end: usize) -> Option<f64> {
    let inside: Vec<&Record> = recs[k + 1..].iter().filter(|r| r.offset < end).collect();
    for cls in ["moLengthParameter_c", "ParallelPlaneDistanceDim_c"] {
        if let Some(r) = inside.iter().find(|r| r.cls == cls) {
            if let Some(v) = param_value(b, data_start(b, r)) {
                if 1e-7 < v.abs() && v.abs() < 100.0 {
                    return Some(v);
                }
            }
        }
    }
    None
}

fn first_face(b: &[u8], from: usize, end: usize, fids: &HashSet<u32>, own: u32) -> Option<FaceRef> {
    let hi = end.min(from + 2000);
    let mut i = from;
    while let Some((_t, fd, v, nxt, at)) = face_ref_at(b, hi, i) {
        // (Python's finditer: the next match starts after this one ends)
        i = at + 24;
        if fids.contains(&fd) && fd != own {
            return Some(FaceRef { side: !(v <= 1 && (nxt < 16 || nxt == 100_000)), fid: fd, v });
        }
    }
    None
}

fn add_got(sk: &mut Sketch, got: Option<Got>, how: &str, first: bool) {
    match got {
        Some(Got::One(f)) => sk.add_plane(&f, how, first),
        Some(Got::Many(v)) => sk.add_planes(&v, how, first),
        None => {}
    }
}

fn num_or_null(x: Option<f64>) -> Value {
    x.map_or(Value::Null, |v| json!(v))
}

/// The part's features in order, or None when the stream can't be numbered.
pub fn read(sw: &SwFile) -> Option<Vec<Feature>> {
    let b: &[u8] = sw.streams.get(STREAM)?;
    if b.is_empty() {
        return None;
    }
    let mut start = archive::start_number(b);
    let old_file = start.is_none();
    let mut outside: Option<HashSet<i64>> = None;
    if start.is_none() {
        // files saved before 2015 carry on Contents/Config-0's numbering
        if let Some(main) = sw.streams.get(&STREAM.replace("-ResolvedFeatures", "")) {
            outside = Some(archive::class_numbers(&archive::records(main, Some(0), None, false)).values().copied().collect());
        }
        start = Some(archive::old_start_number(b, outside.as_ref())?);
    }
    let recs = archive::records(b, start, outside.as_ref(), true);
    let kw = sw.xml("swXmlContents/KeyWords").unwrap_or_default();
    // each sketch's current dimensions by name, from KeyWords (a stale record isn't listed)
    let sk_re = Regex::new(r#"(?s)<Sketch id="\d+" Name="([^"]*)"[^>/]*>(.*?)</Sketch>"#).unwrap();
    let dim_re = Regex::new(r#"<Dimension Name="([^"]+)""#).unwrap();
    let mut kw_sk_dims: HashMap<String, HashSet<String>> = HashMap::new();
    for c in sk_re.captures_iter(&kw) {
        kw_sk_dims.insert(unescape(&c[1]), dim_re.captures_iter(&c[2]).map(|d| d[1].to_string()).collect());
    }
    let kw_sketches: HashSet<String> = Regex::new(r#"<Sketch id="\d+" Name="([^"]*)""#).unwrap().captures_iter(&kw).map(|c| unescape(&c[1])).collect();
    let tags: Tags = class_tags(&recs);
    let (by_id, by_off) = plane_frames(b, &recs);
    let mut named: Vec<Named> = Vec::new();
    let mut origin_seen = false;
    for (k, r) in recs.iter().enumerate() {
        if r.cls == "moOriginProfileFeature_c" {
            origin_seen = true;
        }
        if !is_feature_class(&r.cls) || (r.cls == "moRefPlane_c" && !origin_seen) {
            continue;
        }
        if let Some(nm) = planes::name(b, r) {
            named.push((Some(k), r.clone(), nm));
        }
    }
    let named = recover(b, named, &kw);
    let mut learned: Tags = Tags::new();
    // the unit KeyWords shows lengths in (as mm), once a value has shown it
    let mut unit: Option<f64> = None;
    let mut local: Option<std::collections::HashMap<String, Vec<u8>>> = None;
    let mut out: Vec<Feature> = Vec::new();
    let mut last_sketch: Option<usize> = None; // index into out
    let fids: HashSet<u32> = named.iter().map(|x| fid(b, &x.1)).collect();
    let rec_offsets: Vec<usize> = recs.iter().map(|x| x.offset).collect();
    for n in 0..named.len() {
        let (k0, ref r, ref nm) = named[n];
        let end = if n + 1 < named.len() { named[n + 1].1.offset } else { b.len() };
        let mut k = k0;
        if k.is_none() && r.cls != FILLET && r.cls != CHAMFER {
            // found by name: the records nearby stand in for it
            k = Some(rec_offsets.partition_point(|&o| o <= r.offset).saturating_sub(1));
        }
        let cls = r.cls.as_str();
        let last_name = last_sketch.map(|i| out[i].name.clone());
        let mut f: Feature;
        if cls == SKETCH {
            let k = k.unwrap();
            let mut sk = Sketch::new(nm, r.offset);
            sk.end = end;
            read_sketch(b, &tags, &mut sk, r.offset, end, Some(&mut learned));
            if kw_sketches.contains(nm) {
                let keep = kw_sk_dims.get(nm).cloned().unwrap_or_default();
                sk.dims.retain(|d| keep.contains(&d.name));
            }
            let (pl, how) = sketch_plane(b, &recs, k, &by_id, &by_off);
            if pl.is_some() {
                add_got(&mut sk, pl, &how, false);
            } else {
                let prev = if n > 0 { named[n - 1].1.offset } else { 0 };
                let refs = plane_refs(b, &recs, prev, r.offset);
                if let Some(&(o, nc)) = refs.last() {
                    let (pl, how) = plane_from_ref(b, &recs, o, nc, &by_id, &by_off);
                    if pl.is_some() {
                        add_got(&mut sk, pl, &format!("plane reference before it: {how}"), false);
                        // some files write a sketch's plane reference after it, among its own
                        // records (the one before is then another's): tried too
                        let (pl2, how2) = plane_inside(b, &recs, r.offset, end, &by_id, &by_off);
                        add_got(&mut sk, pl2, &format!("plane reference after it: {how2}"), false);
                    }
                }
            }
            if sk.planes.is_empty() {
                let (pl, how) = plane_inside(b, &recs, r.offset, end, &by_id, &by_off);
                add_got(&mut sk, pl, &how, false);
            }
            if unit.is_none() {
                unit = sketch_unit(&kw, &sk);
            }
            f = Feature::new("sketch", nm, r.offset, cls);
            f.sketch = Some(sk);
        } else if cls == "moBossThin_c" || cls == "moCutThin_c" || cls == "moExtruThin_c" {
            // a thin extrude: KeyWords' D1 its depth, D5 its wall's thickness
            f = Feature::new(if cls == "moCutThin_c" { "cut" } else { "boss" }, nm, r.offset, cls);
            f.profile = last_name;
            let dims: HashMap<String, String> = kw_element(&kw, nm).map(|i| kw_dims(&i).into_iter().collect()).unwrap_or_default();
            f.depth_mm = kw_length(dims.get("D1").map(|s| s.as_str()), b, r.offset, end, &mut unit);
            f.thin_mm = kw_length(dims.get("D5").map(|s| s.as_str()), b, r.offset, end, &mut unit);
            if f.depth_mm.is_none_or(|v| v == 0.0) || f.thin_mm.is_none_or(|v| v == 0.0) {
                f.kind = "tbd".into();
                f.reason = "thin extrude's depth or thickness not read".into();
            }
        } else if cls == BOSS || cls == CUT || cls == "moCut_c" {
            f = Feature::new(if cls == BOSS { "boss" } else { "cut" }, nm, r.offset, cls);
            f.profile = last_name;
            // where the numbering drifts, a boss can read as a cut: a default name that says the
            // other kind is tried too
            if f.kind == "cut" && (nm.starts_with("Boss") || nm.starts_with("Бобышка")) {
                f.alt_kind = Some("boss".into());
            } else if f.kind == "boss" && (nm.starts_with("Cut") || nm.starts_with("Вырез") || nm.starts_with("Enl")) {
                f.alt_kind = Some("cut".into());
            }
            let mut dep = depth(b, &recs, k.unwrap(), end);
            if dep.is_none() {
                // no distance in its records: KeyWords' D1 for it (a blind depth; through all has none)
                let re = Regex::new(&format!(r#"(?s)<Extrusion [^>]*Name="{}"[^>/]*>(.*?)</Extrusion>"#, regex::escape(&escape(nm)))).unwrap();
                let d1 = re.captures(&kw).and_then(|c| kw_dims(&c[1]).into_iter().find(|d| d.0 == "D1")).map(|d| d.1);
                dep = d1.and_then(|t| kw_length(Some(&t), b, r.offset, end, &mut unit)).filter(|&mm| mm != 0.0).map(|mm| mm / 1000.0);
            }
            match dep {
                None => f.through_all = true,
                Some(d) => f.depth_mm = Some(d * 1000.0),
            }
            // a thin extrude kept under the plain class (older files): KeyWords gives its wall as D5
            let re = Regex::new(&format!(r#"(?s)<Extrusion ([^>]*Name="{}"[^>/]*)>(.*?)</Extrusion>"#, regex::escape(&escape(nm)))).unwrap();
            if let Some(c) = re.captures(&kw) {
                if let Some(d5) = kw_dims(&c[2]).into_iter().find(|d| d.0 == "D5") {
                    if nm.contains("Thin") || c[1].contains("Thin") {
                        f.thin_mm = kw_length(Some(&d5.1), b, r.offset, end, &mut unit);
                    }
                }
            }
        } else if cls == REVOLVE || cls == REVCUT {
            f = Feature::new(if cls == REVOLVE { "revolve" } else { "revcut" }, nm, r.offset, cls);
            f.profile = last_name;
            let mut ang = None;
            for x in &recs[k.unwrap() + 1..] {
                if x.offset >= end {
                    break;
                }
                if x.cls == "moAngleParameter_c" {
                    ang = param_value(b, data_start(b, x));
                    break;
                }
            }
            f.angle_deg = match ang {
                Some(a) if a != 0.0 && 1e-6 < a.abs() && a.abs() <= 2.0 * std::f64::consts::PI + 1e-9 => a.to_degrees(),
                _ => 360.0,
            };
        } else if cls == FILLET || cls == CHAMFER {
            f = Feature::new(if cls == FILLET { "fillet" } else { "chamfer" }, nm, r.offset, cls);
            let mut rad = None;
            if let Some(k) = k {
                for x in &recs[k + 1..] {
                    if x.offset >= end {
                        break;
                    }
                    if x.cls == "moLengthParameter_c" {
                        rad = param_value(b, data_start(b, x));
                        break;
                    }
                }
            }
            let d1 = [0xff, 0xfe, 0xff, 0x02, b'D', 0, b'1', 0];
            let d2n = [0xff, 0xfe, 0xff, 0x02, b'D', 0, b'2', 0];
            if rad.is_none() {
                rad = find_in(b, &d1, r.offset, end).and_then(|j| param_value(b, j));
            }
            let groups = edge_refs(b, &recs, k, end, &fids, fid(b, r), r.offset);
            f.edges = groups.iter().map(|g| (g[0], g[1])).collect();
            f.edge_ends = groups.iter().map(|g| (g[2], g[3])).collect();
            if f.kind == "chamfer" {
                rad = find_in(b, &d1, r.offset, end).and_then(|j| param_value(b, j));
                let j2 = find_in(b, &d2n, r.offset, end);
                let d2 = j2.and_then(|j| param_value(b, j));
                let owner = j2.and_then(|j| recs.iter().filter(|x| x.offset <= j).next_back());
                match d2 {
                    Some(d2) if owner.is_some_and(|o| o.cls == "moAngleParameter_c") || (0.1 < d2 && d2 < std::f64::consts::PI) => {
                        f.chamfer_deg = Some(py_round(d2.to_degrees(), 6));
                    }
                    Some(d2) if 1e-7 < d2 && d2 < 10.0 => f.chamfer_mm2 = Some(d2 * 1000.0),
                    _ => f.chamfer_deg = Some(45.0),
                }
            }
            match rad {
                Some(v) if v != 0.0 && 1e-7 < v && v < 10.0 && !f.edges.is_empty() => f.radius_mm = Some(v * 1000.0),
                _ => {
                    f.reason = format!("{}'s size or edges not read", f.kind);
                    f.kind = "tbd".into();
                }
            }
        } else if cls == HOLE {
            // its placement sketch and profile sketch follow it; its sizes are named parameters
            f = Feature::new("hole", nm, r.offset, cls);
            let stop = named[n + 1..].iter().find(|x| x.1.cls != SKETCH).map_or(b.len(), |x| x.1.offset);
            f.hole = hole_params(b, r.offset, stop);
            if !f.hole.contains_key("diameter") {
                if let Some(d) = hole_from_name(nm) {
                    f.hole.insert("diameter".into(), json!(d));
                }
            }
            if !f.hole.contains_key("diameter") {
                f.kind = "tbd".into();
                f.reason = "hole's size not read".into();
            }
        } else if cls == "moShell_c" {
            // a shell: KeyWords' D1 its thickness; the face it opens named like a mirror's
            f = Feature::new("shell", nm, r.offset, cls);
            let d1 = kw_feature(&kw, nm).and_then(|i| kw_dims(&i).into_iter().find(|d| d.0 == "D1")).map(|d| d.1);
            f.thin_mm = d1.and_then(|t| kw_length(Some(&t), b, r.offset, end, &mut unit));
            f.mirror_face = first_face(b, r.offset, end, &fids, fid(b, r));
            if f.thin_mm.is_none_or(|v| v == 0.0) {
                f.kind = "tbd".into();
                f.reason = "shell's thickness not read".into();
            }
        } else if ["moCosmeticThread_c", "moRefAxis_c", "moRefPoint_c", "moSensor_c", "moHelix_c", "moRefCurve_c", "moSketchBitmap_c", "moExtObject_c", "moDatumTarget_c", "moCoordSys_c"].contains(&cls) {
            f = Feature::new("absorbed", nm, r.offset, cls);
            f.reason = format!("{cls}: reference geometry or annotation, no solid; not converted yet");
        } else if cls == "moCombineBodies_c" {
            f = Feature::new("absorbed", nm, r.offset, cls);
            f.reason = "combine of bodies: the converter joins bodies as it goes".into();
        } else if cls == "moSweep_c" || cls == "moSweepCut_c" {
            // a sweep: a profile and a path, the two sketches before it (the profile the one
            // with a closed loop; the search tries them the other way round too)
            f = Feature::new(if cls == "moSweep_c" { "sweep" } else { "sweepcut" }, nm, r.offset, cls);
            let two: Vec<usize> = out.iter().enumerate().filter(|(_, x)| x.kind == "sketch").map(|(i, _)| i).collect();
            if two.len() >= 2 {
                let (a, c) = (two[two.len() - 2], two[two.len() - 1]);
                let closed = |i: usize| !crate::design::profile_loops(out[i].sketch.as_ref().unwrap()).is_empty();
                let (prof, path) = if closed(a) && !closed(c) { (a, c) } else { (c, a) };
                f.profile = Some(out[prof].name.clone());
                f.path = Some(out[path].name.clone());
                out[prof].sketch.as_mut().unwrap().used = true;
                out[path].sketch.as_mut().unwrap().used = true;
            } else {
                f.kind = "tbd".into();
                f.reason = "sweep's profile and path not found".into();
            }
        } else if cls == "moScale_c" {
            // a scale: its factors are the first three doubles in its record that are all sizes;
            // what it scales about is chosen in the rebuild
            f = Feature::new("scale", nm, r.offset, cls);
            f.scale = scale_factors(b, r.offset, end);
            if f.scale.is_none() {
                f.kind = "tbd".into();
                f.reason = "scale's factors not read".into();
            }
        } else if cls == "moDome_c" {
            f = Feature::new("dome", nm, r.offset, cls);
            let d1 = kw_feature(&kw, nm).and_then(|i| kw_dims(&i).into_iter().find(|d| d.0 == "D1")).map(|d| d.1);
            f.dome_mm = d1.and_then(|t| kw_length(Some(&t), b, r.offset, end, &mut unit)).filter(|&v| v != 0.0);
            if f.dome_mm.is_none() {
                f.kind = "tbd".into();
                f.reason = "dome's height not read".into();
            }
        } else if let Some(kind) = pattern_kind(cls) {
            // counts and spacings are KeyWords' dimensions: D1 count, D3 spacing / angle, D2 the
            // second count, D4 the second spacing
            f = Feature::new("pattern", nm, r.offset, cls);
            let dims: Vec<(String, String)> = kw_feature(&kw, nm).map(|i| kw_dims(&i)).unwrap_or_default();
            let dmap: HashMap<String, String> = dims.iter().cloned().collect();
            let val = |k: &str| dmap.get(k).and_then(|v| first_number(&unescape(v), true));
            let angle = dims.iter().find(|(_, v)| unescape(v).contains('°')).and_then(|(k, _)| val(k));
            f.pattern.insert("kind".into(), json!(kind));
            f.pattern.insert("count1".into(), num_or_null(val("D1")));
            if kind == "circular" {
                f.pattern.insert("angle".into(), num_or_null(angle));
            } else {
                let s1 = kw_length(dmap.get("D3").map(|s| s.as_str()), b, r.offset, end, &mut unit);
                f.pattern.insert("spacing1".into(), num_or_null(s1));
                f.pattern.insert("count2".into(), num_or_null(val("D2")));
                let s2 = kw_length(dmap.get("D4").map(|s| s.as_str()), b, r.offset, end, &mut unit);
                f.pattern.insert("spacing2".into(), num_or_null(s2));
            }
            let zero = |x: Option<f64>| x.is_none_or(|v| v == 0.0);
            if zero(val("D1")) || (kind == "circular" && zero(angle)) || (kind == "linear" && zero(val("D3"))) {
                f.kind = "tbd".into();
                f.reason = "pattern's counts not read".into();
            }
        } else if cls == THREAD {
            // a modelled thread: `<MOD-DIAM>4` the diameter; of the other lengths the smaller is
            // the pitch, the larger the length
            f = Feature::new("thread", nm, r.offset, cls);
            let all = Regex::new(r#"<Dimension Name="D\d+">([^<]*)</Dimension>"#).unwrap();
            let dims: Vec<String> = kw_feature(&kw, nm).map(|i| all.captures_iter(&i).map(|c| c[1].to_string()).collect()).unwrap_or_default();
            let mut lengths: Vec<f64> = Vec::new();
            for v in dims {
                let v = unescape(&v);
                let Some(num) = first_number(&v, true) else { continue };
                if v.contains('°') {
                    continue;
                }
                let mm = kw_length(Some(&v.replace("<MOD-DIAM>", "")), b, r.offset, end, &mut unit).unwrap_or(num);
                if v.contains("MOD-DIAM") {
                    f.thread.insert("diameter".into(), json!(mm));
                } else {
                    lengths.push(mm);
                }
            }
            let has_d = f.thread.contains_key("diameter");
            if lengths.len() >= 2 && has_d {
                let lo = lengths.iter().copied().fold(f64::INFINITY, f64::min);
                let hi = lengths.iter().copied().fold(f64::NEG_INFINITY, f64::max);
                f.thread.insert("pitch".into(), json!(lo));
                f.thread.insert("length".into(), json!(hi));
            } else if lengths.len() == 1 && has_d {
                f.thread.insert("pitch".into(), json!(lengths[0]));
            } else {
                f.kind = "tbd".into();
                f.reason = "thread's sizes not read".into();
            }
        } else if MIRRORS.contains(&cls) {
            f = Feature::new("mirror", nm, r.offset, cls);
            f.mirror_face = first_face(b, r.offset, end, &fids, fid(b, r));
            for (o, nc) in plane_refs(b, &recs, r.offset, end) {
                match plane_from_ref(b, &recs, o, nc, &by_id, &by_off).0 {
                    Some(Got::One(p)) => f.mirror_planes.push(p),
                    Some(Got::Many(v)) => f.mirror_planes.extend(v),
                    None => {}
                }
            }
        } else if IMPORTED.contains(&cls) {
            // it converts as SolidCraft's import of the body, as it was imported (kept under the
            // feature's name among the local bodies)
            f = Feature::new("import", nm, r.offset, cls);
            if local.is_none() {
                local = Some(crate::step::local_bodies(sw));
            }
            f.import_body = local.as_ref().and_then(|l| l.get(nm.as_str()).cloned());
        } else if cls == "moRefPlane_c" {
            f = Feature::new("plane", nm, r.offset, cls);
            f.frame = by_off.get(&r.offset).copied();
            if f.frame.is_none() {
                f.kind = "tbd".into();
                f.reason = "plane's placement not read".into();
            }
        } else if cls == "mo3DProfileFeature_c" && out.last().is_some_and(|x| x.cls == HOLE) {
            // a Hole Wizard hole's 3D placement sketch: its points become a sketch of points on a
            // plane through them
            let pts = points_3d(b, r.offset, end);
            match if pts.is_empty() { None } else { placement_from_3d(nm, r.offset, &pts) } {
                None => {
                    f = Feature::new("tbd", nm, r.offset, cls);
                    f.reason = "3D sketch: its points not read, or not on one plane".into();
                }
                Some(mut sk) => {
                    sk.end = end;
                    f = Feature::new("sketch", nm, r.offset, cls);
                    f.sketch = Some(sk);
                }
            }
        } else {
            f = Feature::new("tbd", nm, r.offset, cls);
            f.reason = format!("{cls} not converted yet");
        }
        if cls != SKETCH {
            if let Some(li) = last_sketch {
                if !out[li].sketch.as_ref().unwrap().used {
                    // every feature is preceded by the plane of the sketch it uses
                    out[li].sketch.as_mut().unwrap().used = true;
                    let prev = if n > 0 { named[n - 1].1.offset } else { 0 };
                    let refs = plane_refs(b, &recs, prev, r.offset);
                    if let Some(&(o, nc)) = refs.last() {
                        let (pl, how) = plane_from_ref(b, &recs, o, nc, &by_id, &by_off);
                        if pl.is_some() {
                            add_got(out[li].sketch.as_mut().unwrap(), pl, &format!("plane of the feature using it: {how}"), old_file);
                        }
                    }
                }
            }
        }
        f.fid = fid(b, r);
        let is_sketch = f.kind == "sketch";
        out.push(f);
        if is_sketch {
            last_sketch = Some(out.len() - 1);
        }
    }
    let mut out = place_holes(out);
    edge_lines(sw, &mut out);
    Some(out)
}

/// A Hole Wizard hole's sizes: its named parameters, lengths in mm, angles in degrees.
/// A scale's x, y and z factors: the first three doubles in a row, each a size (between a
/// thousandth and a thousand), after its name.
fn scale_factors(b: &[u8], s: usize, e: usize) -> Option<[f64; 3]> {
    let start = match find_in(b, &[0xff, 0xfe, 0xff], s, s + 40) {
        Some(i) => i + 4 + 2 * *b.get(i + 3)? as usize,
        None => s,
    };
    let stop = e.min(b.len()).saturating_sub(24);
    (start..stop).map(|k| f64s::<3>(b, k)).find(|v| v.iter().all(|x| 1e-3 < *x && *x < 1e3))
}

fn hole_params(b: &[u8], s: usize, e: usize) -> IndexMap<String, Value> {
    let mut out: IndexMap<String, Value> = IndexMap::new();
    let e = e.min(b.len());
    let mut from = s;
    while let Some(j) = find_in(b, &[0xff, 0xfe, 0xff], from, e) {
        if j + 4 > e {
            break;
        }
        let n = b[j + 3];
        if !(0x04..=0x30).contains(&n) {
            from = j + 1;
            continue;
        }
        from = j + 4;
        let name = planes::utf16(&b[(j + 4).min(b.len())..(j + 4 + 2 * n as usize).min(b.len())]);
        let Some(key) = hole_param(&name) else { continue };
        if out.contains_key(key) {
            continue;
        }
        let Some(v) = param_value(b, j) else { continue };
        if !(0.0 < v && v < 10.0) {
            continue;
        }
        let val = if key.ends_with("angle") { py_round(v.to_degrees(), 6) } else { py_round(v * 1000.0, 9) };
        out.insert(key.into(), json!(val));
    }
    // a tapped hole with no drill diameter: its "Thread Major Dia." is the hole as drilled (see the Python)
    let major = out.shift_remove("thread_major");
    if !out.contains_key("diameter") {
        if let Some(v) = major {
            out.insert("diameter".into(), v);
        }
    }
    out
}

/// ISO metric sizes (public standards): (diameter, coarse pitch (ISO 261), ISO 273's medium
/// clearance hole, the Hole Wizard's "normal" fit).
const ISO_METRIC: [(f64, f64, f64); 15] = [
    (1.6, 0.35, 1.8), (2.0, 0.4, 2.4), (2.5, 0.45, 2.9), (3.0, 0.5, 3.4), (3.5, 0.6, 3.9), (4.0, 0.7, 4.5), (5.0, 0.8, 5.5),
    (6.0, 1.0, 6.6), (8.0, 1.25, 9.0), (10.0, 1.5, 11.0), (12.0, 1.75, 13.5), (14.0, 2.0, 15.5), (16.0, 2.0, 17.5),
    (20.0, 2.5, 22.0), (24.0, 3.0, 26.0),
];

/// A hole's diameter (mm) from the size in its Hole Wizard name, where the record names none (see the Python).
/// A 3D sketch's points (metres): the coordinate triples its records write at least twice, in
/// the order first written (see the Python).
fn points_3d(b: &[u8], s: usize, e: usize) -> Vec<[f64; 3]> {
    let mut count: HashMap<&[u8], usize> = HashMap::new();
    let mut order: Vec<[f64; 3]> = Vec::new();
    let e = e.min(b.len());
    for j in s..e.saturating_sub(24).max(s) {
        let d = |k: usize| f64::from_le_bytes(b[j + 8 * k..j + 8 * k + 8].try_into().unwrap());
        let p = [d(0), d(1), d(2)];
        if !p.iter().all(|c| c.is_finite() && c.abs() < 10.0)
            || !p.iter().any(|c| c.abs() > 1e-7)
            || p.iter().any(|c| *c != 0.0 && c.abs() < 1e-7)
            || ((p[0] * p[0] + p[1] * p[1] + p[2] * p[2]).sqrt() - 1.0).abs() < 1e-9
        {
            continue; // (a unit vector is a direction the records keep, not a point)
        }
        let n = count.entry(&b[j..j + 24]).or_insert(0);
        *n += 1;
        if *n == 2 && order.iter().all(|q| ((p[0] - q[0]).powi(2) + (p[1] - q[1]).powi(2) + (p[2] - q[2]).powi(2)).sqrt() > 1e-9) {
            order.push(p);
        }
    }
    order
}

const AXES: [([f64; 3], [f64; 3]); 3] = [([0.0, 0.0, 1.0], [1.0, 0.0, 0.0]), ([0.0, 1.0, 0.0], [0.0, 0.0, 1.0]), ([1.0, 0.0, 0.0], [0.0, 1.0, 0.0])];

/// A hole's 3D placement sketch as a sketch of points on a plane through them (see the Python).
fn placement_from_3d(name: &str, offset: usize, pts: &[[f64; 3]]) -> Option<Sketch> {
    let sub = |a: &[f64; 3], c: &[f64; 3]| [a[0] - c[0], a[1] - c[1], a[2] - c[2]];
    let dot = |a: &[f64; 3], c: &[f64; 3]| a[0] * c[0] + a[1] * c[1] + a[2] * c[2];
    let cross = |a: &[f64; 3], c: &[f64; 3]| [a[1] * c[2] - a[2] * c[1], a[2] * c[0] - a[0] * c[2], a[0] * c[1] - a[1] * c[0]];
    let unit = |a: &[f64; 3]| {
        let l = dot(a, a).sqrt();
        [a[0] / l, a[1] / l, a[2] / l]
    };
    let o = pts[0];
    // the first point farthest from o (as Python's max keeps the first of equals)
    let mut far = pts[0];
    for p in pts {
        if dot(&sub(p, &o), &sub(p, &o)) > dot(&sub(&far, &o), &sub(&far, &o)) {
            far = *p;
        }
    }
    let mut frames: Vec<[[f64; 3]; 3]> = Vec::new();
    if dot(&sub(&far, &o), &sub(&far, &o)) > 1e-18 {
        let x = unit(&sub(&far, &o));
        let mut best = pts[0];
        for p in pts {
            let cp = cross(&x, &sub(p, &o));
            let cb = cross(&x, &sub(&best, &o));
            if dot(&cp, &cp) > dot(&cb, &cb) {
                best = *p;
            }
        }
        let c = cross(&x, &sub(&best, &o));
        if dot(&c, &c) > 1e-18 {
            let n = unit(&c);
            if pts.iter().any(|p| dot(&sub(p, &o), &n).abs() > 1e-7) {
                return None;
            }
            frames.push([x, cross(&n, &x), n]);
        } else {
            for (a, _xa) in AXES {
                if dot(&a, &x).abs() < 0.999 {
                    let k = dot(&a, &x);
                    let n = unit(&[a[0] - k * x[0], a[1] - k * x[1], a[2] - k * x[2]]);
                    frames.push([x, cross(&n, &x), n]);
                }
            }
        }
    } else {
        for (a, xa) in AXES {
            frames.push([xa, cross(&a, &xa), a]);
        }
    }
    let mut sk = Sketch::new(name, offset);
    let [x0, y0, _n0] = frames[0];
    for (k, p) in pts.iter().enumerate() {
        sk.points.insert(k as u32 + 1, (dot(&sub(p, &o), &x0), dot(&sub(p, &o), &y0)));
    }
    for fr in &frames {
        sk.add_plane(&(*fr, o), "a 3D sketch's points, on a plane through them", false);
    }
    Some(sk)
}

fn hole_from_name(name: &str) -> Option<f64> {
    static C: OnceLock<Regex> = OnceLock::new();
    static T: OnceLock<Regex> = OnceLock::new();
    let clearance = C.get_or_init(|| Regex::new(r"^M(\d+(?:\.\d+)?)(?:x(\d+(?:\.\d+)?))?\s+Clearance Hole").unwrap());
    let tapped = T.get_or_init(|| Regex::new(r"^(?:Tap Drill for )?M(\d+(?:\.\d+)?)(?:x(\d+(?:\.\d+)?))?\s+(?:Tapped Hole|Tap)").unwrap());
    let row = |d: f64| ISO_METRIC.iter().find(|r| r.0 == d).copied();
    if let Some(c) = clearance.captures(name) {
        return row(c[1].parse().ok()?).map(|r| r.2);
    }
    if let Some(c) = tapped.captures(name) {
        let d: f64 = c[1].parse().ok()?;
        let p = match c.get(2) {
            Some(m) => m.as_str().parse().ok()?,
            None => row(d)?.1,
        };
        return Some(py_round(d - p, 9));
    }
    None
}

fn transpose(r: &[V3; 3]) -> [V3; 3] {
    let mut t = [[0.0; 3]; 3];
    for (i, row) in t.iter_mut().enumerate() {
        for (j, x) in row.iter_mut().enumerate() {
            *x = r[j][i];
        }
    }
    t
}

/// A hole's placement sketch goes before it; transposed rotations as later candidates; unused
/// plane-less sketches absorbed; profiles with no curves TBD; fillets after what they round.
/// The faces of the part's own solid by the tag SolidWorks puts on each (with help from
/// cadkit-kernel: the Parasolid attribute `FACE_ID_2001`; see the Python `_tagged_faces`):
/// (kind, feature id, local) -> the faces' surface node indices.
fn tagged_faces(part: &crate::parasolid::Partition) -> std::collections::BTreeMap<(i64, i64, i64), Vec<i64>> {
    use crate::parasolid::F;
    let chars = |f: Option<&F>| -> String {
        match f {
            Some(F::List(v)) => v.iter().map(F::ch).collect(),
            Some(F::Char(c)) => c.to_string(),
            _ => String::new(),
        }
    };
    let mut names: HashMap<i64, String> = HashMap::new();
    let mut out: std::collections::BTreeMap<(i64, i64, i64), Vec<i64>> = std::collections::BTreeMap::new();
    for face in part.of_type("FACE") {
        let surf = face.p("surface");
        if part.get(surf).is_none() {
            continue;
        }
        let (mut a, mut hops) = (face.p("attributes_groups"), 0);
        while hops < 64 {
            let Some(at) = part.get(a) else { break };
            hops += 1;
            if at.name != "ATTRIBUTE" {
                break;
            }
            let d = at.p("definition");
            let name = names
                .entry(d)
                .or_insert_with(|| part.get(d).and_then(|dn| part.get(dn.p("identifier"))).map_or(String::new(), |idn| chars(idn.get("string"))))
                .clone();
            if name == "FACE_ID_2001" {
                let mut vals: Vec<i64> = Vec::new();
                if let Some(F::List(ps)) = at.get("fields") {
                    for p in ps {
                        if let Some(nv) = part.get(p.ptr()) {
                            if nv.name == "INT_VALUES" {
                                if let Some(F::List(vs)) = nv.get("values") {
                                    vals.extend(vs.iter().map(F::int));
                                }
                            }
                        }
                    }
                }
                if vals.len() >= 5 {
                    out.entry((vals[0], vals[1], vals[4])).or_default().push(surf);
                }
            }
            a = at.p("next");
        }
    }
    out
}

/// The line two planes meet on, as (a point, a unit direction), mm (see the Python `_plane_line`).
fn plane_line(p1: [f64; 3], n1: [f64; 3], p2: [f64; 3], n2: [f64; 3]) -> Option<[[f64; 3]; 2]> {
    let d = [n1[1] * n2[2] - n1[2] * n2[1], n1[2] * n2[0] - n1[0] * n2[2], n1[0] * n2[1] - n1[1] * n2[0]];
    let dd = d[0] * d[0] + d[1] * d[1] + d[2] * d[2];
    if dd < 1e-12 {
        return None;
    }
    let h1 = (n1[0] * p1[0] + n1[1] * p1[1] + n1[2] * p1[2]) * 1000.0;
    let h2 = (n2[0] * p2[0] + n2[1] * p2[1] + n2[2] * p2[2]) * 1000.0;
    let a = [n2[1] * d[2] - n2[2] * d[1], n2[2] * d[0] - n2[0] * d[2], n2[0] * d[1] - n2[1] * d[0]];
    let b = [d[1] * n1[2] - d[2] * n1[1], d[2] * n1[0] - d[0] * n1[2], d[0] * n1[1] - d[1] * n1[0]];
    let pt = [0, 1, 2].map(|k| (h1 * a[k] + h2 * b[k]) / dd);
    let ln = dd.sqrt();
    Some([pt, [d[0] / ln, d[1] / ln, d[2] / ln]])
}

/// For each fillet and chamfer edge between two flat faces, the line those faces meet on; and a
/// fillet's own faces' axes where all are cylinders (see the Python `_edge_lines`).
fn edge_lines(sw: &SwFile, feats: &mut [Feature]) {
    if !feats.iter().any(|f| (f.kind == "fillet" || f.kind == "chamfer") && !f.edges.is_empty()) {
        return;
    }
    let srcs = crate::step::parasolid_sources(sw);
    let Some((_n, data)) = srcs.first() else { return };
    let Ok(part) = crate::parasolid::read(data) else { return };
    let tagged = tagged_faces(&part);
    if tagged.is_empty() {
        return;
    }
    let planes: HashMap<(i64, i64, i64), Vec<([f64; 3], [f64; 3])>> = tagged
        .iter()
        .map(|(k, v)| (*k, v.iter().filter_map(|s| part.get(*s)).filter(|n| n.name == "PLANE").map(|n| (n.v("pvec"), n.v("normal"))).collect::<Vec<_>>()))
        .filter(|(_, v)| !v.is_empty())
        .collect();
    for f in feats.iter_mut() {
        if !((f.kind == "fillet" || f.kind == "chamfer") && !f.edges.is_empty()) {
            continue;
        }
        // a fillet's own faces (kind 72): each a cylinder whose axis runs along the edge it rounds
        let own: Vec<&crate::parasolid::Node> = tagged
            .iter()
            .filter(|((kind, fid, _), _)| *kind == 72 && *fid == f.fid as i64)
            .flat_map(|(_, v)| v.iter().filter_map(|s| part.get(*s)))
            .collect();
        if f.kind == "fillet" && !own.is_empty() && own.iter().all(|n| n.name == "CYLINDER") {
            f.round_axes = own
                .iter()
                .map(|n| {
                    let p = n.v("pvec");
                    ([p[0] * 1000.0, p[1] * 1000.0, p[2] * 1000.0], n.v("axis"), n.r("radius") * 1000.0)
                })
                .collect();
        }
    }
    // kind 40 an end; a side is 74 on a boss, 83 on a cut (as read on our own samples)
    let plane_of = |r: &FaceRef| -> Option<([f64; 3], [f64; 3])> {
        let kinds: &[i64] = if r.side { &[74, 83] } else { &[40] };
        kinds.iter().find_map(|k| planes.get(&(*k, r.fid as i64, r.v as i64)).map(|v| v[0]))
    };
    for f in feats.iter_mut() {
        if !((f.kind == "fillet" || f.kind == "chamfer") && !f.edges.is_empty()) {
            continue;
        }
        f.edge_lines = f
            .edges
            .iter()
            .map(|(a, b)| match (plane_of(a), plane_of(b)) {
                (Some((p1, n1)), Some((p2, n2))) => plane_line(p1, n1, p2, n2),
                _ => None,
            })
            .collect();
    }
}

fn place_holes(mut out: Vec<Feature>) -> Vec<Feature> {
    let holes: Vec<(String, usize)> = out.iter().filter(|x| x.kind == "hole").map(|x| (x.name.clone(), x.offset)).collect();
    for (name, off) in holes {
        let i = out.iter().position(|x| x.name == name && x.offset == off).unwrap();
        let after: Vec<usize> = (i + 1..(i + 3).min(out.len())).collect();
        let ok = after.first().is_some_and(|&a| out[a].kind == "sketch" && !out[a].sketch.as_ref().unwrap().points.is_empty());
        if !ok {
            out[i].kind = "tbd".into();
            out[i].reason = "hole's placement sketch not found".into();
            continue;
        }
        let second_is_sketch = after.len() > 1 && out[after[1]].kind == "sketch";
        let place = out.remove(after[0]);
        let place_name = place.name.clone();
        out.insert(i, place);
        out[i + 1].profile = Some(place_name);
        if second_is_sketch {
            // (indices unchanged: the placement sketch moved from i + 1 to i)
            out[after[1]].kind = "absorbed".into();
            out[after[1]].reason = String::new();
        }
    }
    for f in out.iter_mut() {
        if f.kind != "sketch" {
            continue;
        }
        let sk = f.sketch.as_mut().unwrap();
        for (fr, how) in sk.planes.clone() {
            if how.contains("rotation") {
                sk.add_plane(&(transpose(&fr.0), fr.1), &format!("{how} (transposed)"), false);
            }
        }
    }
    // a sketch a second feature uses: SolidWorks records an empty copy, `Sketch3<3>`, for it; the
    // feature uses the sketch itself
    let names: HashSet<String> = out.iter().filter(|f| f.kind == "sketch").map(|f| f.name.clone()).collect();
    let mut aliases: Vec<(String, String)> = Vec::new();
    for f in out.iter_mut() {
        if f.kind != "sketch" || !f.sketch.as_ref().is_some_and(|s| s.points.is_empty()) {
            continue;
        }
        let Some(base) = f.name.strip_suffix('>').and_then(|n| n.rsplit_once('<')).filter(|(_, d)| !d.is_empty() && d.bytes().all(|c| c.is_ascii_digit())).map(|(b, _)| b.to_string()) else { continue };
        if base.is_empty() || !names.contains(&base) {
            continue;
        }
        aliases.push((f.name.clone(), base.clone()));
        f.kind = "absorbed".into();
        f.reason = format!("the same sketch as {base}, for a second feature");
    }
    for g in out.iter_mut() {
        if let Some((_, base)) = aliases.iter().find(|(a, _)| g.profile.as_deref() == Some(a.as_str())) {
            g.profile = Some(base.clone());
        }
    }
    // an extrude or revolve whose sketch wasn't found can't be built
    let sketches: HashSet<String> = out.iter().filter(|f| f.kind == "sketch").map(|f| f.name.clone()).collect();
    for f in out.iter_mut() {
        if ["boss", "cut", "revolve", "revcut"].contains(&f.kind.as_str()) && !f.profile.as_ref().is_some_and(|p| sketches.contains(p)) {
            f.kind = "tbd".into();
            f.reason = "the sketch it uses wasn't found".into();
        }
    }
    // one whose sketch has no curves read (an older layout) has nothing to build from
    let empty: HashSet<String> = out
        .iter()
        .filter(|f| f.kind == "sketch" && f.sketch.as_ref().is_some_and(|s| s.lines.is_empty() && s.arcs.is_empty() && s.circles.is_empty()))
        .map(|f| f.name.clone())
        .collect();
    for k in 0..out.len() {
        let solid_before = out[..k].iter().any(|x| ["boss", "cut", "revolve", "revcut", "sweep", "import"].contains(&x.kind.as_str()));
        let f = &mut out[k];
        // (the sketch stays in the tree as read, under its own name)
        if ["boss", "cut"].contains(&f.kind.as_str()) && f.profile.as_ref().is_some_and(|p| empty.contains(p)) {
            if !solid_before {
                // the first solid feature: no model for it to select edges of (see the Python)
                f.kind = "tbd".into();
                f.reason = "its sketch's curves weren't read".into();
            } else {
                // SolidWorks extrudes edges of the model the sketch selects: SolidCraft extrudes a
                // face of the body (its outline projected), the face chosen in the rebuild
                f.from_face = true;
            }
        } else if ["revolve", "revcut", "sweep", "sweepcut"].contains(&f.kind.as_str())
            && (f.profile.as_ref().is_some_and(|p| empty.contains(p)) || f.path.as_ref().is_some_and(|p| empty.contains(p)))
        {
            f.kind = "tbd".into();
            f.reason = "its sketch has no curves of its own (likely model edges it selects)".into();
        }
    }
    let used: HashSet<String> = out.iter().filter_map(|f| f.profile.clone()).collect();
    for f in out.iter_mut() {
        if f.kind == "sketch" && !used.contains(&f.name) && f.sketch.as_ref().unwrap().planes.is_empty() {
            let s = f.sketch.as_mut().unwrap();
            if s.points.is_empty() && s.lines.is_empty() && s.arcs.is_empty() && s.circles.is_empty() {
                // an empty sketch (SolidWorks keeps them): written empty, on the Front plane, so
                // the tree keeps its names and order (see the Python)
                s.add_plane(&(FRONT, [0.0, 0.0, 0.0]), "an empty sketch whose plane isn't read: kept for its place in the tree", false);
            } else {
                f.kind = "absorbed".into();
                f.reason = "sketch plane not read (no feature uses this sketch)".into();
            }
        }
    }
    after_what_it_rounds(out)
}

/// A fillet or chamfer dragged up the tree goes right after the latest feature its edges name.
fn after_what_it_rounds(mut out: Vec<Feature>) -> Vec<Feature> {
    let todo: Vec<(String, usize)> =
        out.iter().filter(|x| (x.kind == "fillet" || x.kind == "chamfer") && !x.edges.is_empty()).map(|x| (x.name.clone(), x.offset)).collect();
    for (name, off) in todo {
        let mut pos: HashMap<u32, usize> = HashMap::new();
        for (i, x) in out.iter().enumerate() {
            if x.kind != "sketch" {
                pos.insert(x.fid, i);
            }
        }
        let here = out.iter().position(|x| x.name == name && x.offset == off).unwrap();
        let f = &out[here];
        let named: HashSet<u32> = f.edges.iter().chain(f.edge_ends.iter()).flat_map(|e| [e.0.fid, e.1.fid]).collect();
        let latest = named.iter().filter(|n| **n != f.fid).filter_map(|n| pos.get(n)).copied().max();
        if let Some(latest) = latest {
            if latest > here {
                let f = out.remove(here);
                out.insert(latest, f); // (latest moved down one when f was taken out)
            }
        }
    }
    out
}
