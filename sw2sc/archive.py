"""SolidWorks object streams (F-006): the records and their numbers.

The feature tree (`Contents/Config-N-ResolvedFeatures`) and the part's main section
(`Contents/Config-N`) are written in the layout of the publicly documented MFC `CArchive`
object format; see docs/clean-room.md. Every new class and every new object takes the next
number, and later records refer to a class as `0x8000 | number`.

- A new class: `FF FF`, u16 schema, u16 name length, ASCII name. It takes one number and its
  first object the next.
- An object of a class already numbered: `0x8000 | class number`. It takes one number.
- Newer files (SolidWorks 2015+) start the feature stream with a u32: the number the stream
  carries on from (classes numbered below it were written in other sections). Older files
  start with a u16 and carry on from `Contents/Config-N` instead; that start is not settled yet.

Field layouts per class are not decoded here; this only finds the records and numbers them,
so references between records can be followed.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass

_NAME = re.compile(rb"[A-Za-z_][A-Za-z0-9_]*")


@dataclass
class Record:
    offset: int       # where its tag starts in the stream
    number: int       # the object's number
    cls: str          # its class name ("pre<n>" for a class numbered in another section)
    new_class: bool   # the record also brought in the class (its number is number - 1)


def start_number(stream: bytes) -> int | None:
    """The number a feature stream carries on from, when its header says (2015+ files)."""
    if len(stream) >= 6 and stream[4:6] != b"\xff\xff" and stream[6:8] == b"\xff\xff":
        n = struct.unpack_from("<I", stream, 0)[0]
        return n if 0 < n < 0x7FFF else None
    return None


_NAMED_AFTER = re.compile(rb"([\x00-\xff][\x80-\xff])([\x00-\xff][\x80-\xff])\xff\xfe\xff", re.S)


def old_start_number(stream: bytes, outside: set | None = None) -> int | None:
    """The number a pre-2015 feature stream carries on from (it continues `Contents/Config-N`'s
    numbering and doesn't say where). Anchor: the three standard planes are written one after
    another, Front bringing in `moRefPlane_c` and the next two tagged with its number, in any
    language; the start is the one that gives `moRefPlane_c` that number. `outside` as for
    records()."""
    i = stream.find(b"moRefPlane_c")
    if i < 0:
        return None
    # moRefPlane_c's number is settled where it is brought in, so only the stream up to there is
    # numbered for each start tried: numbering the whole stream up to 600 times made opening a
    # large old file take minutes
    head = stream[:i + len(b"moRefPlane_c")]
    records_ = lambda s: records(head, s, outside)  # noqa: E731
    m = _NAMED_AFTER.search(stream, i + 12, i + 3000)
    if not m:
        return None
    target = struct.unpack("<H", m.group(1))[0] & 0x7FFF
    s = target
    seen = set()
    for _ in range(16):
        c = class_numbers(records_(s)).get("moRefPlane_c")
        if c is None:
            return None
        if c == target:
            return s
        seen.add(s)
        s += target - c
        if s in seen or s <= 0:
            break
    for s in range(max(1, target - 600), target + 1):  # not converging: search
        if class_numbers(records_(s)).get("moRefPlane_c") == target:
            return s
    return None


def records(stream: bytes, start: int | None = None, outside: set | None = None,
            resync: bool = False) -> list[Record]:
    """Every record that can be told apart by its tag, in order, with its number.

    `start` is the number the stream carries on from; by default the header's (2015+), else 0.
    `outside`: the numbers of the classes written in the section the stream carries on from
    (pre-2015 files: `Contents/Config-N`); a tag naming one of them is an object too. Without
    it every number below `start` is taken as such a class. A two-byte value that only looks
    like a tag inside some object's data is counted too, so numbers can run ahead in streams
    whose layouts aren't known; the checks in the tests say where the numbering is exact.
    """
    header = start_number(stream)
    if start is None:
        start = header
    if header is not None:
        pos = 6                      # u32 start, u16
    elif len(stream) > 4 and stream[2:4] == b"\xff\xff":
        pos = 2                      # pre-2015: a u16, then the first class
    else:
        pos = 0
    num = (start - 1) if start else 0
    classes: dict[int, str] = {}
    out: list[Record] = []
    n = len(stream)
    while pos < n - 1:
        if stream[pos] == 0xFF and stream[pos + 1] == 0xFF and pos + 6 < n:
            ln = struct.unpack_from("<H", stream, pos + 4)[0]
            name = stream[pos + 6:pos + 6 + ln]
            if 3 <= ln <= 64 and _NAME.fullmatch(name):
                num += 1
                classes[num] = name.decode()
                num += 1
                out.append(Record(pos, num, classes[num - 1], True))
                pos += 6 + ln
                continue
        tag = struct.unpack_from("<H", stream, pos)[0]
        k = tag & 0x7FFF
        kind = _anchored(stream, pos) if resync and tag & 0x8000 and tag != 0xFFFF and k not in classes else None
        if kind:
            # a real object starts here, so k is a class number: the count has drifted (tag-like
            # bytes inside data were counted). Shift the nearest class of the right kind and all
            # later ones.
            fits = [c for c, nm in classes.items() if _KIND[kind](nm) and c >= (start or 0)]
            near = min(fits, key=lambda c: abs(c - k)) if fits else None
            if near is not None and 0 < abs(near - k) <= RESYNC_MAX:
                delta = k - near
                classes = {(c + delta if c >= near else c): nm for c, nm in classes.items()}
                for r in out:
                    if r.number - (1 if r.new_class else 0) >= near and r.offset >= _intro(out, near):
                        r.number += delta
                num += delta
        if tag & 0x8000 and tag != 0xFFFF and (k in classes or (start and 0 < k < start and (outside is None or k in outside))):
            num += 1
            out.append(Record(pos, num, classes.get(k, f"pre{k}"), False))
            pos += 2
            continue
        pos += 1
    return out


RESYNC_MAX = 6


def _anchored(s: bytes, pos: int) -> str | None:
    """What the bytes after a tag show starts there: a named object (node tag, then `FF FE FF`),
    a curve handle (u16 id, `FF FF FF FF`, 4 zero bytes) or a component reference such as a
    plane reference (sub-tag, `02 00`, zero bytes); None when it isn't clear."""
    t = s[pos + 2:pos + 14]
    if t[1:2] == b"\x80" and t[2:5] == b"\xff\xfe\xff":
        return "named"
    if t[2:10] == b"\xff\xff\xff\xff\x00\x00\x00\x00":
        return "handle"
    if t[1:2] == b"\x80" and t[2:4] == b"\x02\x00" and t[4:12] == bytes(8):
        return "component"
    return None


_KIND = {"named": lambda nm: not nm.endswith("Handle") and not nm.startswith("moComp"),
         "handle": lambda nm: nm.endswith("Handle"),
         "component": lambda nm: nm.startswith("moComp")}


def _intro(out: list, number: int) -> int:
    for r in out:
        if r.new_class and r.number - 1 == number:
            return r.offset
    return 0


def class_numbers(recs: list[Record]) -> dict[str, int]:
    """Each class brought in by the stream and its number."""
    return {r.cls: r.number - 1 for r in recs if r.new_class}
