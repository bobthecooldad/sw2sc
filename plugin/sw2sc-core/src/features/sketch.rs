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
pub fn read_sketch(b: &[u8], base: &Tags, sk: &mut Sketch, s: usize, e: usize, learned: Option<&mut Tags>) {
    let mut trial: Tags = learned.as_deref().cloned().unwrap_or_default();
    let (tags2, listed) = read_sketch_once(b, base, sk, s, e, Some(&mut trial), &Tags::new());
    // an arc tag whose two-point curves find no centre is the line class (see the Python)
    static FAIL: OnceLock<regex::Regex> = OnceLock::new();
    let re = FAIL.get_or_init(|| regex::Regex::new(r"^arc (\d+): no centre found \(ends \[\d+, \d+\]\)$").unwrap());
    let fails: HashSet<u16> = sk.problems.iter().filter_map(|p| re.captures(p).and_then(|c| c[1].parse().ok())).collect();
    if fails.len() >= 2 {
        for (t, cids) in &listed {
            if tags2.get(t).map(String::as_str) != Some(ARC)
                || !cids.keys().any(|c| fails.contains(c))
                || cids.values().any(|ps| ps.iter().collect::<HashSet<_>>().len() != 2)
            {
                continue;
            }
            let mut sk2 = Sketch::new(&sk.name, sk.offset);
            sk2.end = sk.end;
            let mut trial2: Tags = learned.as_deref().cloned().unwrap_or_default();
            let force: Tags = [(*t, LINE.to_string())].into_iter().collect();
            read_sketch_once(b, base, &mut sk2, s, e, Some(&mut trial2), &force);
            let nc = |k: &Sketch| k.problems.iter().filter(|p| p.contains("no centre found")).count();
            if nc(&sk2) < nc(sk) && sk2.problems.len() < sk.problems.len() {
                *sk = sk2;
                trial = trial2;
            }
            break;
        }
    }
    if let Some(l) = learned {
        l.extend(trial);
    }
}

/// One reading of a sketch; `force` gives tags a class whatever the numbering says. Returns the
/// tags used and each tag's curves (tag -> curve id -> points).
#[allow(clippy::type_complexity)]
fn read_sketch_once(
    b: &[u8],
    base: &Tags,
    sk: &mut Sketch,
    s: usize,
    e: usize,
    mut learned: Option<&mut Tags>,
    force: &Tags,
) -> (Tags, IndexMap<u32, IndexMap<u16, Vec<u32>>>) {
    let mut tags = base.clone();
    if let Some(l) = learned.as_deref() {
        tags.extend(l.iter().map(|(k, v)| (*k, v.clone())));
    }
    tags.extend(force.iter().map(|(k, v)| (*k, v.clone())));
    let mut inline: Vec<String> = Vec::new();
    let mut unknown: IndexMap<(u32, u16), Vec<u32>> = IndexMap::new();
    let mut curves: IndexMap<(String, u16), Vec<u32>> = IndexMap::new();
    let mut plain: Vec<u32> = Vec::new();
    // every handle in a point's list: (tag or None, class brought in, curve id, point)
    let mut entries: Vec<(Option<u32>, Option<String>, u16, u32)> = Vec::new();
    let mut pts_order: Vec<u32> = Vec::new();
    let e2 = e.min(b.len());
    let mut from = s;
    // (files before about 2010 write `07` where later ones write `1F`)
    while let Some(i) = find_point_mark(b, from, e2) {
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
    curves_from_records(b, sk, s, e);
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
    (tags, listed)
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

/// Keep confirmed contours and their dimensions, with reference lines as construction and no
/// unrelated points. Repeated handles on a dimension are one reference.
pub fn select_sketch_loops(sk: &Sketch, loops: &[Vec<String>]) -> Sketch {
    let mut keep: HashSet<String> = loops.iter().flatten().cloned().collect();
    let mut p = sk.points.clone();
    p.entry(0).or_insert((0.0, 0.0));
    let mut contour_points = HashSet::new();
    for cid in &keep {
        if cid.starts_with('l') {
            if let Some(line) = cid[1..].parse::<usize>().ok().and_then(|n| sk.lines.get(n.saturating_sub(1))) {
                contour_points.extend([line.0, line.1]);
            }
        } else if cid.starts_with('a') {
            if let Some(arc) = cid[1..].parse::<usize>().ok().and_then(|n| sk.arcs.get(n.saturating_sub(1))) {
                contour_points.extend([arc.0, arc.1, arc.2]);
            }
        } else if cid.starts_with('c') {
            if let Some(circle) = cid[1..].parse::<usize>().ok().and_then(|n| sk.circles.get(n.saturating_sub(1))) {
                contour_points.insert(circle.0);
            }
        }
    }
    let mut reference_lines = HashSet::new();
    for d in &sk.dims {
        if d.cls != "sgPntLineDist" {
            continue;
        }
        let mut seen = HashSet::new();
        let mut points: Vec<Vec<u32>> = Vec::new();
        for h in &d.handles {
            if h.cls != "sgPointHandle" || !seen.insert((h.cls.clone(), h.id)) {
                continue;
            }
            let mut options = Vec::new();
            if h.id == 0 {
                options.push(0);
            }
            for pid in [Some(h.id), h.id.checked_add(1)].into_iter().flatten() {
                if p.contains_key(&pid) && !options.contains(&pid) {
                    options.push(pid);
                }
            }
            points.push(options);
        }
        let mut curves = Vec::new();
        for h in &d.handles {
            let key = ("line".to_string(), h.id as u16);
            if h.cls == "sgLineHandle" && sk.curve_of.contains_key(&key) && !curves.contains(&key) {
                curves.push(key);
            }
        }
        for options in points {
            for pid in options {
                for curve in &curves {
                    let Some(cid) = sk.curve_of.get(curve) else { continue };
                    let Some(&(a, b)) = cid[1..].parse::<usize>().ok().and_then(|n| sk.lines.get(n.saturating_sub(1))) else { continue };
                    let (pa, pb) = (p[&a], p[&b]);
                    let (dx, dy) = (pb.0 - pa.0, pb.1 - pa.1);
                    let length = dx.hypot(dy);
                    let distance = if length > 0.0 { ((p[&pid].0 - pa.0) * dy - (p[&pid].1 - pa.1) * dx).abs() / length } else { -1.0 };
                    if (distance - d.value).abs() < 1e-9 {
                        let normal = (-dy / length, dx / length);
                        let projections: Vec<f64> = contour_points.iter().map(|pid| p[pid].0 * normal.0 + p[pid].1 * normal.1).collect();
                        let span = projections.iter().copied().reduce(f64::max).unwrap_or(0.0) - projections.iter().copied().reduce(f64::min).unwrap_or(0.0);
                        if keep.contains(cid) || (span - d.value.abs()).abs() < 1e-9 {
                            reference_lines.insert(cid.clone());
                        }
                    }
                }
            }
        }
    }
    keep.extend(reference_lines.iter().cloned());
    let mut out = sk.clone();
    let mut new_lines = HashMap::new();
    out.lines.clear();
    for (old, &(a, c)) in sk.lines.iter().enumerate() {
        if keep.contains(&format!("l{}", old + 1)) {
            new_lines.insert(old, out.lines.len());
            out.lines.push((a, c));
        }
    }
    out.construction = sk.construction.iter().filter_map(|old| new_lines.get(old).copied()).collect();
    for (old, new) in &new_lines {
        if reference_lines.contains(&format!("l{}", old + 1)) {
            out.construction.insert(*new);
        }
    }
    out.arcs = sk.arcs.iter().enumerate().filter(|(n, _)| keep.contains(&format!("a{}", n + 1))).map(|(_, &(a, c, ctr))| (a, c, ctr)).collect();
    out.circles = sk.circles.iter().enumerate().filter(|(n, _)| keep.contains(&format!("c{}", n + 1))).map(|(_, &(ctr, r))| (ctr, r)).collect();
    let mut renumbered = HashMap::new();
    for (old, new) in &new_lines {
        renumbered.insert(format!("l{}", old + 1), format!("l{}", new + 1));
    }
    let mut new = 0;
    for old in 0..sk.arcs.len() {
        if keep.contains(&format!("a{}", old + 1)) {
            new += 1;
            renumbered.insert(format!("a{}", old + 1), format!("a{new}"));
        }
    }
    new = 0;
    for old in 0..sk.circles.len() {
        if keep.contains(&format!("c{}", old + 1)) {
            new += 1;
            renumbered.insert(format!("c{}", old + 1), format!("c{new}"));
        }
    }
    out.curve_of = sk.curve_of.iter().filter_map(|(key, value)| renumbered.get(value).map(|v| (key.clone(), v.clone()))).collect();
    let allowed: HashSet<(String, u16)> = out.curve_of.keys().cloned().collect();
    let relevant = |groups: &[Vec<Handle>]| groups.iter().flatten().all(|h| h.cls == "point" || allowed.contains(&(h.cls.clone(), h.id as u16)));
    let candidate_relations: Vec<Relation> = sk.relations.iter().filter(|r| relevant(&r.groups)).cloned().collect();
    out.dims = Vec::new();
    for d in &sk.dims {
        let mut seen = HashSet::new();
        let handles: Vec<Handle> = d.handles.iter().filter(|h| seen.insert((*h).clone())).cloned().collect();
        let raw = handles.iter().map(|h| Handle {
            cls: match h.cls.as_str() {
                "sgPointHandle" => "point",
                "sgLineHandle" => "line",
                "sgArcHandle" => "arc",
                other => other,
            }.into(),
            id: h.id,
        }).collect::<Vec<_>>();
        if handles.is_empty() || relevant(&[raw]) {
            let mut dim = d.clone();
            dim.handles = handles;
            out.dims.push(dim);
        }
    }
    let mut used = HashSet::new();
    for &(a, b) in &out.lines {
        used.extend([a, b]);
    }
    for &(a, b, centre) in &out.arcs {
        used.extend([a, b, centre]);
    }
    used.extend(out.circles.iter().map(|c| c.0));
    for d in &out.dims {
        for h in &d.handles {
            if h.cls == "sgPointHandle" {
                if h.id == 0 {
                    used.insert(0);
                } else {
                    used.extend([Some(h.id), h.id.checked_add(1)].into_iter().flatten().filter(|pid| p.contains_key(pid)));
                }
            }
        }
    }
    out.relations = Vec::new();
    for relation in candidate_relations {
        let mut kept = Vec::new();
        for group in relation.groups {
            let has_curve = group.iter().any(|h| h.cls != "point");
            let points: Vec<u32> = group.iter().filter(|h| h.cls == "point").filter_map(|h| h.id.checked_add(1)).filter(|pid| p.contains_key(pid)).collect();
            if has_curve || (!points.is_empty() && points.iter().all(|pid| used.contains(pid))) {
                kept.push(group);
                if has_curve {
                    used.extend(points);
                }
            }
        }
        if !kept.is_empty() {
            out.relations.push(Relation { kind: relation.kind, groups: kept });
        }
    }
    used.remove(&0);
    out.points.retain(|pid, _| used.contains(pid));
    out.offsets.clear();
    out
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

/// The next point record's `FF FF 1F 00` (older files: `FF FF 07 00`) in `b[lo..hi]`.
fn find_point_mark(b: &[u8], lo: usize, hi: usize) -> Option<usize> {
    let mut from = lo;
    while let Some(i) = find_in(b, &[0xff, 0xff], from, hi) {
        if i + 4 <= hi && matches!(b[i + 2], 0x07 | 0x1f) && b[i + 3] == 0 {
            return Some(i);
        }
        from = i + 1;
    }
    None
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
    let mut j = i + 8;
    if b.get(j..j + 3) == Some(&[0xff, 0xfe, 0xff][..]) {
        j += 4 + 2 * *b.get(j + 3)? as usize;
    }
    if b.get(j..j + 2) == Some(&[0, 0][..]) && j + 10 <= b.len() {
        return Some(f64_at(b, j + 2));
    }
    // saved by SolidWorks 2012: `FF FF FF FF`, 2 zero bytes and the double (see the Python)
    if b.get(i + 4..i + 6) == Some(&[0, 0][..]) && i + 14 <= b.len() {
        return Some(f64_at(b, i + 6));
    }
    None
}

fn rel_head() -> &'static Regex {
    static R: OnceLock<Regex> = OnceLock::new();
    R.get_or_init(|| Regex::new(r"(?s-u)([\x00-\xff])\x00\x00\x00\x02\x00\x00\x00(?:\x00\x00){1,2}\xfe\xff\x00\x00").unwrap())
}

fn handle_re() -> &'static Regex {
    static R: OnceLock<Regex> = OnceLock::new();
    R.get_or_init(|| Regex::new(r"(?s-u)([\x00-\xff][\x80-\xff])([\x00-\xff]{2})\xff\xff\xff\xff\x00\x00\x00\x00").unwrap())
}

pub(super) fn parameter_records(b: &[u8], s: usize, e: usize) -> Vec<(usize, String)> {
    let mut out = Vec::new();
    let mut from = s;
    while let Some(j) = find_in(b, &[0xff, 0xfe, 0xff], from, e) {
        from = j + 1;
        let Some(&ln) = b.get(j + 3) else { continue };
        if !(1..=32).contains(&ln) || j + 4 + 2 * ln as usize > b.len() {
            continue;
        }
        let nm = utf16(&b[j + 4..j + 4 + 2 * ln as usize]);
        if nm.starts_with('D') && nm.len() > 1 && nm[1..].bytes().all(|c| c.is_ascii_digit()) {
            out.push((j, nm));
        }
    }
    out
}

pub(super) fn dimension_handles(b: &[u8], tags: &Tags, j: usize, end: usize, parameters: &[(usize, String)]) -> Vec<Handle> {
    let mut end = parameters.iter().filter(|(at, _)| *at > j).map(|(at, _)| *at).min().unwrap_or(end).min(end).min(b.len());
    if j < end {
        if let Some(m) = rel_head().find(&b[j..end]) {
            end = j + m.start();
        }
    }
    let mut handles = Vec::new();
    let mut k = j;
    while k + 12 <= end && k + 12 <= b.len() {
        if b[k + 1] & 0x80 != 0 && b[k + 4..k + 8] == [0xff; 4] && b[k + 8..k + 12] == [0u8; 4] {
            let cname = tags.get(&(u16_at(b, k) as u32)).cloned().unwrap_or_default();
            handles.push(Handle { cls: cname, id: u16_at(b, k + 2) as u32 });
            k += 12;
        } else {
            k += 1;
        }
    }
    handles
}

/// Read each dimension class's current parameter and only the handles before the next parameter.
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
            from = i + needle.len();
            starts.push((i, cls.to_string(), i + 2));
        }
    }
    starts.sort();
    let parameters = parameter_records(b, s, e);
    let mut found: IndexMap<String, (String, f64, Vec<Handle>)> = IndexMap::new();
    for n in 0..starts.len() {
        let (i, ref cls, data) = starts[n];
        let end = if n + 1 < starts.len() { starts[n + 1].0 } else { e.min(i + 600) };
        let Some(first) = find_in(b, &[0xff, 0xfe, 0xff], data, data + 40) else { continue };
        let ln = *b.get(first + 3).unwrap_or(&0) as usize;
        let nm = utf16(&b[(first + 4).min(b.len())..(first + 4 + 2 * ln).min(b.len())]);
        let Some(j) = parameters.iter().filter(|(at, name)| *at >= data && *at < end && name == &nm).map(|(at, _)| *at).last() else { continue };
        let Some(v) = param_value(b, j.saturating_sub(2)) else { continue };
        if nm.is_empty() {
            continue;
        }
        let handles = dimension_handles(b, tags, j, end, &parameters);
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


/// Curve-handle tags for a file whose numbering has drifted before its first sketch (NIST FTC 06),
/// as `_handle_tags_file`: only where no handle tag in any point's list is one the numbering
/// gives a curve class, those tags take the curve classes in the order the stream brings them in.
pub fn handle_tags_file(b: &[u8], tags: &Tags, recs: &[crate::archive::Record]) -> Tags {
    let curve = |c: Option<&String>| matches!(c.map(|s| s.as_str()), Some("sgLineHandle") | Some("sgArcHandle"));
    let mut seen: std::collections::BTreeSet<u32> = std::collections::BTreeSet::new();
    let mut from = 0;
    while let Some(i) = find_in(b, &[0xff, 0xff, 0x1f, 0x00], from, b.len()) {
        from = i + 1;
        let Some(j) = find_in(b, &[0x1e, 0x00], i + 30, i + 80) else { continue };
        let ok = b.get(j.wrapping_sub(2)..j) == Some(&[0xf0, 0x3f][..])
            || (j >= 10 && b[j - 10..j - 8] == [0xf0, 0x3f] && b[j - 8..j] == [0u8; 8]);
        if j + 22 > b.len() || !ok {
            continue;
        }
        let mut k = j + 22;
        for _ in 0..16 {
            if k + 12 > b.len() {
                break;
            }
            let t = u16_at(b, k) as u32;
            if t & 0x8000 == 0 || t == 0xFFFF || b[k + 4..k + 8] != [0xff; 4] {
                break;
            }
            seen.insert(t);
            k += 12;
        }
    }
    let mut out = Tags::new();
    if seen.is_empty() || seen.iter().any(|t| curve(tags.get(t))) {
        return out;
    }
    let mut order: Vec<String> = Vec::new();
    for r in recs {
        if r.new_class && curve(Some(&r.cls)) && !order.contains(&r.cls) {
            order.push(r.cls.clone());
        }
    }
    if order.len() == seen.len() {
        out.extend(seen.into_iter().zip(order));
    }
    out
}

/// A sketch record: a point (id, x, y, located) or a curve (id, first end, last end, flag, tail).
enum Ent {
    P(u32, f64, f64, bool),
    S(u32, u16, u16, u16, [u16; 6]),
}

/// A sketch's point and curve records in order (see the Python `_entities`).
/// Ported from cadkit-kernel crates/ck-sldprt/src/sketch.rs `entities`, MIT OR Apache-2.0.
fn entities(b: &[u8], s: usize, e: usize) -> Vec<Ent> {
    let e = e.min(b.len());
    let mut heads = Vec::new();
    let mut i = s.max(4);
    while let Some(j) = find_in(b, &[0xff, 0xff], i, e) {
        if j + 13 > e {
            break;
        }
        if b[j + 2] <= 0x40 && b[j + 3] == 0 && (1..=8).contains(&b[j + 4]) && b[j + 5..j + 13] == [0xff; 8] {
            heads.push(j);
            i = j + 13;
        } else {
            i = j + 1;
        }
    }
    let (mut w, mut wo) = (0usize, 0usize);
    for &h in &heads {
        let Some(r) = find_in(b, &[0xf0, 0x3f], h + 13, (h + 4096).min(b.len())) else { continue };
        if b.get(r + 2..r + 4) == Some(&[0x1e, 0x00]) {
            wo += 1;
        } else if b.get(r + 2..r + 10) == Some(&[0; 8]) && b.get(r + 10..r + 12) == Some(&[0x1e, 0x00]) {
            w += 1;
        }
    }
    let zeros = if w + wo > 0 { w >= wo } else { true };
    let mut out = Vec::new();
    for (n, &h) in heads.iter().enumerate() {
        let end = heads.get(n + 1).copied().unwrap_or(b.len()).min(h + 4096);
        if b.get(h + 13..h + 17) != Some(&[0, 0, 0x80, 0xbf]) || b.get(h + 33..h + 35) != Some(&[0x80, 0xbf]) {
            continue;
        }
        let pid = u32_at(b, h - 4);
        if b.get(h + 35..h + 37) != Some(&[0, 0]) {
            let mut o = h + 35;
            let mut found = None;
            while found.is_none() {
                let Some(q) = find_in(b, &[0xf0, 0x3f], o, end) else { break };
                let k = q + 2 + if zeros { 8 } else { 0 };
                if (!zeros || b.get(q + 2..q + 10) == Some(&[0; 8])) && b.get(k..k + 2) == Some(&[0x1e, 0x00]) && k + 18 <= b.len() {
                    let (x, y) = (f64_at(b, k + 2), f64_at(b, k + 10));
                    if x.is_finite() && y.is_finite() {
                        found = Some((x, y));
                    }
                }
                o = q + 1;
            }
            let (x, y) = found.unwrap_or((0.0, 0.0));
            out.push(Ent::P(pid, x, y, found.is_some()));
            continue;
        }
        let Some(r) = find_in(b, &[0xf0, 0x3f], h + 13, end) else { continue };
        let mut k = r + 2;
        if zeros {
            if b.get(k..k + 8) != Some(&[0; 8]) {
                continue;
            }
            k += 8;
        }
        if b.get(k..k + 2) == Some(&[0x1e, 0x00]) {
            if k + 18 > b.len() {
                continue;
            }
            let (x, y) = (f64_at(b, k + 2), f64_at(b, k + 10));
            if x.is_finite() && y.is_finite() {
                out.push(Ent::P(pid, x, y, true));
            }
        } else if k + 32 <= b.len() {
            let tail: [u16; 6] = std::array::from_fn(|t| u16_at(b, k + 20 + 2 * t));
            out.push(Ent::S(pid, u16_at(b, k), u16_at(b, k + 2), u16_at(b, k + 4), tail));
        }
    }
    out
}

/// Where the handle reading leaves curves unread, the sketch's curve records instead (see the
/// Python `_curves_from_records`). After cadkit-kernel crates/ck-sldprt/src/sketch.rs
/// `build_sketch`, MIT OR Apache-2.0.
fn curves_from_records(b: &[u8], sk: &mut Sketch, s: usize, e: usize) {
    static BAD: OnceLock<regex::Regex> = OnceLock::new();
    let re = BAD.get_or_init(|| regex::Regex::new(r"^(?:arc \d+: no centre found .*|(line|arc) \d+ has \d+ (end )?points)$").unwrap());
    let bad: Vec<String> = sk.problems.iter().filter(|p| re.is_match(p)).cloned().collect();
    if (!sk.lines.is_empty() || !sk.arcs.is_empty() || !sk.circles.is_empty()) && bad.is_empty() {
        return;
    }
    let ents = entities(b, s, e);
    let pts: Vec<(u32, f64, f64, bool)> = ents.iter().filter_map(|x| if let Ent::P(a, b, c, d) = x { Some((*a, *b, *c, *d)) } else { None }).collect();
    let segs: Vec<(u32, u16, u16, u16, [u16; 6])> =
        ents.iter().filter_map(|x| if let Ent::S(a, b, c, d, t) = x { Some((*a, *b, *c, *d, *t)) } else { None }).filter(|x| x.0 != 0xFFFF_FFFF).collect();
    if segs.is_empty() {
        return;
    }
    let n = pts.len();
    let mut first: HashMap<u32, usize> = HashMap::new();
    for (k, x) in pts.iter().enumerate() {
        first.entry(x.0).or_insert(k);
    }
    let mut points = sk.points.clone();
    let (mut lines, mut arcs, mut circles) = (Vec::new(), Vec::new(), Vec::new());
    let mut cons = std::collections::BTreeSet::new();
    let mut curve_of: IndexMap<(String, u16), String> = IndexMap::new();
    let mut dropped = Vec::new();
    let pid = |k: usize, points: &mut IndexMap<u32, (f64, f64)>| -> Option<u32> {
        if k >= n || !pts[k].3 || pts[k].0 == 0xFFFF_FFFF || first[&pts[k].0] != k {
            return None;
        }
        points.insert(pts[k].0, (pts[k].1, pts[k].2));
        Some(pts[k].0)
    };
    let dist = |p: (f64, f64), q: (f64, f64)| (p.0 - q.0).hypot(p.1 - q.1);
    for &(cid, a, c, flag, tail) in &segs {
        let (a, c) = (a as usize, c as usize);
        if flag > 1 || a >= n || c >= n || cid > 0xFFFF {
            return;
        }
        let (Some(pa), Some(pc)) = (pid(a, &mut points), pid(c, &mut points)) else { return };
        if tail[1] == 0xFFFE {
            let Some(pk) = pid(tail[0] as usize, &mut points) else { return };
            if pk == pa || pk == pc {
                return;
            }
            let r = dist(points[&pk], points[&pa]);
            if r < TOL || (dist(points[&pk], points[&pc]) - r).abs() > 1e-6 * r.max(1e-3) {
                return;
            }
            if flag == 0 {
                dropped.push(format!("construction arc {cid}"));
                continue;
            }
            if pa == pc {
                circles.push((pk, r));
                curve_of.insert(("arc".into(), cid as u16), format!("c{}", circles.len()));
            } else {
                arcs.push((pa, pc, pk));
                curve_of.insert(("arc".into(), cid as u16), format!("a{}", arcs.len()));
            }
        } else if a == c {
            return;
        } else {
            if dist(points[&pa], points[&pc]) < TOL {
                return;
            }
            lines.push((pa, pc));
            if flag == 0 {
                cons.insert(lines.len() - 1);
            }
            curve_of.insert(("line".into(), cid as u16), format!("l{}", lines.len()));
        }
    }
    if lines.is_empty() && arcs.is_empty() && circles.is_empty() {
        return;
    }
    sk.points = points;
    sk.lines = lines;
    sk.arcs = arcs;
    sk.circles = circles;
    sk.construction = cons;
    sk.curve_of = curve_of;
    sk.problems.retain(|p| !bad.contains(p));
    sk.dropped.extend(dropped);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn contour_selection_filters_geometry_and_its_relations() {
        let mut sk = Sketch::new("S", 0);
        sk.points.extend([
            (1, (0.0, 0.0)),
            (2, (0.01, 0.0)),
            (3, (0.01, 0.01)),
            (4, (0.0, 0.01)),
            (5, (0.005, 0.005)),
            (6, (0.007, 0.005)),
        ]);
        sk.lines = vec![(1, 2), (2, 3), (3, 4), (4, 1)];
        sk.circles = vec![(5, 0.002)];
        sk.curve_of.insert(("arc".into(), 7), "c1".into());
        sk.curve_of.insert(("line".into(), 1), "l1".into());
        sk.relations = vec![
            Relation { kind: 9, groups: vec![vec![Handle { cls: "arc".into(), id: 7 }]] },
            Relation { kind: 1, groups: vec![vec![Handle { cls: "line".into(), id: 1 }]] },
        ];
        let selected = select_sketch_loops(&sk, &[vec!["l1".into(), "l2".into(), "l3".into(), "l4".into()]]);
        assert_eq!(selected.lines.len(), 4);
        assert!(selected.circles.is_empty());
        assert_eq!(selected.relations, [Relation { kind: 1, groups: vec![vec![Handle { cls: "line".into(), id: 1 }]] }]);
        assert_eq!(selected.curve_of.into_iter().collect::<Vec<_>>(), [(("line".into(), 1), "l1".into())]);
        assert_eq!(selected.points.keys().copied().collect::<std::collections::BTreeSet<_>>(), [1, 2, 3, 4].into());
    }

    fn parameter(name: &str, value: f64) -> Vec<u8> {
        let mut out = vec![0xff, 0xfe, 0xff, name.len() as u8];
        out.extend(name.encode_utf16().flat_map(u16::to_le_bytes));
        out.extend([0; 8]);
        out.extend([0xff; 4]);
        out.extend([0; 4]);
        out.extend([0xff, 0xfe, 0xff, 0, 0, 0]);
        out.extend(value.to_le_bytes());
        out
    }

    #[test]
    fn repeated_dimension_uses_its_current_parameter_and_own_handles() {
        let class = b"sgPntPntDist";
        let mut raw = vec![0xff, 0xff, 1, 0, class.len() as u8, 0];
        raw.extend(class);
        raw.extend(parameter("D3", 0.010));
        raw.extend(parameter("D3", 0.038));
        for id in [5u16, 4] {
            raw.extend(0x80b4u16.to_le_bytes());
            raw.extend(id.to_le_bytes());
            raw.extend([0xff; 4]);
            raw.extend([0; 4]);
        }
        raw.extend(0x81cbu16.to_le_bytes());
        raw.extend(0u16.to_le_bytes());
        raw.extend([0xff; 4]);
        raw.extend([0; 4]);
        let mut sk = Sketch::new("S", 0);
        sk.end = raw.len();
        let tags = [(0x80b4, "sgPointHandle".to_string()), (0x81cb, "sgLineHandle".to_string())].into();
        read_dimensions(&raw, &tags, &mut sk, 0, raw.len());
        assert_eq!(sk.dims.len(), 1);
        assert_eq!(sk.dims[0].name, "D3");
        assert_eq!(sk.dims[0].value, 0.038);
        assert_eq!(sk.dims[0].handles, [Handle { cls: "sgPointHandle".into(), id: 5 }, Handle { cls: "sgPointHandle".into(), id: 4 }, Handle { cls: "sgLineHandle".into(), id: 0 }]);
    }

    #[test]
    fn contour_filter_keeps_a_valid_reference_and_renumbers_it() {
        let mut sk = Sketch::new("S", 0);
        sk.points.extend([(1, (0.0, 0.0)), (2, (0.0, 0.070)), (3, (0.123, 0.456)), (4, (0.009, 0.008)), (5, (-0.005, 0.070)), (6, (0.005, 0.070))]);
        sk.lines = vec![(1, 2), (3, 4), (5, 6)];
        sk.curve_of.extend([( (String::from("line"), 1), "l1".into()), (("line".into(), 2), "l2".into()), (("line".into(), 3), "l3".into())]);
        sk.dims = vec![Dim { name: "D4".into(), cls: "sgPntLineDist".into(), value: 0.070,
                             handles: vec![Handle { cls: "sgPointHandle".into(), id: 0 }, Handle { cls: "sgLineHandle".into(), id: 3 }] }];
        sk.relations = vec![Relation { kind: 4, groups: vec![vec![Handle { cls: "point".into(), id: 2 }]] }];
        let selected = select_sketch_loops(&sk, &[vec!["l1".into()]]);
        assert_eq!(selected.curve_of.get(&("line".into(), 3)).map(String::as_str), Some("l2"));
        assert!(selected.construction.contains(&1));
        assert_eq!(selected.points.keys().copied().collect::<std::collections::BTreeSet<_>>(), [1, 2, 5, 6].into());
        assert!(selected.relations.is_empty());
    }
}
