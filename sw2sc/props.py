"""Custom (user-defined) document properties.

* 2015+ files keep them as XML (``docProps/custom.xml``, Office custom-properties
  schema).
* Older files keep them in the ``\\x05DocumentSummaryInformation`` stream, an OLE
  property set; this reader follows Microsoft's public [MS-OLEPS] specification.

Only the user-defined section is returned: ``{name: text}``.
"""
from __future__ import annotations

import struct
import xml.etree.ElementTree as ET

USER_DEFINED_FMTID = bytes.fromhex("05d5cdd59c2e1b10939708002b2cf9ae")
MAX_PROPS = 1024


def _clean(v: str) -> str:
    return "".join(ch for ch in v if ch >= " " or ch in "\t").strip()


def from_custom_xml(text: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not text:
        return out
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError:
        return out
    for section in root.iter():
        if section.tag.split("}")[-1] != "propertySection":
            continue
        if section.get("name") != "UserDefinedProperties":
            continue
        for prop in section:
            if prop.tag.split("}")[-1] != "property":
                continue
            name = prop.get("name") or ""
            if not name or len(out) >= MAX_PROPS:
                continue
            value = "".join(prop.itertext())
            out[name] = _clean(value)
    return out


def _decode(raw: bytes, codepage: int) -> str:
    enc = {65001: "utf-8", 1200: "utf-16-le", 1252: "cp1252", 936: "gbk", 932: "cp932"}.get(codepage, "latin-1")
    try:
        return raw.decode(enc, "replace").split("\0", 1)[0]
    except LookupError:
        return raw.decode("latin-1").split("\0", 1)[0]


def from_property_set(blob: bytes | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not blob or len(blob) < 48:
        return out
    try:
        nsections, = struct.unpack_from("<I", blob, 24)
        for s in range(min(nsections, 4)):
            fmtid = blob[28 + 20 * s:44 + 20 * s]
            offset, = struct.unpack_from("<I", blob, 44 + 20 * s)
            if fmtid == USER_DEFINED_FMTID:
                out.update(_section(blob, offset))
    except struct.error:
        pass
    return out


def _section(blob: bytes, base: int) -> dict[str, str]:
    _size, nprops = struct.unpack_from("<II", blob, base)
    nprops = min(nprops, MAX_PROPS)
    entries = [struct.unpack_from("<II", blob, base + 8 + 8 * i) for i in range(nprops)]
    offsets = dict(entries)
    codepage = 1252
    if 1 in offsets:
        vt, cp = struct.unpack_from("<IH", blob, base + offsets[1])
        if vt & 0xFFFF == 2:
            codepage = cp if cp < 0x8000 else cp - 0x10000 & 0xFFFF
    names: dict[int, str] = {}
    if 0 in offsets:
        p = base + offsets[0]
        count, = struct.unpack_from("<I", blob, p)
        p += 4
        for _ in range(min(count, MAX_PROPS)):
            pid, n = struct.unpack_from("<II", blob, p)
            p += 8
            if codepage == 1200:
                names[pid] = _decode(blob[p:p + 2 * n], 1200)
                p += 2 * n
                p += (-p) % 4
            else:
                names[pid] = _decode(blob[p:p + n], codepage)
                p += n
    out: dict[str, str] = {}
    for pid, off in entries:
        if pid in (0, 1) or pid not in names:
            continue
        val = _value(blob, base + off, codepage)
        if val is not None:
            out[names[pid]] = _clean(val)
    return out


def _value(blob: bytes, p: int, codepage: int) -> str | None:
    vt, = struct.unpack_from("<I", blob, p)
    vt &= 0xFFFF
    p += 4
    if vt == 0x1E:  # VT_LPSTR
        n, = struct.unpack_from("<I", blob, p)
        return _decode(blob[p + 4:p + 4 + n], codepage)
    if vt == 0x1F:  # VT_LPWSTR
        n, = struct.unpack_from("<I", blob, p)
        return _decode(blob[p + 4:p + 4 + 2 * n], 1200)
    if vt == 0x03:
        return str(struct.unpack_from("<i", blob, p)[0])
    if vt == 0x02:
        return str(struct.unpack_from("<h", blob, p)[0])
    if vt == 0x05:
        return repr(struct.unpack_from("<d", blob, p)[0])
    if vt == 0x0B:
        return "Yes" if struct.unpack_from("<h", blob, p)[0] else "No"
    return None
