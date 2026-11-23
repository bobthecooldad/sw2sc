//! Minimal, read-only Compound File Binary (OLE2) reader (port of `sw2sc/cfb.py`).
//!
//! Written from Microsoft's public [MS-CFB] specification. Pre-2015 SolidWorks files use this
//! container. Input is untrusted: every offset and chain is bounds-checked and loops are capped.

use std::collections::{BTreeMap, HashSet};

pub const MAGIC: [u8; 8] = [0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1];
const FREESECT: u32 = 0xFFFF_FFFF;
const ENDOFCHAIN: u32 = 0xFFFF_FFFE;
const NOSTREAM: u32 = 0xFFFF_FFFF;
const MAX_CHAIN: usize = 1 << 22;

#[derive(Debug)]
pub struct CfbError(pub String);

impl std::fmt::Display for CfbError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

fn err<T>(m: impl Into<String>) -> Result<T, CfbError> {
    Err(CfbError(m.into()))
}

pub(crate) fn u16_at(b: &[u8], o: usize) -> u16 {
    b.get(o..o + 2).map_or(0, |s| u16::from_le_bytes([s[0], s[1]]))
}

pub(crate) fn u32_at(b: &[u8], o: usize) -> u32 {
    b.get(o..o + 4).map_or(0, |s| u32::from_le_bytes([s[0], s[1], s[2], s[3]]))
}

fn u64_at(b: &[u8], o: usize) -> u64 {
    b.get(o..o + 8).map_or(0, |s| u64::from_le_bytes(s.try_into().unwrap()))
}

#[derive(Clone, Debug)]
struct Entry {
    name: String,
    kind: u8,
    left: u32,
    right: u32,
    child: u32,
    start: u32,
    size: u64,
}

pub struct CompoundFile<'a> {
    data: &'a [u8],
    sector_size: usize,
    mini_size: usize,
    mini_cutoff: u64,
    fat: Vec<u32>,
    minifat: Vec<u32>,
    ministream: Vec<u8>,
    entries: Vec<Entry>,
    paths: BTreeMap<String, usize>,
}

impl<'a> CompoundFile<'a> {
    pub fn new(data: &'a [u8]) -> Result<Self, CfbError> {
        if data.len() < 512 || data[..8] != MAGIC {
            return err("not a compound file");
        }
        let shift = u16_at(data, 0x1E);
        let mini_shift = u16_at(data, 0x20);
        if !(shift == 9 || shift == 12) || mini_shift != 6 {
            return err(format!("bad sector shift {shift}/{mini_shift}"));
        }
        let mut cf = CompoundFile {
            data,
            sector_size: 1 << shift,
            mini_size: 1 << mini_shift,
            mini_cutoff: 0,
            fat: vec![],
            minifat: vec![],
            ministream: vec![],
            entries: vec![],
            paths: BTreeMap::new(),
        };
        let h: Vec<u32> = (0..8).map(|i| u32_at(data, 0x2C + 4 * i)).collect();
        let (n_fat, first_dir, mini_cutoff, first_minifat, n_minifat, first_difat, n_difat) =
            (h[0], h[1], h[3], h[4], h[5], h[6], h[7]);
        cf.mini_cutoff = mini_cutoff as u64;
        let mut difat: Vec<u32> = (0..109).map(|i| u32_at(data, 0x4C + 4 * i)).collect();
        let (mut sec, mut guard) = (first_difat, 0u32);
        let per = cf.sector_size / 4 - 1;
        while sec != ENDOFCHAIN && sec != FREESECT && guard < n_difat.max(1) + 1 {
            let buf = cf.sector(sec)?;
            for i in 0..per {
                difat.push(u32_at(&buf, 4 * i));
            }
            sec = u32_at(&buf, 4 * per);
            guard += 1;
        }
        let mut fat = Vec::new();
        for &s in difat.iter().take(n_fat as usize) {
            if s == FREESECT || s == ENDOFCHAIN {
                continue;
            }
            let buf = cf.sector(s)?;
            for i in 0..cf.sector_size / 4 {
                fat.push(u32_at(&buf, 4 * i));
            }
        }
        cf.fat = fat;
        cf.entries = cf.read_dir(first_dir)?;
        let root = match cf.entries.first() {
            Some(r) => r.clone(),
            None => return err("no root entry"),
        };
        cf.ministream = cf.chain(root.start, Some(root.size), false)?;
        if n_minifat > 0 {
            let mf = cf.chain(first_minifat, None, false)?;
            cf.minifat = (0..mf.len() / 4).map(|i| u32_at(&mf, 4 * i)).collect();
        }
        cf.paths = cf.build_paths();
        Ok(cf)
    }

    fn sector(&self, idx: u32) -> Result<Vec<u8>, CfbError> {
        let off = (idx as usize + 1) * self.sector_size;
        if idx >= 0xFFFF_FFFA || off > self.data.len() {
            return err(format!("sector {idx} out of range"));
        }
        let end = (off + self.sector_size).min(self.data.len());
        let mut v = self.data[off..end].to_vec();
        v.resize(self.sector_size, 0);
        Ok(v)
    }

    fn mini(&self, idx: u32) -> Result<Vec<u8>, CfbError> {
        let off = idx as usize * self.mini_size;
        if off + self.mini_size > self.ministream.len() {
            return err(format!("mini sector {idx} out of range"));
        }
        Ok(self.ministream[off..off + self.mini_size].to_vec())
    }

    fn chain(&self, start: u32, size: Option<u64>, mini: bool) -> Result<Vec<u8>, CfbError> {
        let table = if mini { &self.minifat } else { &self.fat };
        let unit = if mini { self.mini_size } else { self.sector_size };
        let mut out = Vec::new();
        let (mut sec, mut n) = (start, 0usize);
        while sec != ENDOFCHAIN && sec != FREESECT {
            if sec as usize >= table.len() || n > MAX_CHAIN {
                return err("broken sector chain");
            }
            out.extend(if mini { self.mini(sec)? } else { self.sector(sec)? });
            sec = table[sec as usize];
            n += 1;
            if let Some(sz) = size {
                if (n * unit) as u64 >= sz {
                    break;
                }
            }
        }
        if let Some(sz) = size {
            out.truncate(sz as usize);
        }
        Ok(out)
    }

    fn read_dir(&self, first: u32) -> Result<Vec<Entry>, CfbError> {
        let raw = self.chain(first, None, false)?;
        let mut entries = Vec::new();
        for e in raw.chunks_exact(128) {
            let name_len = u16_at(e, 0x40) as usize;
            let n = name_len.min(64).saturating_sub(2);
            let units: Vec<u16> = e[..n].chunks_exact(2).map(|c| u16::from_le_bytes([c[0], c[1]])).collect();
            let mut size = u64_at(e, 0x78);
            if self.sector_size == 512 {
                size &= 0xFFFF_FFFF;
            }
            entries.push(Entry {
                name: String::from_utf16_lossy(&units),
                kind: e[0x42],
                left: u32_at(e, 0x44),
                right: u32_at(e, 0x48),
                child: u32_at(e, 0x4C),
                start: u32_at(e, 0x74),
                size,
            });
        }
        Ok(entries)
    }

    fn build_paths(&self) -> BTreeMap<String, usize> {
        let mut paths = BTreeMap::new();
        let mut seen = HashSet::new();
        let mut stack = vec![(self.entries[0].child, String::new())];
        while let Some((idx, prefix)) = stack.pop() {
            if idx == NOSTREAM || idx as usize >= self.entries.len() || !seen.insert(idx) {
                continue;
            }
            let e = &self.entries[idx as usize];
            stack.push((e.left, prefix.clone()));
            stack.push((e.right, prefix.clone()));
            let path = format!("{prefix}{}", e.name);
            if e.kind == 2 {
                paths.insert(path, idx as usize);
            } else if e.kind == 1 {
                stack.push((e.child, format!("{path}/")));
            }
        }
        paths
    }

    pub fn list(&self) -> Vec<String> {
        self.paths.keys().cloned().collect()
    }

    pub fn read(&self, path: &str) -> Result<Vec<u8>, CfbError> {
        let Some(&i) = self.paths.get(path) else { return err(format!("no stream {path}")) };
        let e = &self.entries[i];
        self.chain(e.start, Some(e.size), e.size < self.mini_cutoff)
    }
}
