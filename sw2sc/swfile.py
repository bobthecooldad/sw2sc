"""Open a SolidWorks .sldprt / .sldasm file and expose its named streams.

Two containers exist:

* ``cfb``   - pre-2015 files: a standard Compound File (see cfb.py). Streams
              whose name ends in ``__ZLB`` carry a 24-byte header (16-byte
              GUID, u32 raw size, u32 packed size) followed by zlib data.
* ``v2015`` - 2015+ files: a flat run of records. Learned from sample files:

      u32  record tag   (constant within a file, differs between files)
      u16  0x0014, u16 0x0006, u16 0x0008
      u32  stream type/flags
      u32  checksum (unverified)
      u32  packed size
      u32  raw size
      u32  name length
      name (each byte has its high/low nibbles swapped)
      data (raw DEFLATE, packed size bytes)

Both are exposed through the same ``SwFile.streams`` dict, with ``__ZLB``
streams already unpacked and the suffix dropped.
"""
from __future__ import annotations

import os
import struct
import zlib

from .cfb import MAGIC as CFB_MAGIC, CfbError, CompoundFile

MAX_FILE = 2 * 1024 ** 3
MAX_STREAM = 512 * 1024 ** 2
V2015_MARK = bytes.fromhex("140006000800")


class SwFormatError(Exception):
    pass


def _nibble_swap(b: bytes) -> bytes:
    return bytes(((x << 4) | (x >> 4)) & 0xFF for x in b)


def _inflate(data: bytes, raw_size: int, wbits: int) -> bytes:
    d = zlib.decompressobj(wbits)
    out = d.decompress(data, max(raw_size, 0) + 1 if raw_size else MAX_STREAM)
    if len(out) > MAX_STREAM:
        raise SwFormatError("stream too large")
    return out


ZLB_GUID = bytes.fromhex("231dd571da8148a2a85898b21b89ef99")


def unzlb(blob: bytes) -> bytes:
    """Unpack a ``__ZLB`` block: 16-byte GUID, then one or more chunks of
    (u32 raw size, u32 packed size, zlib data); large data is split into chunks."""
    if len(blob) < 24:
        raise SwFormatError("short ZLB stream")
    out: list[bytes] = []
    total = 0
    p = 16
    while p + 8 <= len(blob):
        raw, packed = struct.unpack_from("<II", blob, p)
        if packed == 0 or p + 8 + packed > len(blob) or blob[p + 8] != 0x78:
            break
        chunk = _inflate(blob[p + 8:p + 8 + packed], raw, 15)
        out.append(chunk)
        total += len(chunk)
        if total > MAX_STREAM:
            raise SwFormatError("stream too large")
        p += 8 + packed
    if not out:
        if struct.unpack_from("<I", blob, 16)[0] == 0:
            return b""  # an empty stream
        raise SwFormatError("no compressed data in ZLB stream")
    return b"".join(out)


def zlb_sections(blob: bytes) -> list[bytes]:
    """A stream holding several length-prefixed ZLB blocks (e.g. Config-N-Partition):
    u32 length, then the block; repeated."""
    out, p = [], 0
    while p + 4 <= len(blob):
        n, = struct.unpack_from("<I", blob, p)
        if n < 24 or p + 4 + n > len(blob) or blob[p + 4:p + 20] != ZLB_GUID:
            break
        out.append(unzlb(blob[p + 4:p + 4 + n]))
        p += 4 + n
    if not out:
        i = blob.find(ZLB_GUID)
        if i >= 0:
            out.append(unzlb(blob[i:]))
    return out


class SwFile:
    def __init__(self, path: str):
        self.path = path
        self.warnings: list[str] = []
        size = os.path.getsize(path)
        if size > MAX_FILE:
            raise SwFormatError("file larger than 2 GB")
        with open(path, "rb") as fh:
            data = fh.read()
        self.streams: dict[str, bytes] = {}
        if data[:8] == CFB_MAGIC:
            self.container = "cfb"
            self._load_cfb(data)
        elif V2015_MARK in data[:1 << 16]:
            self.container = "v2015"
            self._load_v2015(data)
        else:
            raise SwFormatError("not a recognised SolidWorks file")

    def _load_cfb(self, data: bytes) -> None:
        try:
            cf = CompoundFile(data)
        except CfbError as e:
            raise SwFormatError(f"compound file: {e}") from e
        for name in cf.list():
            try:
                blob = cf.read(name)
                if name.endswith("__ZLB"):
                    name, blob = name[:-5], unzlb(blob)
                self.streams[name] = blob
            except (CfbError, SwFormatError, zlib.error) as e:
                self.warnings.append(f"stream {name!r} unreadable: {e}")

    @staticmethod
    def _record_tag(data: bytes) -> bytes:
        """The per-file 4-byte tag: the most common prefix before the marker."""
        counts: dict[bytes, int] = {}
        i = data.find(V2015_MARK, 4)
        while i >= 0:
            k = data[i - 4:i]
            counts[k] = counts.get(k, 0) + 1
            i = data.find(V2015_MARK, i + 1)
        if not counts:
            raise SwFormatError("no records found")
        return max(counts, key=counts.get) + V2015_MARK

    def _load_v2015(self, data: bytes) -> None:
        V2015_TAG = self._record_tag(data)
        i = data.find(V2015_TAG)
        while i >= 0:
            if i + 30 > len(data):
                break
            _kind, _crc, packed, raw, nlen = struct.unpack_from("<IIIII", data, i + 10)
            start = i + 30 + nlen
            if nlen > 1024 or start + packed > len(data):
                self.warnings.append(f"bad record at {i:#x}")
                i = data.find(V2015_TAG, i + 1)
                continue
            name = _nibble_swap(data[i + 30:start]).decode("latin-1")
            try:
                blob = _inflate(data[start:start + packed], raw, -15) if packed else b""
                if name in self.streams:
                    self.warnings.append(f"duplicate stream {name!r}; keeping first")
                else:
                    self.streams[name] = blob
            except (zlib.error, SwFormatError) as e:
                self.warnings.append(f"stream {name!r} unreadable: {e}")
            i = data.find(V2015_TAG, start + packed)

    # ------------------------------------------------------------------
    def get(self, *names: str) -> bytes | None:
        for n in names:
            if n in self.streams:
                return self.streams[n]
        return None

    def xml(self, name: str) -> str | None:
        """A stream that holds XML text, with any leading junk bytes removed."""
        blob = self.get(name)
        if blob is None:
            return None
        start = blob.find(b"<")
        return blob[start:].decode("utf-8", "replace") if start >= 0 else None
