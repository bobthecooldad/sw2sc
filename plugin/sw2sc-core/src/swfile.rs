//! A SolidWorks `.sldprt` / `.sldasm` file and its named streams (port of `sw2sc/swfile.py`).
//!
//! Two containers exist:
//!
//! * `cfb`   - pre-2015 files: a standard Compound File (see `cfb`). Streams whose name ends in
//!   `__ZLB` carry a 16-byte GUID, then chunks of (u32 raw size, u32 packed size, zlib data).
//! * `v2015` - 2015+ files: a flat run of records, learned from sample files:
//!   u32 record tag (constant within a file), u16 0x14, u16 6, u16 8, u32 stream type/flags,
//!   u32 checksum, u32 packed size, u32 raw size, u32 name length, the name (each byte's nibbles
//!   swapped), then raw DEFLATE data.
//!
//! Both come out as one map of streams, `__ZLB` streams unpacked and the suffix dropped.

use std::collections::{BTreeMap, HashMap};

use miniz_oxide::inflate::{self, TINFLStatus};

use crate::cfb::{u32_at, CompoundFile, MAGIC as CFB_MAGIC};

pub const MAX_FILE: usize = 2 * 1024 * 1024 * 1024;
pub const MAX_STREAM: usize = 512 * 1024 * 1024;
const V2015_MARK: [u8; 6] = [0x14, 0x00, 0x06, 0x00, 0x08, 0x00];
const ZLB_GUID: [u8; 16] = [
    0x23, 0x1d, 0xd5, 0x71, 0xda, 0x81, 0x48, 0xa2, 0xa8, 0x58, 0x98, 0xb2, 0x1b, 0x89, 0xef, 0x99,
];

#[derive(Debug)]
pub struct SwFormatError(pub String);

impl std::fmt::Display for SwFormatError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

fn nibble_swap(b: &[u8]) -> Vec<u8> {
    b.iter().map(|&x| x.rotate_left(4)).collect()
}

/// Inflate up to `raw_size + 1` bytes (all of it, capped, when the size is unknown). A stream cut
/// short gives what it holds, as Python's `decompressobj` does; corrupt data is an error.
fn inflate_raw(data: &[u8], raw_size: usize, zlib: bool) -> Result<Vec<u8>, SwFormatError> {
    let limit = if raw_size > 0 { raw_size + 1 } else { MAX_STREAM };
    let got = if zlib {
        inflate::decompress_to_vec_zlib_with_limit(data, limit)
    } else {
        inflate::decompress_to_vec_with_limit(data, limit)
    };
    match got {
        Ok(v) => Ok(v),
        Err(e) => match e.status {
            TINFLStatus::HasMoreOutput | TINFLStatus::FailedCannotMakeProgress | TINFLStatus::NeedsMoreInput => {
                if e.output.len() > MAX_STREAM {
                    Err(SwFormatError("stream too large".into()))
                } else {
                    Ok(e.output)
                }
            }
            s => Err(SwFormatError(format!("inflate: {s:?}"))),
        },
    }
}

/// Unpack a `__ZLB` block: a 16-byte GUID, then one or more chunks of (u32 raw size, u32 packed
/// size, zlib data); large data is split into chunks.
pub fn unzlb(blob: &[u8]) -> Result<Vec<u8>, SwFormatError> {
    if blob.len() < 24 {
        return Err(SwFormatError("short ZLB stream".into()));
    }
    let mut out = Vec::new();
    let mut chunks = 0;
    let mut p = 16;
    while p + 8 <= blob.len() {
        let raw = u32_at(blob, p) as usize;
        let packed = u32_at(blob, p + 4) as usize;
        if packed == 0 || p + 8 + packed > blob.len() || blob[p + 8] != 0x78 {
            break;
        }
        out.extend(inflate_raw(&blob[p + 8..p + 8 + packed], raw, true)?);
        chunks += 1;
        if out.len() > MAX_STREAM {
            return Err(SwFormatError("stream too large".into()));
        }
        p += 8 + packed;
    }
    if chunks == 0 {
        if u32_at(blob, 16) == 0 {
            return Ok(vec![]); // an empty stream
        }
        return Err(SwFormatError("no compressed data in ZLB stream".into()));
    }
    Ok(out)
}

/// A stream holding several length-prefixed ZLB blocks (e.g. Config-N-Partition): u32 length,
/// then the block; repeated.
pub fn zlb_sections(blob: &[u8]) -> Result<Vec<Vec<u8>>, SwFormatError> {
    let mut out = Vec::new();
    let mut p = 0;
    while p + 4 <= blob.len() {
        let n = u32_at(blob, p) as usize;
        if n < 24 || p + 4 + n > blob.len() || blob[p + 4..p + 20] != ZLB_GUID {
            break;
        }
        out.push(unzlb(&blob[p + 4..p + 4 + n])?);
        p += 4 + n;
    }
    if out.is_empty() {
        if let Some(i) = find(blob, &ZLB_GUID, 0) {
            out.push(unzlb(&blob[i..])?);
        }
    }
    Ok(out)
}

/// The first `needle` in `hay` at or after `from`.
pub fn find(hay: &[u8], needle: &[u8], from: usize) -> Option<usize> {
    if needle.is_empty() || from > hay.len() {
        return None;
    }
    memchr::memmem::find(&hay[from..], needle).map(|i| i + from)
}

pub struct SwFile {
    pub name: String,
    pub container: &'static str,
    pub streams: BTreeMap<String, Vec<u8>>,
    pub warnings: Vec<String>,
}

impl SwFile {
    /// A file's streams from its bytes; `name` is only used in messages.
    pub fn from_bytes(name: &str, data: &[u8]) -> Result<Self, SwFormatError> {
        if data.len() > MAX_FILE {
            return Err(SwFormatError("file larger than 2 GB".into()));
        }
        let mut f = SwFile { name: name.into(), container: "", streams: BTreeMap::new(), warnings: vec![] };
        if data.len() >= 8 && data[..8] == CFB_MAGIC {
            f.container = "cfb";
            f.load_cfb(data)?;
        } else if find(&data[..data.len().min(1 << 16)], &V2015_MARK, 0).is_some() {
            f.container = "v2015";
            f.load_v2015(data)?;
        } else {
            return Err(SwFormatError("not a recognised SolidWorks file".into()));
        }
        Ok(f)
    }

    #[cfg(not(target_arch = "wasm32"))]
    pub fn open(path: &std::path::Path) -> Result<Self, SwFormatError> {
        let data = std::fs::read(path).map_err(|e| SwFormatError(e.to_string()))?;
        Self::from_bytes(&path.display().to_string(), &data)
    }

    fn load_cfb(&mut self, data: &[u8]) -> Result<(), SwFormatError> {
        let cf = CompoundFile::new(data).map_err(|e| SwFormatError(format!("compound file: {e}")))?;
        for name in cf.list() {
            let got = cf.read(&name).map_err(|e| e.to_string()).and_then(|blob| {
                if let Some(base) = name.strip_suffix("__ZLB") {
                    unzlb(&blob).map(|b| (base.to_string(), b)).map_err(|e| e.to_string())
                } else {
                    Ok((name.clone(), blob))
                }
            });
            match got {
                Ok((n, b)) => {
                    self.streams.insert(n, b);
                }
                Err(e) => self.warnings.push(format!("stream {name:?} unreadable: {e}")),
            }
        }
        Ok(())
    }

    /// The per-file 4-byte tag: the most common prefix before the marker (the first such, on a
    /// tie, as Python's `max` over an insertion-ordered dict).
    fn record_tag(data: &[u8]) -> Result<Vec<u8>, SwFormatError> {
        let mut counts: HashMap<&[u8], usize> = HashMap::new();
        let mut order: Vec<&[u8]> = Vec::new();
        let mut i = find(data, &V2015_MARK, 4);
        while let Some(at) = i {
            let k = &data[at - 4..at];
            let c = counts.entry(k).or_insert(0);
            if *c == 0 {
                order.push(k);
            }
            *c += 1;
            i = find(data, &V2015_MARK, at + 1);
        }
        let best = order.iter().copied().fold(None::<&[u8]>, |b, k| match b {
            Some(bk) if counts[bk] >= counts[k] => Some(bk),
            _ => Some(k),
        });
        let Some(tag) = best else { return Err(SwFormatError("no records found".into())) };
        let mut t = tag.to_vec();
        t.extend_from_slice(&V2015_MARK);
        Ok(t)
    }

    fn load_v2015(&mut self, data: &[u8]) -> Result<(), SwFormatError> {
        let tag = Self::record_tag(data)?;
        let mut i = find(data, &tag, 0);
        while let Some(at) = i {
            if at + 30 > data.len() {
                break;
            }
            let packed = u32_at(data, at + 18) as usize;
            let raw = u32_at(data, at + 22) as usize;
            let nlen = u32_at(data, at + 26) as usize;
            let start = at + 30 + nlen;
            if nlen > 1024 || start + packed > data.len() {
                self.warnings.push(format!("bad record at {at:#x}"));
                i = find(data, &tag, at + 1);
                continue;
            }
            let name: String = nibble_swap(&data[at + 30..start]).iter().map(|&c| c as char).collect();
            let blob = if packed > 0 { inflate_raw(&data[start..start + packed], raw, false) } else { Ok(vec![]) };
            match blob {
                Ok(b) => {
                    if self.streams.contains_key(&name) {
                        self.warnings.push(format!("duplicate stream {name:?}; keeping first"));
                    } else {
                        self.streams.insert(name, b);
                    }
                }
                Err(e) => self.warnings.push(format!("stream {name:?} unreadable: {e}")),
            }
            i = find(data, &tag, start + packed);
        }
        Ok(())
    }

    pub fn get(&self, names: &[&str]) -> Option<&[u8]> {
        names.iter().find_map(|n| self.streams.get(*n).map(|v| v.as_slice()))
    }

    /// A stream that holds XML text, with any leading junk bytes removed.
    pub fn xml(&self, name: &str) -> Option<String> {
        let blob = self.get(&[name])?;
        let start = blob.iter().position(|&c| c == b'<')?;
        Some(String::from_utf8_lossy(&blob[start..]).into_owned())
    }
}
