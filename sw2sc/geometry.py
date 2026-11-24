"""SolidWorks part file -> STEP text, via its embedded Parasolid data.

Bodies are found in either place a part keeps them:
* ``Contents/Config-N-Partition`` - a Parasolid partition (root WORLD) with every body;
* ``Config-N-FeatureBodies/LocalBodies`` - newer files: one Parasolid part (root BODY) per
  body, each preceded by the body's name.
"""
from __future__ import annotations

import re
import struct

from . import parasolid, step, xtgeom
from .swfile import ZLB_GUID, SwFile, unzlb, zlb_sections

_CONFIG = re.compile(r"Config-(\d+)-", re.I)


def _config_of(name: str) -> int:
    m = _CONFIG.search(name)
    return int(m.group(1)) if m else 1 << 30


def _sw_string_before(blob: bytes, end: int) -> str:
    """The last length-prefixed UTF-16 string (ff fe ff <len> chars) before `end`."""
    i = blob.rfind(b"\xff\xfe\xff", max(0, end - 600), end)
    if i < 0:
        return ""
    n = blob[i + 3]
    raw = blob[i + 4:i + 4 + 2 * n]
    return raw.decode("utf-16-le", "replace") if len(raw) == 2 * n else ""


def parasolid_sources(sw: SwFile) -> list[tuple[str, bytes]]:
    """[(body name or '', transmit bytes)] for the first configuration that has geometry."""
    by_config: dict[int, list[tuple[str, bytes]]] = {}
    for n, blob in sw.streams.items():
        cfg = _config_of(n)
        if n.startswith("Contents/") and n.lower().endswith("-partition"):
            for sec in zlb_sections(blob):
                if sec[:4] == b"PS\x00\x00" and b"(partition)" in sec[:80]:
                    by_config.setdefault(cfg, []).append(("", sec))
        elif n.endswith("FeatureBodies/LocalBodies"):
            i = blob.find(ZLB_GUID)
            while i >= 0:
                try:
                    sec = unzlb(blob[i:])
                except Exception:
                    sec = b""
                if sec[:4] == b"PS\x00\x00" and b"(deltas)" not in sec[:80]:
                    name = re.sub(r"_\d+$", "", _sw_string_before(blob, i))
                    by_config.setdefault(cfg, []).append((name, sec))
                i = blob.find(ZLB_GUID, i + 16)
    for cfg in sorted(by_config):
        found = [(nm, sec) for nm, sec in by_config[cfg] if _has_body(sec)]
        # where the partition holds the part's solid, the named local bodies beside it are bodies
        # as they were imported (an import feature's own, before the features after it)
        if any(not nm for nm, _sec in found):
            found = [(nm, sec) for nm, sec in found if not nm]
        if found:
            return found
    return []


def local_bodies(sw: SwFile) -> dict:
    """The named bodies of `FeatureBodies/LocalBodies` (first configuration first): name -> the
    Parasolid transmit bytes. An imported body is kept here under its feature's name."""
    out: dict = {}
    for n in sorted(sw.streams, key=_config_of):
        if not n.endswith("FeatureBodies/LocalBodies"):
            continue
        blob = sw.streams[n]
        i = blob.find(ZLB_GUID)
        while i >= 0:
            try:
                sec = unzlb(blob[i:])
            except Exception:
                sec = b""
            if sec[:4] == b"PS\x00\x00" and b"(deltas)" not in sec[:80]:
                name = re.sub(r"_\d+$", "", _sw_string_before(blob, i))
                if name and name not in out:
                    out[name] = sec
            i = blob.find(ZLB_GUID, i + 16)
    return out


def body_step(data: bytes, name: str) -> str | None:
    """One Parasolid body as STEP text (None if it doesn't convert)."""
    try:
        part = parasolid.read(data)
    except parasolid.XtError:
        return None
    bodies = xtgeom.Converter(part).bodies()
    for b in bodies:
        b.name = name
    return step.write(bodies, name) if bodies else None


def _has_body(sec: bytes) -> bool:
    # cheap test: a partition with only its WORLD node is a few hundred bytes
    return len(sec) > 400 or b"(partition)" not in sec[:80]


def part_to_step(sw: SwFile, name: str) -> tuple[str | None, list[str], dict]:
    """(STEP text or None, warnings, stats)."""
    sources = parasolid_sources(sw)
    if not sources:
        return None, ["no Parasolid geometry found in the part"], {}
    bodies: list[xtgeom.Body] = []
    warnings: list[str] = []
    for body_name, data in sources:
        try:
            part = parasolid.read(data)
        except parasolid.XtError as e:
            warnings.append(f"geometry unreadable: {e}")
            continue
        conv = xtgeom.Converter(part)
        got = conv.bodies()
        for b in got:
            b.name = body_name
        bodies.extend(got)
        warnings.extend(conv.warnings)
    faces = [f for b in bodies for sh in b.outer + b.voids for f in sh.faces]
    stats = {
        "bodies": len(bodies),
        "faces": len(faces),
        "approx_faces": sum(1 for f in faces if f.approx),
        "faces_left_out": sum(1 for w in warnings if w.startswith("face ")),
    }
    if not bodies:
        return None, warnings + ["no bodies converted"], stats
    return step.write(bodies, name), warnings, stats
