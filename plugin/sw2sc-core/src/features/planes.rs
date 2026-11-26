//! Planes: where a sketch or feature sits (port of the plane readers in `sw2sc/features.py`).

use std::collections::HashMap;
use std::sync::OnceLock;

use regex::bytes::Regex;

use super::{f64s, find_in, u16_at, u32_at, Frame, V3, FRONT};
use crate::archive::Record;

/// Where a record's data starts (past its tag, or its new-class header).
pub fn data_start(b: &[u8], r: &Record) -> usize {
    data_start_at(b, r.offset, r.new_class)
}

pub fn data_start_at(b: &[u8], off: usize, new_class: bool) -> usize {
    off + if new_class { 6 + u16_at(b, off + 4) as usize } else { 2 }
}

/// The name of a feature record: its node tag, then `FF FE FF`, u8 length, UTF-16.
pub fn name(b: &[u8], r: &Record) -> Option<String> {
    let s = data_start(b, r);
    // (the node tag's high byte is 0x81 and up where class numbers run past 255)
    if b.get(s + 1).map_or(true, |x| x & 0x80 == 0) || b.get(s + 2..s + 5) != Some(&[0xff, 0xfe, 0xff][..]) {
        return None;
    }
    let n = *b.get(s + 5)? as usize;
    if n == 0 {
        return None;
    }
    Some(utf16(&b[(s + 6).min(b.len())..(s + 6 + 2 * n).min(b.len())]))
}

pub fn utf16(b: &[u8]) -> String {
    let units: Vec<u16> = b.chunks_exact(2).map(|c| u16::from_le_bytes([c[0], c[1]])).collect();
    String::from_utf16_lossy(&units)
}

fn unitish(v: &[f64]) -> bool {
    v.iter().all(|x| x.abs() <= 1.0000001)
}

/// Offsets of 9 doubles forming 3 orthonormal axes (a rotation), from `start` up to `end`.
pub fn triads(b: &[u8], start: usize, end: usize) -> impl Iterator<Item = usize> + '_ {
    let stop = end.min(b.len().saturating_sub(96));
    (start..stop.max(start)).filter(move |&i| {
        let v: [f64; 9] = f64s(b, i);
        if !unitish(&v) {
            return false;
        }
        let r = [[v[0], v[1], v[2]], [v[3], v[4], v[5]], [v[6], v[7], v[8]]];
        r.iter().all(|a| (a.iter().map(|c| c * c).sum::<f64>() - 1.0).abs() < 1e-9)
            && [(0, 1), (0, 2), (1, 2)].iter().all(|&(a, c)| dot(&r[a], &r[c]).abs() < 1e-9)
    })
}

pub fn dot(a: &V3, b: &V3) -> f64 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}

pub fn cross(a: &V3, b: &V3) -> V3 {
    [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
}

/// The rotation and translation of 12 doubles at `t`.
pub fn frame_at(b: &[u8], t: usize) -> Frame {
    let v: [f64; 12] = f64s(b, t);
    ([[v[0], v[1], v[2]], [v[3], v[4], v[5]], [v[6], v[7], v[8]]], [v[9], v[10], v[11]])
}

/// (plane feature id, offset after it) of a moCompRefPlane_c object: tag, `02 00`, 41 zero bytes,
/// [16 x FF, zeros, (2018+) a version stamp], u32 id.
pub fn plane_record(b: &[u8], off: usize, is_new: bool) -> Option<(u32, usize)> {
    let mut i = data_start_at(b, off, is_new);
    // the sub-record's class tag: any class number (high bit set; numbers past 255 give 0x81…)
    if i + 4 > b.len() || b[i + 1] & 0x80 == 0 || b[i + 2..i + 4] != [0x02, 0x00] {
        return None;
    }
    i += 4;
    let z = i;
    while i < b.len() && b[i] == 0 {
        i += 1;
    }
    // some files set a flag byte (01) inside the zero run, ahead of the FF block
    if i < b.len() && b[i] == 1 {
        let mut j = i + 1;
        while j < b.len() && b[j] == 0 {
            j += 1;
        }
        if j - z >= 40 && b.get(j..j + 16) == Some(&[0xff; 16][..]) {
            i = j;
        } else if j - z >= 40 && b.get(j..j + 4) == Some(&[0xff; 4][..]) {
            // no FF block: the id -1 straight after the zero run, a sketch on a face
            return Some((0xFFFF_FFFF, j + 4));
        }
    }
    if i - z < 40 {
        return None;
    }
    if b.get(i..i + 16) == Some(&[0xff; 16][..]) {
        i += 16;
        while i < b.len() && b[i] == 0 {
            i += 1;
        }
        if b.get(i..i + 4) == Some(&[0xff; 4][..]) {
            return Some((0xFFFF_FFFF, i + 4));
        }
        let mut v = u32_at(b, i);
        if (7000..=40000).contains(&v) && v % 1000 == 0 {
            // version stamp
            i += 4;
            v = u32_at(b, i);
        }
        return Some((v, i + 4));
    }
    Some((u32_at(b, i), i + 4))
}

pub type ById = HashMap<u32, Frame>;
pub type ByOff = std::collections::BTreeMap<usize, Frame>;

/// Feature id -> frame of every named plane, and offset -> the same for every plane object (also
/// unnamed ones). A plane square to the model stores no frame.
pub fn plane_frames(b: &[u8], recs: &[Record]) -> (ById, ByOff) {
    let (mut by_id, mut by_off) = (ById::new(), ByOff::new());
    for r in recs {
        if r.cls != "moRefPlane_c" {
            continue;
        }
        let s = data_start(b, r);
        let Some(i) = find_in(b, &[0xff, 0xfe, 0xff], s, s + 40) else { continue };
        let end = i + 4 + 2 * *b.get(i + 3).unwrap_or(&0) as usize;
        let ft = match triads(b, end, end + 700).next() {
            Some(t) => frame_at(b, t),
            None => (FRONT, [0.0; 3]),
        };
        by_off.insert(r.offset, ft);
        if let Some(tail) = b.get(end..end + 10) {
            if tail[..7] == [0u8; 7] && (tail[7] == 0x40 || tail[7] == 0xC0) {
                by_id.insert(u16_at(tail, 8) as u32, ft);
            }
        }
    }
    (by_id, by_off)
}

/// A face-plane record's data at s0: origin, the face's normal, a flag byte, then the sketch's
/// x, y and z axes. The sketch faces out of the face: its normal is the face's, y = normal x x.
pub fn face_frame_at(b: &[u8], s0: usize) -> Option<Got> {
    if s0 + 121 > b.len() {
        return None;
    }
    let d = |o: usize| super::f64_at(b, s0 + o);
    let origin = [d(0), d(8), d(16)];
    let normal = [d(24), d(32), d(40)];
    let x = [d(49), d(57), d(65)];
    let y = [d(73), d(81), d(89)];
    let z = [d(97), d(105), d(113)];
    let unit = |v: &V3| unitish(v) && (v.iter().map(|c| c * c).sum::<f64>() - 1.0).abs() < 1e-6;
    if !(unit(&x) && unit(&y) && unit(&z) && unit(&normal) && dot(&x, &y).abs() < 1e-6
        && origin.iter().all(|c| c.abs() < 100.0))
    {
        return None;
    }
    let n = normal;
    let y2 = cross(&n, &x);
    let first = ([x, y2, n], origin);
    // the record's own axes: where its z points into the part its y is the other way from y2,
    // and some files' sketches are drawn in it: a second candidate, the rebuild check chooses
    if dot(&y, &y2) < 0.0 {
        // and the first turned half round in its plane (NIST CTC 03's Sketch3 on a side face is
        // drawn so: x the other way, its normal the face's)
        let turned = ([x.map(|c| -c), y2.map(|c| -c), n], origin);
        return Some(Got::Many(vec![first, ([x, y, cross(&x, &y)], origin), turned]));
    }
    Some(Got::One(first))
}

/// A face record whose axes aren't stored (some versions keep only the face's origin and normal,
/// then a box): the sketch's x axis along each world axis projected onto the face, both ways, as
/// candidate frames for the rebuild check to choose between.
pub fn face_candidates(b: &[u8], recs: &[Record], after: usize, end: usize) -> Vec<Frame> {
    let hi = (after + 1500).min(end);
    let mut starts: Vec<usize> = recs
        .iter()
        .filter(|r| after <= r.offset && r.offset <= hi && r.cls == "moFaceRefPlnData_c")
        .take(1)
        .map(|r| data_start(b, r))
        .collect();
    if starts.is_empty() {
        // its class not named (the numbering drifts): the first unit vector after the reference
        // is the face's normal, the three doubles before it its origin
        let stop = hi.min(b.len().saturating_sub(24));
        for k in (after + 24)..stop.max(after + 24) {
            let n: [f64; 3] = f64s(b, k);
            if unitish(&n) && (n.iter().map(|c| c * c).sum::<f64>() - 1.0).abs() < 1e-9 {
                starts.push(k - 24);
                break;
            }
        }
    }
    let Some(&s0) = starts.first() else { return vec![] };
    if s0 + 48 > b.len() {
        return vec![];
    }
    let v: [f64; 6] = f64s(b, s0);
    let origin = [v[0], v[1], v[2]];
    let n = [v[3], v[4], v[5]];
    if (n.iter().map(|c| c * c).sum::<f64>() - 1.0).abs() > 1e-6 || origin.iter().any(|c| c.abs() >= 100.0) {
        return vec![];
    }
    let mut out = Vec::new();
    for a in FRONT {
        let dt = dot(&a, &n);
        let x = [a[0] - dt * n[0], a[1] - dt * n[1], a[2] - dt * n[2]];
        let ln = x.iter().map(|c| c * c).sum::<f64>().sqrt();
        if ln < 0.5 {
            continue; // (nearly) along the normal
        }
        let x = [x[0] / ln, x[1] / ln, x[2] / ln];
        for sgn in [1.0, -1.0] {
            let xs = [sgn * x[0], sgn * x[1], sgn * x[2]];
            out.push(([xs, cross(&n, &xs), n], origin));
        }
    }
    out
}

/// A plane on a face (moFaceRefPlnData_c after a -1 plane reference). Found by its class, or else
/// by its layout, for files where stray bytes have thrown the numbering off.
pub fn face_plane(b: &[u8], recs: &[Record], after: usize) -> Option<Got> {
    for r in recs {
        if r.offset < after {
            continue;
        }
        if r.offset > after + 1500 {
            break;
        }
        if r.cls == "moFaceRefPlnData_c" {
            return face_frame_at(b, data_start(b, r));
        }
    }
    let stop = (after + 1500).min(b.len().saturating_sub(121));
    (after..stop.max(after)).find_map(|s0| face_frame_at(b, s0))
}

/// A plane object after a -1 plane reference that stores only its origin and unit normal
/// (`moRefPlane_c`: origin, normal, a flag byte, no axes). The sketch's axes aren't stored, so the
/// standard plane's for that normal and its mirror are both offered and the rebuild check chooses.
pub fn origin_normal_plane(b: &[u8], recs: &[Record], after: usize) -> Vec<Frame> {
    let Some(r) = recs.iter().find(|r| after <= r.offset && r.offset < after + 40 && r.cls == "moRefPlane_c") else { return vec![] };
    let end = recs.iter().find(|x| x.offset > r.offset).map_or(r.offset + 600, |x| x.offset);
    let stop = end.min(r.offset + 600).min(b.len().saturating_sub(49));
    for s0 in r.offset..stop.max(r.offset) {
        let o: [f64; 3] = f64s(b, s0);
        let n: [f64; 3] = f64s(b, s0 + 24);
        if !o.iter().chain(n.iter()).all(|c| !c.is_nan() && c.abs() < 100.0) || (n.iter().map(|c| c * c).sum::<f64>() - 1.0).abs() > 1e-9 {
            continue;
        }
        if o.iter().any(|&c| c != 0.0 && c.abs() < 1e-300) {
            continue; // denormals: not a coordinate
        }
        let mut k = 0;
        for a in 1..3 {
            if n[a].abs() > n[k].abs() {
                k = a;
            }
        }
        if (n[k].abs() - 1.0).abs() > 1e-9 || o[k] == 0.0 || o[k].abs() < 1e-12 || ![0u8, 1, 0x80].contains(&b[s0 + 48]) {
            continue;
        }
        let sg = if n[k] > 0.0 { 1.0 } else { -1.0 };
        let x = if k == 0 { [0.0, 0.0, -sg] } else { [sg, 0.0, 0.0] };
        let mx = [-x[0], -x[1], -x[2]];
        // the first that reads is the record's; later ones are the same doubles read shifted
        return vec![([x, cross(&n, &x), n], o), ([mx, cross(&n, &mx), n], o)];
    }
    vec![]
}

/// A plane read: one frame, or candidates to try.
#[derive(Clone, Debug)]
pub enum Got {
    One(Frame),
    Many(Vec<Frame>),
}

fn next_by_off(by_off: &ByOff, after: usize) -> Option<Frame> {
    by_off.range(after..after + 400).next().map(|(_, f)| *f)
}

/// The plane reference written right before recs[k] (a sketch or a feature), read.
pub fn plane_before(b: &[u8], recs: &[Record], k: usize, by_id: &ById, by_off: &ByOff) -> (Option<Got>, String) {
    match ref_before(recs, k) {
        Some(j) => plane_from_ref(b, recs, recs[j].offset, recs[j].new_class, by_id, by_off),
        None => (None, "no plane reference before it".into()),
    }
}

fn ref_before(recs: &[Record], k: usize) -> Option<usize> {
    let mut j = k as isize - 1;
    while j >= 0 && recs[j as usize].cls.starts_with("pre") && recs[k].offset - recs[j as usize].offset < 600 {
        j -= 1;
    }
    if j < 0 || recs[j as usize].cls != "moCompRefPlane_c" || recs[k].offset - recs[j as usize].offset >= 600 {
        return None;
    }
    Some(j as usize)
}

pub fn plane_from_ref(b: &[u8], recs: &[Record], off: usize, new_class: bool, by_id: &ById, by_off: &ByOff) -> (Option<Got>, String) {
    let Some((pid, after)) = plane_record(b, off, new_class) else {
        return (None, "plane reference not read".into());
    };
    if let Some(t) = triads(b, after, after + 200).next() {
        return (Some(Got::One(frame_at(b, t))), "rotation in the plane reference".into());
    }
    if pid == 0xFFFF_FFFF {
        if let Some(g) = face_plane(b, recs, after) {
            return (Some(g), "face the sketch is on".into());
        }
        if let Some(f) = next_by_off(by_off, after) {
            return (Some(Got::One(f)), "plane object after the reference".into());
        }
        let c = face_candidates(b, recs, after, after + 1500);
        if !c.is_empty() {
            return (Some(Got::Many(c)), "face the sketch is on, its axes tried".into());
        }
        let on = origin_normal_plane(b, recs, after);
        if !on.is_empty() {
            return (Some(Got::Many(on)), "plane by origin and normal, its axes tried".into());
        }
        return (None, "sketch on a face: plane not read".into());
    }
    match by_id.get(&pid) {
        Some(f) => (Some(Got::One(*f)), format!("plane feature {pid}")),
        None => (None, format!("plane feature {pid} not found")),
    }
}

pub fn ref_shape() -> &'static Regex {
    static R: OnceLock<Regex> = OnceLock::new();
    R.get_or_init(|| Regex::new(r"(?s-u)[\x00-\xff][\x80-\xff][\x00-\xff][\x80-\xff]\x02\x00(?:\x00{40}|\x00{20,39}\x01\x00{1,20})").unwrap())
}

/// Python's `pattern.finditer(b, lo, hi)`: the matches inside b[lo..hi], offsets in b.
pub fn finditer(re: &Regex, b: &[u8], lo: usize, hi: usize) -> Vec<usize> {
    let hi = hi.min(b.len());
    if lo >= hi {
        return vec![];
    }
    re.find_iter(&b[lo..hi]).map(|m| m.start() + lo).collect()
}

/// A plane reference: (offset, brings in its class).
pub type RefAt = (usize, bool);

/// Plane references between two offsets: the records numbered as moCompRefPlane_c, or else
/// anything with their shape (tag, sub-tag, `02 00`, a long zero run) whose plane id reads, for
/// files where stray bytes have thrown the numbering off.
pub fn plane_refs(b: &[u8], recs: &[Record], lo: usize, hi: usize) -> Vec<RefAt> {
    let refs: Vec<RefAt> = recs
        .iter()
        .filter(|x| lo < x.offset && x.offset < hi && x.cls == "moCompRefPlane_c")
        .map(|x| (x.offset, x.new_class))
        .collect();
    if !refs.is_empty() {
        return refs;
    }
    finditer(ref_shape(), b, lo, hi).into_iter().filter(|&o| plane_record(b, o, false).is_some()).map(|o| (o, false)).collect()
}

/// A sketch's plane written inside its own records: a Hole Wizard hole's placement sketch lists
/// its points first, then the plane reference (`moCompRefPlane_c`) and the face it is on.
pub fn plane_inside(b: &[u8], recs: &[Record], s: usize, e: usize, by_id: &ById, by_off: &ByOff) -> (Option<Got>, String) {
    let named: Vec<RefAt> = recs
        .iter()
        .filter(|r| s <= r.offset && r.offset < e && r.cls == "moCompRefPlane_c")
        .map(|r| (r.offset, r.new_class))
        .collect();
    // where the numbering drifts, by their shape (as plane_refs); a named one may not read
    let shaped: Vec<RefAt> = finditer(ref_shape(), b, s, e).into_iter().map(|o| (o, false)).collect();
    let all = named.iter().copied().chain(shaped.into_iter().filter(|x| !named.iter().any(|n| n.0 == x.0)));
    for (off, new_class) in all {
        let Some((pid, after)) = plane_record(b, off, new_class) else { continue };
        if let Some(t) = triads(b, after, after + 200).next() {
            return (Some(Got::One(frame_at(b, t))), "rotation in its plane reference".into());
        }
        if pid == 0xFFFF_FFFF {
            if let Some(g) = face_plane(b, recs, after) {
                return (Some(g), "face it is on (after its points)".into());
            }
            if let Some(f) = next_by_off(by_off, after) {
                return (Some(Got::One(f)), "plane object after its plane reference (after its points)".into());
            }
            // the plane object's frame by its shape (nine orthonormal doubles, a translation),
            // where the numbering drifts and its class isn't named
            if let Some(t) = triads(b, after, (after + 1500).min(e)).next() {
                return (Some(Got::One(frame_at(b, t))), "frame after its plane reference, by shape (after its points)".into());
            }
            let c = face_candidates(b, recs, after, e);
            if !c.is_empty() {
                return (Some(Got::Many(c)), "face it is on (after its points), its axes tried".into());
            }
            let on = origin_normal_plane(b, recs, after);
            if !on.is_empty() {
                return (Some(Got::Many(on)), "plane by origin and normal (after its points), its axes tried".into());
            }
        } else if let Some(f) = by_id.get(&pid) {
            return (Some(Got::One(*f)), format!("plane feature {pid} (after its points)"));
        }
    }
    (None, String::new())
}

/// The plane of the sketch whose record is recs[k]: the plane reference written right before it.
pub fn sketch_plane(b: &[u8], recs: &[Record], k: usize, by_id: &ById, by_off: &ByOff) -> (Option<Got>, String) {
    let Some(j) = ref_before(recs, k) else { return (None, "no plane reference before the sketch".into()) };
    let (got, how) = plane_from_ref(b, recs, recs[j].offset, recs[j].new_class, by_id, by_off);
    // the same reader, worded for a sketch
    let how = match how.as_str() {
        "sketch on a face: plane not read" | "plane reference not read" => how,
        h => h.to_string(),
    };
    (got, how)
}

#[cfg(test)]
mod tests {
    #[test]
    fn plane_record_flag_then_bare_minus_one() {
        let mut b = vec![0x16, 0x81, 0x83, 0x80, 0x02, 0x00];
        b.extend([0u8; 29]);
        b.push(1);
        b.extend([0u8; 11]);
        b.extend([0xffu8; 4]);
        b.extend([0x00, 0x8d]);
        assert_eq!(super::plane_record(&b, 0, false), Some((0xFFFF_FFFF, b.len() - 2)));
    }
}
