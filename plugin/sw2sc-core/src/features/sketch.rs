//! Sketch entities: points, curves, centres, construction lines, dimensions and relations
//! (port of `_read_sketch` and its helpers in `sw2sc/features.py`).

use std::collections::{HashMap, HashSet};
use std::sync::OnceLock;

use indexmap::IndexMap;
use regex::bytes::Regex;

use super::planes::{finditer, utf16};
use super::{f64_at, find_in, u16_at, u32_at, Dim, Handle, Relation, Sketch, TOL};

/// Class tag (`0x8000 | number`) -> class name.
pub type Tags = HashMap<u32, String>;

pub fn class_tags(recs: &[crate::archive::Record]) -> Tags {
    let mut t = Tags::new();
    for r in recs.iter().filter(|r| r.new_class) {
        t.insert(0x8000 | (r.number - 1) as u32, r.cls.clone());
    }
    t
}

const LINE: &str = "sgLineHandle";
const ARC: &str = "sgArcHandle";

fn hypot(a: (f64, f64), c: (f64, f64)) -> f64 {
    (a.0 - c.0).hypot(a.1 - c.1)
}

/// The curves the sketch's region records name, as (kind, curve id): the closed shape
/// SolidWorks made. Each curve is written `<tag> <id> FF FF FF FF 00 00`, the tag being the
/// file's own number for `sgLineHandle` / `sgArcHandle`.
pub fn region_curves(b: &[u8], s: usize, e: usize, tags: &Tags) -> Vec<(String, u16)> {
    let mut out: Vec<(String, u16)> = Vec::new();
    let mut i = find_in(b, b"moSketchRegion_c", s, e);
    while let Some(at) = i {
        let j = at + b"moSketchRegion_c".len();
        let stop = match find_in(b, b"moSketchChain_c", j, e) {
            Some(x) if x > 0 => x,
            _ => e.min(j + 8192),
        };
        let words: Vec<u16> = (j..j.max(stop.saturating_sub(1))).step_by(2).map(|k| u16_at(b, k)).collect();
        for k in 0..words.len().saturating_sub(3) {
            if let Some(cls) = tags.get(&(words[k] as u32)) {
                if (cls == ARC || cls == LINE) && words[k + 1] < 4000 && words[k + 2] == 0xFFFF && words[k + 3] == 0xFFFF {
                    let item = ((if cls == ARC { "arc" } else { "line" }).to_string(), words[k + 1]);
                    if !out.contains(&item) {
                        out.push(item);
                    }
                }
            }
        }
        i = find_in(b, b"moSketchRegion_c", stop, e);
    }
    out
}

/// The points a sketch's `moSketchChain_c` record names, in order: a `u16` count, then that many
/// `u32` point ids.
pub fn chain_points(b: &[u8], s: usize, e: usize) -> Vec<u32> {
    let mut out = Vec::new();
    let Some(i) = find_in(b, b"moSketchChain_c", s, e) else { return out };
    let j = i + b"moSketchChain_c".len();
    let n = u16_at(b, j) as usize;
    if !(0 < n && n < 4096) || j + 2 + 4 * n > b.len() {
        return out;
    }
    for k in 0..n {
        let pid = u32_at(b, j + 2 + 4 * k);
        if pid == 0xFFFF_FFFF {
            return out; // a count that ran past the record: nothing to trust
        }
        out.push(pid);
    }
    out
}

/// Points (u32 id, `FF FF 1F 00`, …, `1E 00`, x, y) and the curves each lies on (handles: class
/// tag or new-class header, u16 curve id, FF FF FF FF, 4 zero bytes). Where the numbering has
/// drifted, handle classes brought in inline here take the tags in order; `learned` carries such
/// tags from sketch to sketch.
pub fn read_sketch(b: &[u8], base: &Tags, sk: &mut Sketch, s: usize, e: usize, mut learned: Option<&mut Tags>) {
    let mut tags = base.clone();
    if let Some(l) = learned.as_deref() {
        tags.extend(l.iter().map(|(k, v)| (*k, v.clone())));
    }
    let mut inline: Vec<String> = Vec::new();
    let mut unknown: IndexMap<(u32, u16), Vec<u32>> = IndexMap::new();
    let mut curves: IndexMap<(String, u16), Vec<u32>> = IndexMap::new();
    let mut plain: Vec<u32> = Vec::new();
    // every handle in a point's list: (tag or None, class brought in, curve id, point)
    let mut entries: Vec<(Option<u32>, Option<String>, u16, u32)> = Vec::new();
    let mut pts_order: Vec<u32> = Vec::new();
    let e2 = e.min(b.len());
    let mut from = s;
    while let Some(i) = find_in(b, &[0xff, 0xff, 0x1f, 0x00], from, e2) {
        from = i + 1;
        let Some(j) = find_in(b, &[0x1e, 0x00], i + 30, i + 80) else { continue };
        // the point's x, y follow `F0 3F 1E 00`; newer files put 8 zero bytes before the `1E 00`
        let ok = b.get(j.wrapping_sub(2)..j) == Some(&[0xf0, 0x3f][..])
            || (j >= 10 && b[j - 10..j - 8] == [0xf0, 0x3f] && b[j - 8..j] == [0u8; 8]);
        if j + 22 > b.len() || !ok || i < 4 {
            continue;
        }
        let pid = u32_at(b, i - 4);
        if pid == 0xFFFF_FFFF {
            continue; // positions of dimension text, not points
        }
        let (x, y) = (f64_at(b, j + 2), f64_at(b, j + 10));
        if !(x.abs() < 100.0 && y.abs() < 100.0) {
            continue;
        }
        sk.points.insert(pid, (x, y));
        if i + 18 <= b.len() {
            sk.point_flags.insert(pid, b[i + 17]);
        }
        let mut k = j + 18 + 4;
        let mut n_on = 0;
        pts_order.push(pid);
        for _ in 0..16 {
            let tag: Option<u32>;
            let cname: String;
            if b.get(k..k + 2) == Some(&[0xff, 0xff][..]) {
                let ln = u16_at(b, k + 4) as usize;
                cname = b.get(k + 6..(k + 6 + ln).min(b.len())).map_or(String::new(), |x| x.iter().map(|&c| c as char).collect());
                tag = None; // (a class brought in here: no tag)
                if cname.ends_with("Handle") && !inline.contains(&cname) {
                    inline.push(cname.clone());
                }
                k += 6 + ln;
            } else {
                if k + 2 > b.len() {
                    break;
                }
                let t = u16_at(b, k) as u32;
                if t & 0x8000 == 0 || t == 0xFFFF {
                    break;
                }
                tag = Some(t);
                cname = tags.get(&t).cloned().unwrap_or_default();
                k += 2;
            }
            let cid = u16_at(b, k);
            if b.get(k + 2..k + 6) != Some(&[0xff; 4][..]) {
                break;
            }
            entries.push((tag, if tag.is_none() { Some(cname.clone()) } else { None }, cid, pid));
            if cname == LINE || cname == ARC {
                curves.entry((cname, cid)).or_default().push(pid);
                n_on += 1;
            } else if let Some(t) = tag {
                unknown.entry((t, cid)).or_default().push(pid); // a handle whose class isn't known
            }
            k += 10;
        }
        if n_on == 0 {
            plain.push(pid);
        }
    }
    // Handle tags of no known class: classes brought in inline here take them in order, the
    // earliest class the smallest tag. Checked: a line has two ends.
    let mut by_tag: IndexMap<u32, Vec<(u16, Vec<u32>)>> = IndexMap::new();
    for ((t, cid), ps) in &unknown {
        by_tag.entry(*t).or_default().push((*cid, ps.clone()));
    }
    let order: Vec<String> = inline.iter().filter(|c| *c == LINE || *c == ARC).cloned().collect();
    // The same where the numbering is off by a class or so: a tag it gives a class this sketch
    // brings in is no more certain than one it doesn't know.
    let curve_cls = |c: Option<&String>| c.is_some_and(|c| c == LINE || c == ARC);
    let mut listed: IndexMap<u32, IndexMap<u16, Vec<u32>>> = IndexMap::new();
    for (t, _c, cid, pid) in &entries {
        if let Some(t) = t {
            listed.entry(*t).or_default().entry(*cid).or_default().push(*pid);
        }
    }
    let learned_has = |t: &u32| learned.as_deref().is_some_and(|l| l.contains_key(t));
    let mut cand: Vec<u32> = listed
        .keys()
        .filter(|t| !learned_has(t) && !(curve_cls(tags.get(t)) && !order.contains(tags.get(t).unwrap())))
        .copied()
        .collect();
    cand.sort();
    let distinct = |ps: &Vec<u32>| ps.iter().collect::<HashSet<_>>().len();
    if !order.is_empty()
        && cand.len() == order.len()
        && cand.iter().any(|t| curve_cls(tags.get(t)))
        && !cand.iter().zip(&order).any(|(t, c)| c == LINE && listed[t].values().any(|ps| distinct(ps) > 2))
    {
        let give: HashMap<u32, String> = cand.iter().copied().zip(order.iter().cloned()).collect();
        curves = IndexMap::new();
        for (t, c, cid, pid) in &entries {
            let nm = match t {
                None => c.clone().unwrap_or_default(),
                Some(t) => give.get(t).cloned().or_else(|| tags.get(t).cloned()).unwrap_or_default(),
            };
            if nm == LINE || nm == ARC {
                curves.entry((nm, *cid)).or_default().push(*pid);
            }
        }
        tags.extend(give);
        let on: HashSet<u32> = curves.values().flatten().copied().collect();
        plain = pts_order.iter().filter(|x| !on.contains(x)).copied().collect();
        by_tag = IndexMap::new();
    }
    let mut utags: Vec<u32> = by_tag.keys().copied().collect();
    utags.sort();
    if !order.is_empty() && utags.len() == order.len() {
        let bad = utags.iter().zip(&order).any(|(t, c)| c == LINE && by_tag[t].iter().any(|(_c, ps)| distinct(ps) > 2));
        if !bad {
            for (t, cname) in utags.iter().zip(&order) {
                for (cid, ps) in &by_tag[t] {
                    curves.entry((cname.clone(), *cid)).or_default().extend(ps);
                }
                tags.insert(*t, cname.clone());
            }
            let on: HashSet<u32> = by_tag.values().flat_map(|items| items.iter().flat_map(|(_c, ps)| ps.iter().copied())).collect();
            plain.retain(|x| !on.contains(x));
            by_tag = IndexMap::new();
        }
    }
    // an unknown handle tag every curve of which has one point only is a circle's
    for (t, items) in &by_tag {
        if items.iter().all(|(_c, ps)| distinct(ps) == 1) {
            for (cid, ps) in items {
                let key = (ARC.to_string(), *cid);
                if !curves.contains_key(&key) {
                    curves.insert(key, ps.clone());
                    if let Some(pos) = plain.iter().position(|x| *x == ps[0]) {
                        plain.remove(pos);
                    }
                    tags.insert(*t, ARC.into());
                }
            }
        }
    }
    if let Some(l) = learned.as_deref_mut() {
        for (t, v) in &tags {
            if base.get(t) != Some(v) && v.ends_with("Handle") {
                l.insert(*t, v.clone());
            }
        }
    }
    sk.region = region_curves(b, s, e, &tags);
    sk.chain = chain_points(b, s, e);
    place_curves(sk, &curves, &plain);
    let partial: IndexMap<u16, Vec<u32>> = sk_partial(&curves);
    read_segments(b, sk, s, e, &partial);
    // a line read with one end only is left out and noted
    let (one_ended, rest): (Vec<String>, Vec<String>) = sk.problems.drain(..).partition(|x| is_one_end(x));
    sk.problems = rest;
    sk.dropped.extend(one_ended);
    tangent_centres(sk);
    alternative_centres(sk);
    if tags.values().any(|v| v == "sgTextHandle") && find_in(b, b"sgTextHandle", s, e).is_some() {
        // the words, size and place are stored, not the letters' outlines (see the Python)
        sk.problems.push("sketch text: SolidWorks keeps the words, size and place but not the letters' shapes, so SolidCraft's own lettering can't be matched to the solid exactly".into());
    }
    read_dimensions(b, &tags, sk, s, e);
    dimensioned_circles(sk);
    read_relations(b, &tags, sk, s, e);
    centres_from_relations(sk);
}

fn is_one_end(x: &str) -> bool {
    // `line \d+ has 1 end points`
    x.strip_prefix("line ")
        .and_then(|r| r.strip_suffix(" has 1 end points"))
        .is_some_and(|d| !d.is_empty() && d.bytes().all(|c| c.is_ascii_digit()))
}

fn sk_partial(curves: &IndexMap<(String, u16), Vec<u32>>) -> IndexMap<u16, Vec<u32>> {
    let mut p = IndexMap::new();
    for ((cn, cid), ps) in curves {
        let ps = dedup(ps);
        if cn == LINE && ps.len() != 2 {
            p.insert(*cid, ps);
        }
    }
    p
}

fn dedup(ps: &[u32]) -> Vec<u32> {
    let mut out: Vec<u32> = Vec::new();
    for p in ps {
        if !out.contains(p) {
            out.push(*p);
        }
    }
    out
}

/// Lines, arcs and circles from the curves read, with each arc's and circle's centre.
fn place_curves(sk: &mut Sketch, curves: &IndexMap<(String, u16), Vec<u32>>, plain: &[u32]) {
    let p = sk.points.clone();
    let d = |a: u32, c: u32| hypot(p[&a], p[&c]);
    let mut used: HashSet<u32> = HashSet::new();
    let line_ends: Vec<(u32, u32)> = curves
        .iter()
        .filter(|((cn, _), ps)| cn == LINE && dedup(ps).len() == 2)
        .map(|(_, ps)| {
            let v = dedup(ps);
            (v[0], v[1])
        })
        .collect();
    // a circle's point and its centre are numbered one after the other
    let one_end: HashSet<u32> =
        curves.iter().filter(|((cn, _), ps)| cn == ARC && dedup(ps).len() == 1).map(|(_, ps)| ps[0]).collect();
    let on_arc: HashSet<u32> = curves.iter().filter(|((cn, _), _)| cn == ARC).flat_map(|(_, ps)| ps.iter().copied()).collect();
    let reserved: HashSet<u32> = one_end
        .iter()
        .filter(|q| p.contains_key(&(**q + 1)) && !on_arc.contains(&(**q + 1)) && d(**q, **q + 1) > TOL)
        .map(|q| q + 1)
        .collect();
    let tangent_joins = |c: u32, ends: &[u32]| -> i32 {
        let mut n = 0;
        for &e in ends {
            for &(a2, b2) in &line_ends {
                if e == a2 || e == b2 {
                    let o = if e == a2 { b2 } else { a2 };
                    let (ux, uy) = (p[&o].0 - p[&e].0, p[&o].1 - p[&e].1);
                    let (rx, ry) = (p[&e].0 - p[&c].0, p[&e].1 - p[&c].1);
                    if (ux * rx + uy * ry).abs() <= 1e-6 * ux.hypot(uy) * rx.hypot(ry) {
                        n += 1;
                    }
                }
            }
        }
        n
    };
    let centre_for = |ends: &[u32], used: &HashSet<u32>| -> Option<u32> {
        let top = *ends.iter().max().unwrap();
        if ends.len() == 1 && reserved.contains(&(top + 1)) {
            return Some(top + 1);
        }
        let by_dist = |v: &mut Vec<u32>, to: u32| v.sort_by(|a, c| d(*a, to).total_cmp(&d(*c, to)));
        if ends.len() == 1 && one_end.contains(&(top + 1)) {
            let mut near: Vec<u32> = p.keys().copied().filter(|c| !on_arc.contains(c) && !reserved.contains(c) && d(*c, top) > TOL).collect();
            by_dist(&mut near, top);
            if let Some(n) = near.first() {
                return Some(*n);
            }
        }
        if ends.len() == 1 {
            let mut cands: Vec<u32> = plain.iter().copied().filter(|c| *c > top && !used.contains(c) && !reserved.contains(c) && d(*c, ends[0]) > TOL).collect();
            cands.sort();
            if cands.is_empty() {
                cands = plain.iter().copied().filter(|c| *c > top && d(*c, ends[0]) > TOL).collect();
                cands.sort();
            }
            if cands.is_empty() {
                let mut near: Vec<u32> = plain.iter().copied().filter(|c| !used.contains(c) && d(*c, ends[0]) > TOL).collect();
                by_dist(&mut near, ends[0]);
                if near.is_empty() {
                    near = plain.iter().copied().filter(|c| d(*c, ends[0]) > TOL).collect();
                    by_dist(&mut near, ends[0]);
                }
                return near.first().copied();
            }
            return Some(cands[0]);
        }
        let eq = |c: u32| (d(c, ends[0]) - d(c, ends[1])).abs() < TOL && d(c, ends[0]) > TOL;
        let mut cands: Vec<u32> = plain.iter().copied().filter(|c| !used.contains(c) && eq(*c)).collect();
        if cands.is_empty() {
            cands = plain.iter().copied().filter(|c| eq(*c)).collect();
        }
        if cands.is_empty() {
            cands = p.keys().copied().filter(|c| !ends.contains(c) && eq(*c)).collect();
        }
        cands.into_iter().min_by(|a, c| {
            let ka = (-tangent_joins(*a, ends), *a <= top, d(*a, ends[0]), *a);
            let kc = (-tangent_joins(*c, ends), *c <= top, d(*c, ends[0]), *c);
            ka.0.cmp(&kc.0).then(ka.1.cmp(&kc.1)).then(ka.2.total_cmp(&kc.2)).then(ka.3.cmp(&kc.3))
        })
    };
    let mut items: Vec<(&(String, u16), &Vec<u32>)> = curves.iter().collect();
    items.sort_by_key(|(_, ps)| *ps.iter().max().unwrap()); // stable, as Python's sorted
    for ((cname, cid), ps) in items {
        let ps = dedup(ps);
        if cname == LINE {
            if ps.len() == 2 {
                sk.lines.push((ps[0], ps[1]));
                sk.curve_of.insert(("line".into(), *cid), format!("l{}", sk.lines.len()));
            } else {
                sk.problems.push(format!("line {cid} has {} end points", ps.len()));
            }
        } else if ps.len() == 1 || ps.len() == 2 {
            let Some(c) = centre_for(&ps, &used) else {
                sk.problems.push(format!("arc {cid}: no centre found (ends {})", py_list(&ps)));
                continue;
            };
            used.insert(c);
            if ps.len() == 2 {
                sk.arcs.push((ps[0], ps[1], c));
                sk.curve_of.insert(("arc".into(), *cid), format!("a{}", sk.arcs.len()));
            } else {
                sk.circles.push((c, d(c, ps[0])));
                sk.curve_of.insert(("arc".into(), *cid), format!("c{}", sk.circles.len()));
            }
        } else {
            sk.problems.push(format!("arc {cid} has {} points", ps.len()));
        }
    }
}

pub fn py_list(v: &[u32]) -> String {
    format!("[{}]", v.iter().map(|x| x.to_string()).collect::<Vec<_>>().join(", "))
}

/// A circle read from one point whose centre wasn't found: a missing point numbered next to the
/// circle's point that a coincident relation (9) puts on a point read is its centre.
/// A circle whose radius is none of the sketch's circle dimensions, where it has some: through
/// the point it was read through, the one point at a dimensioned radius is its centre (see the Python).
fn dimensioned_circles(sk: &mut Sketch) {
    let mut radii: Vec<f64> = sk.dims.iter().filter(|d| d.cls == "sgCircleDim" && d.value != 0.0).map(|d| d.value.abs() / 2.0).collect();
    radii.sort_by(|a, b| a.partial_cmp(b).unwrap());
    radii.dedup();
    if radii.is_empty() {
        return;
    }
    let p = sk.points.clone();
    let d = |a: u32, c: u32| (p[&a].0 - p[&c].0).hypot(p[&a].1 - p[&c].1);
    let mut ids: Vec<u32> = p.keys().copied().collect();
    ids.sort();
    for n in 0..sk.circles.len() {
        let (c, r) = sk.circles[n];
        if radii.iter().any(|rr| (r - rr).abs() <= 1e-9) {
            continue;
        }
        let through: Vec<u32> = ids.iter().copied().filter(|&q| q != c && (d(c, q) - r).abs() <= 1e-9).collect();
        if through.len() != 1 {
            continue;
        }
        let t = through[0];
        let centres: Vec<u32> = sk.circles.iter().enumerate().filter(|(k, _)| *k != n).map(|(_, cc)| cc.0).collect();
        let mut hits: Vec<(u32, f64)> = Vec::new();
        for &q in &ids {
            for &rr in &radii {
                if q != t && q != c && !centres.contains(&q) && (d(q, t) - rr).abs() <= 1e-9 {
                    hits.push((q, rr));
                }
            }
        }
        if hits.len() == 1 {
            sk.circles[n] = hits[0];
        }
    }
}

fn centres_from_relations(sk: &mut Sketch) {
    for pr in sk.problems.clone() {
        let Some(rest) = pr.strip_prefix("arc ") else { continue };
        let Some((cid, ends)) = rest.split_once(": no centre found (ends [") else { continue };
        let Some(ends) = ends.strip_suffix("])") else { continue };
        let (Ok(cid), Ok(end)) = (cid.parse::<u16>(), ends.parse::<u32>()) else { continue };
        let mut at: Option<u32> = None;
        for r in &sk.relations {
            if r.kind != 9 {
                continue;
            }
            for g in &r.groups {
                let ids: Vec<u32> = g.iter().filter(|h| h.cls == "point").map(|h| h.id + 1).collect();
                if ids.len() != 2 {
                    continue;
                }
                for (a, c) in [(ids[0], ids[1]), (ids[1], ids[0])] {
                    if (a + 1 == end || a == end + 1) && !sk.points.contains_key(&a) && sk.points.contains_key(&c) && c != end && at.is_none() {
                        at = Some(c);
                    }
                }
            }
        }
        let Some(at) = at else { continue };
        let r = hypot(sk.points[&at], sk.points[&end]);
        if r < TOL {
            continue;
        }
        sk.problems.retain(|x| *x != pr);
        sk.circles.push((at, r));
        sk.curve_of.insert(("arc".into(), cid), format!("c{}", sk.circles.len()));
    }
}

/// An arc's other possible centre: the mirror of the centre across the chord, kept where no line
/// meets the arc tangentially at either end (a tangency would settle it).
/// An arc whose centre, as read, leaves every line meeting it at a corner, where another point
/// of the sketch is as far from both its ends and makes every one of those lines tangent: that
/// point is its centre (see the Python).
pub fn tangent_centres(sk: &mut Sketch) {
    let p = sk.points.clone();
    let tangent = |e: u32, o: u32, cx: f64, cy: f64| -> bool {
        let (ux, uy) = (p[&o].0 - p[&e].0, p[&o].1 - p[&e].1);
        let (rx, ry) = (p[&e].0 - cx, p[&e].1 - cy);
        (ux * rx + uy * ry).abs() <= 1e-6 * ux.hypot(uy) * rx.hypot(ry)
    };
    let mut ids: Vec<u32> = p.keys().copied().collect();
    ids.sort();
    for n in 0..sk.arcs.len() {
        let (a, c, ctr) = sk.arcs[n];
        let mut meet: Vec<(u32, u32)> = Vec::new();
        for &(la, lb) in &sk.lines {
            for e in [a, c] {
                if e == la || e == lb {
                    meet.push((e, if e == la { lb } else { la }));
                }
            }
        }
        if meet.is_empty() || meet.iter().any(|&(e, o)| tangent(e, o, p[&ctr].0, p[&ctr].1)) {
            continue;
        }
        for &q in &ids {
            if q == a || q == c || q == ctr {
                continue;
            }
            let (qx, qy) = p[&q];
            let da = (p[&a].0 - qx).hypot(p[&a].1 - qy);
            let dc = (p[&c].0 - qx).hypot(p[&c].1 - qy);
            if da > TOL && (da - dc).abs() <= 1e-6 * da && meet.iter().all(|&(e, o)| tangent(e, o, qx, qy)) {
                sk.arcs[n] = (a, c, q);
                break;
            }
        }
    }
}

pub fn alternative_centres(sk: &mut Sketch) {
    let p = &sk.points;
    let mut alts = Vec::new();
    for (n, &(a, c, ctr)) in sk.arcs.iter().enumerate() {
        let ((ax, ay), (bx, by), (cx, cy)) = (p[&a], p[&c], p[&ctr]);
        let chord = (bx - ax).hypot(by - ay);
        if chord < TOL {
            continue;
        }
        let mut tangent = false;
        for &(la, lb) in &sk.lines {
            for e in [a, c] {
                if e == la || e == lb {
                    let o = if e == la { lb } else { la };
                    let (ux, uy) = (p[&o].0 - p[&e].0, p[&o].1 - p[&e].1);
                    let (rx, ry) = (p[&e].0 - cx, p[&e].1 - cy);
                    if (ux * rx + uy * ry).abs() <= 1e-6 * ux.hypot(uy) * rx.hypot(ry) {
                        tangent = true;
                    }
                }
            }
        }
        if tangent {
            continue;
        }
        let (dx, dy) = ((bx - ax) / chord, (by - ay) / chord);
        let t = (cx - ax) * dx + (cy - ay) * dy;
        let (fx, fy) = (ax + t * dx, ay + t * dy);
        let (mx, my) = (2.0 * fx - cx, 2.0 * fy - cy);
        if (mx - cx).hypot(my - cy) > TOL {
            alts.push((n, (mx, my)));
        }
    }
    for (n, m) in alts {
        sk.alt_centres.insert(n, m);
    }
}

/// The sketch with the arcs in `flips` turned about their alternative centre.
pub fn with_centres(sk: &Sketch, flips: &[usize]) -> Sketch {
    let mut s2 = sk.clone();
    for &n in flips {
        if let Some(&m) = sk.alt_centres.get(&n) {
            let pid = 10_000_000 + n as u32; // a point of its own (no record holds the true centre)
            s2.points.insert(pid, m);
            let (a, c, _) = s2.arcs[n];
            s2.arcs[n] = (a, c, pid);
        }
    }
    s2
}

/// Construction lines, from the sketch's segment records (see the Python for the layout). Used
/// only when at least half of a sketch's normal records, and at least two, give the ends of a
/// line or arc already read.
fn read_segments(b: &[u8], sk: &mut Sketch, s: usize, e: usize, partial: &IndexMap<u16, Vec<u32>>) {
    let mut segs: Vec<(u32, u32, u32, u16)> = Vec::new();
    let mut from = s;
    while let Some(i) = find_in(b, &[0xff, 0xff, 0x1f, 0x00], from, e) {
        from = i + 1;
        if i < s + 4 {
            continue;
        }
        let cid = u32_at(b, i - 4);
        if cid > 0xFFFF {
            continue;
        }
        let Some(j) = find_in(b, &[0xf0, 0x3f], i, i + 80) else { continue };
        if b.get(j + 2..j + 4) == Some(&[0x1e, 0x00][..]) || b.get(j + 10..j + 12) == Some(&[0x1e, 0x00][..]) {
            continue; // a point record
        }
        let k = j + 2 + if b.get(j + 2..j + 10) == Some(&[0u8; 8][..]) { 8 } else { 0 };
        if k + 6 > b.len() {
            continue;
        }
        let (a, c, flag) = (u16_at(b, k) as u32, u16_at(b, k + 2) as u32, u16_at(b, k + 4));
        segs.push((cid, a + 1, c + 1, flag));
    }
    let key2 = |x: u32, y: u32| if x <= y { (x, y) } else { (y, x) };
    let pairs: HashSet<(u32, u32)> = sk.lines.iter().map(|l| key2(l.0, l.1)).chain(sk.arcs.iter().map(|a| key2(a.0, a.1))).collect();
    let normal: Vec<(u32, u32)> = segs.iter().filter(|x| x.3 == 1).map(|x| key2(x.1, x.2)).collect();
    let good = normal.iter().filter(|pr| pairs.contains(pr)).count();
    if good < 2 || 2 * good < normal.len() {
        return;
    }
    for (cid, a, c, flag) in segs {
        if a == c || !sk.points.contains_key(&a) || !sk.points.contains_key(&c) || hypot(sk.points[&a], sk.points[&c]) < TOL {
            continue;
        }
        let key = ("line".to_string(), cid as u16);
        if let Some(cur) = sk.curve_of.get(&key).cloned() {
            let n: usize = cur[1..].parse::<usize>().unwrap_or(1) - 1;
            if flag == 0 && cur.starts_with('l') && key2(sk.lines[n].0, sk.lines[n].1) == key2(a, c) {
                sk.construction.insert(n);
            }
            continue;
        }
        if let Some(pp) = partial.get(&(cid as u16)) {
            if pp.iter().all(|x| *x == a || *x == c) {
                sk.lines.push((a, c));
                sk.curve_of.insert(key, format!("l{}", sk.lines.len()));
                let gone = format!("line {cid} has {} end points", pp.len());
                sk.problems.retain(|pr| *pr != gone);
                if flag == 0 {
                    sk.construction.insert(sk.lines.len() - 1);
                }
                continue;
            }
        }
        if flag != 0 || sk.lines.iter().any(|l| key2(l.0, l.1) == key2(a, c)) {
            continue;
        }
        sk.lines.push((a, c));
        sk.construction.insert(sk.lines.len() - 1);
        sk.curve_of.insert(key, format!("l{}", sk.lines.len()));
    }
}

const DIM_CLASSES: [&str; 8] = [
    "sgPntPntDist", "sgPntPntHorDist", "sgPntPntVertDist", "sgCircleDim", "sgPntLineDist", "sgLLDist", "sgAnglDim",
    "sgSkOffsetDim",
];

/// The value of a dimension's parameter record starting at s (see the Python for the layout), in
/// metres or radians.
pub fn param_value(b: &[u8], s: usize) -> Option<f64> {
    let mut i = find_in(b, &[0xff, 0xfe, 0xff], s, s + 16)?;
    i += 4 + 2 * *b.get(i + 3)? as usize + 8;
    if b.get(i..i + 4) != Some(&[0xff; 4][..]) {
        return None;
    }
    i += 8;
    if b.get(i..i + 3) == Some(&[0xff, 0xfe, 0xff][..]) {
        i += 4 + 2 * *b.get(i + 3)? as usize;
    }
    if b.get(i..i + 2) != Some(&[0, 0][..]) {
        return None;
    }
    (i + 10 <= b.len()).then(|| f64_at(b, i + 2))
}

fn rel_head() -> &'static Regex {
    static R: OnceLock<Regex> = OnceLock::new();
    R.get_or_init(|| Regex::new(r"(?s-u)([\x00-\xff])\x00\x00\x00\x02\x00\x00\x00(?:\x00\x00){1,2}\xfe\xff\x00\x00").unwrap())
}

fn handle_re() -> &'static Regex {
    static R: OnceLock<Regex> = OnceLock::new();
    R.get_or_init(|| Regex::new(r"(?s-u)([\x00-\xff][\x80-\xff])([\x00-\xff]{2})\xff\xff\xff\xff\x00\x00\x00\x00").unwrap())
}

/// The sketch's dimensions: each a record of a dimension class, its parameter (name, value) and
/// handles naming the points or curves it measures. The last record of each name wins.
fn read_dimensions(b: &[u8], tags: &Tags, sk: &mut Sketch, s: usize, e: usize) {
    let e = e.min(b.len());
    let mut starts: Vec<(usize, String, usize)> = Vec::new();
    let mut from = s;
    while let Some(i) = find_in(b, &[0xff, 0xff, 0x01, 0x00], from, e) {
        from = i + 1;
        if b.get(i + 5) != Some(&0) || i + 6 > e {
            continue;
        }
        let n = b[i + 4] as usize;
        let name: String = b[(i + 6).min(b.len())..(i + 6 + n).min(b.len())].iter().map(|&c| c as char).collect();
        if DIM_CLASSES.contains(&name.as_str()) {
            starts.push((i, name, i + 6 + n));
        }
    }
    let tag_of: HashMap<&str, u32> = tags.iter().map(|(k, v)| (v.as_str(), *k)).collect();
    for cls in DIM_CLASSES {
        let Some(&t) = tag_of.get(cls) else { continue };
        if t > 0xFFFF {
            continue;
        }
        let mut needle = (t as u16).to_le_bytes().to_vec();
        needle.extend_from_slice(&[0, 0, 0, 0]);
        let mut from = s;
        while let Some(i) = find_in(b, &needle, from, e) {
            // (Python's finditer: matches don't overlap)
            from = i + needle.len();
            starts.push((i, cls.to_string(), i + 2));
        }
    }
    starts.sort();
    let mut found: IndexMap<String, (String, f64, Vec<Handle>)> = IndexMap::new();
    for n in 0..starts.len() {
        let (i, ref cls, data) = starts[n];
        let mut end = if n + 1 < starts.len() { starts[n + 1].0 } else { e.min(i + 600) };
        let Some(j) = find_in(b, &[0xff, 0xfe, 0xff], data, data + 40) else { continue };
        let ln = *b.get(j + 3).unwrap_or(&0) as usize;
        let nm = utf16(&b[(j + 4).min(b.len())..(j + 4 + 2 * ln).min(b.len())]);
        let Some(v) = param_value(b, j.saturating_sub(2)) else { continue };
        if nm.is_empty() {
            continue;
        }
        let mut handles = Vec::new();
        if j < end {
            if let Some(m) = rel_head().find(&b[j..end.min(b.len())]) {
                end = j + m.start();
            }
        }
        let mut k = j;
        while k + 12 < end && k + 12 <= b.len() {
            if b[k + 1] == 0x80 && b[k + 4..k + 8] == [0xff; 4] && b[k + 8..k + 12] == [0u8; 4] {
                let cname = tags.get(&(u16_at(b, k) as u32)).cloned().unwrap_or_default();
                handles.push(Handle { cls: cname, id: u16_at(b, k + 2) as u32 });
                k += 12;
            } else {
                k += 1;
            }
        }
        found.insert(nm, (cls.clone(), v, handles));
    }
    sk.dims = found.into_iter().map(|(nm, (cls, v, h))| Dim { name: nm, cls, value: v, handles: h }).collect();
}

/// The sketch's relations: u32 type, u32 2, 4 zero bytes, `FE FF 00 00`, then handles to the
/// entities related, in groups that end with an `FFFF FFFF` pair. Stored raw: (type, groups of
/// (kind, id)) with kind point / line / arc.
fn read_relations(b: &[u8], tags: &Tags, sk: &mut Sketch, s: usize, e: usize) {
    let e = e.min(b.len());
    if s >= e {
        return;
    }
    let heads: Vec<(usize, usize, u8)> = rel_head()
        .captures_iter(&b[s..e])
        .map(|c| {
            let m = c.get(0).unwrap();
            (s + m.start(), s + m.end(), c.get(1).unwrap().as_bytes()[0])
        })
        .collect();
    for (n, &(_st, mend, kind)) in heads.iter().enumerate() {
        let end = if n + 1 < heads.len() { heads[n + 1].0 } else { e.min(mend + 200) };
        let (mut groups, mut cur): (Vec<Vec<Handle>>, Vec<Handle>) = (vec![], vec![]);
        let hi = end.min(mend + 200);
        for at in finditer(handle_re(), b, mend, hi) {
            let tag = u16_at(b, at) as u32;
            let hid = u16_at(b, at + 2) as u32;
            if tag == 0xFFFF {
                if !cur.is_empty() {
                    groups.push(std::mem::take(&mut cur));
                }
                continue;
            }
            let cls = tags.get(&tag).cloned().unwrap_or_default();
            let kind = match cls.as_str() {
                "sgPointHandle" => "point".to_string(),
                "sgLineHandle" => "line".to_string(),
                "sgArcHandle" => "arc".to_string(),
                "" => "?".to_string(),
                c => c.to_string(),
            };
            cur.push(Handle { cls: kind, id: hid });
        }
        if !cur.is_empty() {
            groups.push(cur);
        }
        sk.relations.push(Relation { kind: kind as u32, groups });
    }
}

