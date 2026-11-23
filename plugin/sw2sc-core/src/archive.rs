//! SolidWorks object streams: the records and their numbers (port of `sw2sc/archive.py`).
//!
//! The feature tree (`Contents/Config-N-ResolvedFeatures`) and the part's main section
//! (`Contents/Config-N`) are written in the layout of the publicly documented MFC `CArchive`
//! object format. Every new class and every new object takes the next number, and later records
//! refer to a class as `0x8000 | number`.
//!
//! - A new class: `FF FF`, u16 schema, u16 name length, ASCII name. It takes one number and its
//!   first object the next.
//! - An object of a class already numbered: `0x8000 | class number`. It takes one number.
//! - Newer files (2015+) start the feature stream with a u32: the number the stream carries on
//!   from. Older files start with a u16 and carry on from `Contents/Config-N` instead.

use std::collections::{BTreeMap, HashMap, HashSet};
use std::sync::OnceLock;

use regex::bytes::Regex;

use crate::cfb::{u16_at, u32_at};
use crate::swfile::find;

#[derive(Clone, Debug, PartialEq)]
pub struct Record {
    /// Where its tag starts in the stream.
    pub offset: usize,
    /// The object's number.
    pub number: i64,
    /// Its class name (`pre<n>` for a class numbered in another section).
    pub cls: String,
    /// The record also brought in the class (its number is `number - 1`).
    pub new_class: bool,
}

fn is_name(b: &[u8]) -> bool {
    // [A-Za-z_][A-Za-z0-9_]*, the whole of it
    !b.is_empty()
        && (b[0].is_ascii_alphabetic() || b[0] == b'_')
        && b.iter().all(|c| c.is_ascii_alphanumeric() || *c == b'_')
}

/// The number a feature stream carries on from, when its header says (2015+ files).
pub fn start_number(stream: &[u8]) -> Option<i64> {
    if stream.len() >= 6 && stream[4..6] != [0xff, 0xff] && stream.get(6..8) == Some(&[0xff, 0xff][..]) {
        let n = u32_at(stream, 0) as i64;
        return (0 < n && n < 0x7FFF).then_some(n);
    }
    None
}

fn named_after() -> &'static Regex {
    static R: OnceLock<Regex> = OnceLock::new();
    R.get_or_init(|| Regex::new(r"(?s-u)([\x00-\xff][\x80-\xff])([\x00-\xff][\x80-\xff])\xff\xfe\xff").unwrap())
}

/// The number a pre-2015 feature stream carries on from (it continues `Contents/Config-N`'s
/// numbering and doesn't say where). Anchor: the three standard planes are written one after
/// another, Front bringing in `moRefPlane_c` and the next two tagged with its number; the start
/// is the one that gives `moRefPlane_c` that number.
pub fn old_start_number(stream: &[u8], outside: Option<&HashSet<i64>>) -> Option<i64> {
    let i = find(stream, b"moRefPlane_c", 0)?;
    // moRefPlane_c's number is settled where it is brought in: only the stream up to there is
    // numbered for each start tried
    let head = &stream[..i + b"moRefPlane_c".len()];
    let recs = |s: i64| records(head, Some(s), outside, false);
    let lo = (i + 12).min(stream.len());
    let hi = (i + 3000).min(stream.len());
    let m = named_after().captures(&stream[lo..hi])?;
    let target = (u16_at(m.get(1).unwrap().as_bytes(), 0) & 0x7FFF) as i64;
    let mut s = target;
    let mut seen = HashSet::new();
    for _ in 0..16 {
        let c = *class_numbers(&recs(s)).get("moRefPlane_c")?;
        if c == target {
            return Some(s);
        }
        seen.insert(s);
        s += target - c;
        if seen.contains(&s) || s <= 0 {
            break;
        }
    }
    for s in (1.max(target - 600))..=target {
        if class_numbers(&recs(s)).get("moRefPlane_c") == Some(&target) {
            return Some(s);
        }
    }
    None
}

pub const RESYNC_MAX: i64 = 6;

#[derive(Clone, Copy, PartialEq, Debug)]
enum Kind {
    Named,
    Handle,
    Component,
}

/// What the bytes after a tag show starts there: a named object (node tag, then `FF FE FF`), a
/// curve handle (u16 id, `FF FF FF FF`, 4 zero bytes) or a component reference such as a plane
/// reference (sub-tag, `02 00`, zero bytes); None when it isn't clear.
fn anchored(s: &[u8], pos: usize) -> Option<Kind> {
    let end = (pos + 14).min(s.len());
    let t = &s[(pos + 2).min(end)..end];
    let g = |a: usize, b: usize| t.get(a..b);
    if g(1, 2) == Some(&[0x80][..]) && g(2, 5) == Some(&[0xff, 0xfe, 0xff][..]) {
        return Some(Kind::Named);
    }
    if g(2, 10) == Some(&[0xff, 0xff, 0xff, 0xff, 0, 0, 0, 0][..]) {
        return Some(Kind::Handle);
    }
    if g(1, 2) == Some(&[0x80][..]) && g(2, 4) == Some(&[0x02, 0x00][..]) && g(4, 12) == Some(&[0u8; 8][..]) {
        return Some(Kind::Component);
    }
    None
}

fn kind_fits(k: Kind, nm: &str) -> bool {
    match k {
        Kind::Named => !nm.ends_with("Handle") && !nm.starts_with("moComp"),
        Kind::Handle => nm.ends_with("Handle"),
        Kind::Component => nm.starts_with("moComp"),
    }
}

fn intro(out: &[Record], number: i64) -> usize {
    out.iter().find(|r| r.new_class && r.number - 1 == number).map_or(0, |r| r.offset)
}

/// Every record that can be told apart by its tag, in order, with its number.
///
/// `start` is the number the stream carries on from; by default the header's (2015+), else 0.
/// `outside`: the numbers of the classes written in the section the stream carries on from
/// (pre-2015 files); a tag naming one of them is an object too. Without it every number below
/// `start` is taken as such a class. `resync`: where a real object starts under a tag the count
/// doesn't give a class, the count has drifted and is shifted to fit.
pub fn records(stream: &[u8], start: Option<i64>, outside: Option<&HashSet<i64>>, resync: bool) -> Vec<Record> {
    let header = start_number(stream);
    let start = start.or(header);
    let mut pos = if header.is_some() {
        6
    } else if stream.len() > 4 && stream[2..4] == [0xff, 0xff] {
        2
    } else {
        0
    };
    let mut num: i64 = match start {
        Some(s) if s != 0 => s - 1,
        _ => 0,
    };
    let st = start.unwrap_or(0);
    let mut classes: BTreeMap<i64, String> = BTreeMap::new();
    let mut out: Vec<Record> = Vec::new();
    let n = stream.len();
    while pos + 1 < n {
        if stream[pos] == 0xFF && stream[pos + 1] == 0xFF && pos + 6 < n {
            let ln = u16_at(stream, pos + 4) as usize;
            let end = (pos + 6 + ln).min(n);
            let name = &stream[pos + 6..end];
            if (3..=64).contains(&ln) && is_name(name) {
                num += 1;
                let nm = String::from_utf8_lossy(name).into_owned();
                classes.insert(num, nm.clone());
                num += 1;
                out.push(Record { offset: pos, number: num, cls: nm, new_class: true });
                pos += 6 + ln;
                continue;
            }
        }
        let tag = u16_at(stream, pos);
        let k = (tag & 0x7FFF) as i64;
        let real_tag = tag & 0x8000 != 0 && tag != 0xFFFF;
        let kind = if resync && real_tag && !classes.contains_key(&k) { anchored(stream, pos) } else { None };
        if let Some(kind) = kind {
            // a real object starts here, so k is a class number: the count has drifted (tag-like
            // bytes inside data were counted). Shift the nearest class of the right kind and all
            // later ones.
            let near = classes
                .iter()
                .filter(|(c, nm)| kind_fits(kind, nm) && **c >= st)
                .map(|(c, _)| *c)
                .min_by_key(|c| ((c - k).abs(), *c));
            if let Some(near) = near {
                if 0 < (near - k).abs() && (near - k).abs() <= RESYNC_MAX {
                    let delta = k - near;
                    classes = classes.into_iter().map(|(c, nm)| (if c >= near { c + delta } else { c }, nm)).collect();
                    let from = intro(&out, near);
                    for r in out.iter_mut() {
                        if r.number - i64::from(r.new_class) >= near && r.offset >= from {
                            r.number += delta;
                        }
                    }
                    num += delta;
                }
            }
        }
        let k_known = classes.contains_key(&k);
        let k_outside = st != 0 && 0 < k && k < st && outside.is_none_or(|o| o.contains(&k));
        if real_tag && (k_known || k_outside) {
            num += 1;
            let cls = classes.get(&k).cloned().unwrap_or_else(|| format!("pre{k}"));
            out.push(Record { offset: pos, number: num, cls, new_class: false });
            pos += 2;
            continue;
        }
        pos += 1;
    }
    out
}

/// Each class brought in by the stream and its number.
pub fn class_numbers(recs: &[Record]) -> HashMap<String, i64> {
    recs.iter().filter(|r| r.new_class).map(|r| (r.cls.clone(), r.number - 1)).collect()
}
