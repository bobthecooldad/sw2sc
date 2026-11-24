"""The feature tree of a SolidWorks part, read from its feature stream (F-006).

Reads `Contents/Config-0-ResolvedFeatures` with the object numbering of sw2sc.archive and
returns the features in order: sketches (points, lines, arcs, circles and the plane they are
on), extrudes and cut-extrudes (their sketch and depth), and every other feature as a TBD
entry with its name, so it keeps its place in the tree. See docs/clean-room.md for each layout
and logs/working-log.md for how it was found.

Only what has been checked is decoded; a feature is marked `"tbd"` with the reason otherwise.
Lengths come out in millimetres, positions in the part's model space.
"""
from __future__ import annotations

import html
import math
import re
import struct
from dataclasses import dataclass, field

from . import archive

STREAM = "Contents/Config-0-ResolvedFeatures"
SKETCH = "moProfileFeature_c"
BOSS = "moExtrusion_c"
REVOLVE = "moRevolution_c"
REVCUT = "moRevCut_c"
FILLET = "Fillet_c"
CHAMFER = "Chamfer_c"
HOLE = "moHoleWzd_c"
MIRRORS = {"moMirrorPattern_c", "moMirrorSolid_c"}
THREAD = "moSweepThread_c"
PATTERNS = {"moLPattern_c": "linear", "moCirPattern_c": "circular"}
# a Hole Wizard hole's named parameters (SolidWorks' own names) -> what they are
_HOLE_PARAMS = {"Hole Dia.": "diameter", "Thru Hole Dia.": "diameter", "Tap Drill Dia.": "diameter",
                "Hole Depth": "depth", "Thru Hole Depth": "depth", "Tap Drill Depth": "depth",
                "C'Sink Dia.": "cs_diameter", "C'Sink Angle": "cs_angle", "C'Bore Dia.": "cb_diameter",
                "C'Bore Depth": "cb_depth", "Drill Angle": "tip_angle",
                "Near C'Sink Dia.": "cs_diameter", "Near C'Sink Angle": "cs_angle",
                "Thru Tap Drill Dia.": "diameter", "Thru Tap Drill Depth": "depth",
                # Polish
                "Średnica otworu gwintowanego na wylot": "diameter", "Głębokość otworu gwintowanego na wylot": "depth",
                # French
                "Diamètre du perçage": "diameter", "Diamètre du perçage jusqu'au prochain": "diameter",
                "Profondeur du perçage": "depth", "Profondeur du perçage jusqu'au prochain": "depth",
                "Diamètre du fraisage entrant": "cs_diameter", "Angle du fraisage entrant": "cs_angle",
                "Diamètre du lamage": "cb_diameter", "Profondeur du lamage": "cb_depth",
                "Angle de pointe": "tip_angle"}
CUT = "moICE_c"
IMPORTED = {"moBaseBody_c", "moRefSurface_c", "moMirrorStock_c", "moMBimport_c", "moSplitBody_c"}  # a body (or surface) imported, or a mirror of another part file: no tree here
# Named records that are not features: folders, parameters, dimensions, handles and helper data.
# Every other named record is a feature, so a feature of a kind not converted yet still keeps its
# place in the tree as TBD instead of being skipped.
NOT_FEATURES = {"moDetailCabinet_c", "moFavoriteHandle_c", "moCompRefPlane_c", "moPointBackedUpData_c",
                "moOriginProfileFeature_c", "moPLine_c", "moVertexRef_c", "moIntegerParameter_c",
                "moScalerParameter_c", "moFoldUpDownSketchFolder_c", "moDimTolerance_c", "moAttributeDef_c",
                "moAttribute_c"}


def is_feature_class(cls: str) -> bool:
    return not (cls in NOT_FEATURES or cls.startswith("pre") or cls.startswith("sg") or
                cls.endswith(("Folder_c", "Parameter_c", "Dim", "Dim_c", "Handle", "Handle_c", "Data_c",
                              "IdRep_c", "Options_c", "Region_c", "ValG", "ValG_c", "ValG2_c", "Radial_c",
                              "Chain_c", "Ref_c", "Ref_w", "Spec_c", "IdRepN_c")))   # (…Spec_c: an extrude's end conditions)


FEATURE_CLASSES = None  # see is_feature_class
FRONT = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
TOL = 1e-9  # metres


@dataclass
class Sketch:
    name: str
    offset: int
    end: int = 0                                     # one past the sketch's records (its feature boundary)
    points: dict = field(default_factory=dict)       # id -> (x, y) in metres, sketch plane
    lines: list = field(default_factory=list)         # (point id, point id)
    construction: set = field(default_factory=set)    # indices into lines of construction lines
    alt_centres: dict = field(default_factory=dict)   # arc index -> the other centre it may have (x, y)
    dropped: list = field(default_factory=list)       # curves left out (a line with one end read)
    point_flags: dict = field(default_factory=dict)   # point id -> the byte after its header's `80 BF`
    region: list = field(default_factory=list)        # (kind, curve id) the file's region names
    chain: list = field(default_factory=list)         # the point ids a chain record names, in order
    arcs: list = field(default_factory=list)          # (start id, end id, centre id)
    circles: list = field(default_factory=list)       # (centre id, radius m)
    planes: list = field(default_factory=list)        # candidates: ((x, y, normal), translation, how)
    problems: list = field(default_factory=list)
    curve_of: dict = field(default_factory=dict)      # (line/arc, file curve id) -> SolidCraft curve id
    dims: list = field(default_factory=list)          # (name, SolidWorks class, value m/rad, handles)
    dims_skipped: list = field(default_factory=list)  # dimensions not written (meaning not decoded)
    relations: list = field(default_factory=list)     # (type, entity groups) as stored
    relations_skipped: int = 0                        # relations not written
    params: list = field(default_factory=list)        # model parameters its dimensions drive
    offsets: list = field(default_factory=list)       # offset loops: {loop, sources, param, value} (SolidCraft ids)
    used: bool = False                                # a later feature has taken its plane reference
    choice: int = 0                                   # which candidate plane the design uses

    def add_plane(self, plane, how: str, first: bool = False) -> None:
        if isinstance(plane, list):   # candidates (a face whose axes aren't stored)
            for one in (reversed(plane) if first else plane):
                self.add_plane(one, how, first)
            return
        same = lambda p: all(abs(a - c) < 1e-9 for u, v in zip(p[0], plane[0]) for a, c in zip(u, v)) and \
            all(abs(a - c) < 1e-9 for a, c in zip(p[1], plane[1]))
        if any(same(p) for p in self.planes):
            return
        item = (plane[0], plane[1], how)
        self.planes.insert(0, item) if first else self.planes.append(item)

    @property
    def plane(self):
        return (self.planes[self.choice][0], self.planes[self.choice][1]) if self.planes else None

    @property
    def plane_how(self) -> str:
        return self.planes[self.choice][2] if self.planes else "no plane reference found"


@dataclass
class Feature:
    kind: str           # sketch / boss / cut / import (a body imported into SolidWorks) / tbd
    name: str
    offset: int
    cls: str
    sketch: Sketch | None = None
    depth_mm: float | None = None
    profile: str | None = None   # name of the sketch an extrude uses
    reason: str = ""
    frame: tuple | None = None   # a plane feature's placement
    through_all: bool = False    # an extrude with no distance in the file
    angle_deg: float = 360.0     # a revolve's angle
    fid: int = 0                 # SolidWorks' id of the feature (what face references name)
    radius_mm: float | None = None   # a fillet's radius, a chamfer's distance
    chamfer_deg: float | None = None  # a chamfer's angle (None: its second distance is chamfer_mm2)
    chamfer_mm2: float | None = None
    hole: dict = field(default_factory=dict)  # a hole's sizes (mm, degrees) by SolidCraft's names
    alt_kind: str | None = None  # an extrude whose name says the other kind (boss / cut): tried too
    mirror_face: tuple | None = None  # a mirror's face: (side|end, feature id, entity|0/1)
    mirror_planes: list = field(default_factory=list)  # planes its record names: frames
    thread: dict = field(default_factory=dict)  # a thread's diameter, pitch, length (mm)
    pattern: dict = field(default_factory=dict)  # a pattern's kind, counts, spacings (mm) or angle (deg)
    thin_mm: float | None = None  # a thin extrude's wall thickness
    dome_mm: float | None = None  # a dome's height
    path: str | None = None       # a sweep's path sketch (its profile sketch is `profile`)
    scale: tuple | None = None    # a scale's factors (x, y, z)
    import_body: bytes | None = field(default=None, repr=False, compare=False)  # an import's body as imported
    import_step: str | None = field(default=None, repr=False, compare=False)    # … as STEP (made when written)
    edges: list = field(default_factory=list)  # a fillet's edges: (face, face), face = (side|end, feature id, entity|0/1)
    edge_ends: list = field(default_factory=list)  # for each edge, the two faces at its ends (they border its faces)


# --- the stream ------------------------------------------------------------------------------
def _data_start(b: bytes, r: archive.Record) -> int:
    return r.offset + (6 + struct.unpack_from("<H", b, r.offset + 4)[0] if r.new_class else 2)


def _name(b: bytes, r: archive.Record) -> str | None:
    """The name of a feature record: its node tag, then `FF FE FF`, u8 length, UTF-16."""
    s = _data_start(b, r)
    if b[s + 1:s + 2] != b"\x80" or b[s + 2:s + 5] != b"\xff\xfe\xff":
        return None
    n = b[s + 5]
    return b[s + 6:s + 6 + 2 * n].decode("utf-16le", "replace") if n else None


def _triads(b: bytes, start: int, end: int):
    """Offsets of 9 doubles forming 3 orthonormal axes (a rotation)."""
    for i in range(start, min(end, len(b) - 96)):
        v = struct.unpack_from("<9d", b, i)
        if not all(abs(x) <= 1.0000001 for x in v):
            continue
        r = (v[0:3], v[3:6], v[6:9])
        if all(abs(sum(c * c for c in a) - 1) < 1e-9 for a in r) and all(
                abs(sum(p * q for p, q in zip(r[a], r[c]))) < 1e-9 for a, c in ((0, 1), (0, 2), (1, 2))):
            yield i


# --- planes ---------------------------------------------------------------------------------
def _plane_record(b: bytes, off: int, is_new: bool):
    """(plane feature id, offset after it) of a moCompRefPlane_c object: tag, `02 00`, 41 zero
    bytes, [16 x FF, zeros, (2018+) a version stamp], u32 id."""
    i = off + (6 + struct.unpack_from("<H", b, off + 4)[0] if is_new else 2)
    # the sub-record's class tag: any class number (high bit set; numbers past 255 give 0x81…)
    if i + 4 > len(b) or not b[i + 1] & 0x80 or b[i + 2:i + 4] != b"\x02\x00":
        return None
    i += 4
    z = i
    while i < len(b) and b[i] == 0:
        i += 1
    # some files set a flag byte (01) inside the zero run, ahead of the FF block
    if i < len(b) and b[i] == 1:
        j = i + 1
        while j < len(b) and b[j] == 0:
            j += 1
        if j - z >= 40 and b[j:j + 16] == b"\xff" * 16:
            i = j
    if i - z < 40:
        return None
    if b[i:i + 16] == b"\xff" * 16:
        i += 16
        while i < len(b) and b[i] == 0:
            i += 1
        if b[i:i + 4] == b"\xff\xff\xff\xff":
            return 0xFFFFFFFF, i + 4
        v = struct.unpack_from("<I", b, i)[0]
        if 7000 <= v <= 40000 and v % 1000 == 0:  # version stamp
            i += 4
            v = struct.unpack_from("<I", b, i)[0]
        return v, i + 4
    return struct.unpack_from("<I", b, i)[0], i + 4


def _plane_frames(b: bytes, recs: list) -> tuple[dict, dict]:
    """Feature id -> (rotation, translation) of every named plane, and offset -> the same for
    every plane object (also unnamed ones). A plane square to the model stores no frame."""
    by_id, by_off = {}, {}
    for r in recs:
        if r.cls != "moRefPlane_c":
            continue
        s = _data_start(b, r)
        i = b.find(b"\xff\xfe\xff", s, s + 40)
        if i < 0:
            continue
        end = i + 4 + 2 * b[i + 3]
        t = next(_triads(b, end, end + 700), None)
        if t is not None:
            v = struct.unpack_from("<12d", b, t)
            ft = ((v[0:3], v[3:6], v[6:9]), v[9:12])
        else:
            ft = (FRONT, (0.0, 0.0, 0.0))
        by_off[r.offset] = ft
        tail = b[end:end + 10]
        if len(tail) == 10 and tail[:7] == bytes(7) and tail[7] in (0x40, 0xC0):
            by_id[struct.unpack_from("<H", tail, 8)[0]] = ft
    return by_id, by_off


def _face_frame_at(b: bytes, s0: int):
    """A face-plane record's data at s0: origin, the face's normal, a flag byte, then the sketch's
    x, y and z axes. The sketch faces out of the face: its normal is the face's, y = normal x x."""
    if s0 + 121 > len(b):
        return None
    d = lambda o: struct.unpack_from("<d", b, s0 + o)[0]  # noqa: E731
    origin = (d(0), d(8), d(16))
    normal = (d(24), d(32), d(40))
    x = (d(49), d(57), d(65)); y = (d(73), d(81), d(89)); z = (d(97), d(105), d(113))
    unit = lambda v: all(abs(c) <= 1.0000001 for c in v) and abs(sum(c * c for c in v) - 1) < 1e-6  # noqa: E731
    if not (unit(x) and unit(y) and unit(z) and unit(normal) and abs(sum(p * q for p, q in zip(x, y))) < 1e-6
            and all(abs(c) < 100 for c in origin)):
        return None
    n = normal
    y2 = (n[1] * x[2] - n[2] * x[1], n[2] * x[0] - n[0] * x[2], n[0] * x[1] - n[1] * x[0])
    first = ((x, y2, n), origin)
    # the record's own axes: where its z points into the part (against the face's normal) its y
    # is the other way from y2, and some files' sketches are drawn in it (a bracket's sketches on
    # its side faces came out mirrored): a second candidate, which the rebuild check chooses
    if sum(p * q for p, q in zip(y, y2)) < 0:
        z2 = (x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0])
        return [first, ((x, y, z2), origin)]
    return first


def _face_candidates(b, recs, after, end):
    """A face record whose axes aren't stored (some versions keep only the face's origin and
    normal, then a box): the sketch's x axis along each world axis projected onto the face, both
    ways, as candidate frames for the rebuild check to choose between."""
    starts = [_data_start(b, r) for r in recs if after <= r.offset <= min(after + 1500, end) and r.cls == "moFaceRefPlnData_c"][:1]
    if not starts:
        # its class not named (the numbering drifts): the first unit vector after the reference
        # is the face's normal, the three doubles before it its origin
        for k in range(after + 24, min(after + 1500, end, len(b) - 24)):
            n = struct.unpack_from("<3d", b, k)
            if all(abs(c) <= 1.0000001 for c in n) and abs(sum(c * c for c in n) - 1) < 1e-9:
                starts = [k - 24]
                break
    for s0 in starts:
        if s0 + 48 > len(b):
            return []
        v = struct.unpack_from("<6d", b, s0)
        origin, n = v[0:3], v[3:6]
        if abs(sum(c * c for c in n) - 1) > 1e-6 or any(abs(c) >= 100 for c in origin):
            return []
        out = []
        for a in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)):
            dot = sum(p * q for p, q in zip(a, n))
            x = tuple(p - dot * q for p, q in zip(a, n))
            ln = sum(c * c for c in x) ** 0.5
            if ln < 0.5:
                continue      # (nearly) along the normal
            x = tuple(c / ln for c in x)
            for sgn in (1.0, -1.0):
                xs = tuple(sgn * c for c in x)
                y = (n[1] * xs[2] - n[2] * xs[1], n[2] * xs[0] - n[0] * xs[2], n[0] * xs[1] - n[1] * xs[0])
                out.append(((xs, y, tuple(n)), tuple(origin)))
        return out
    return []


def _face_plane(b, recs, after):
    """A plane on a face (moFaceRefPlnData_c after a -1 plane reference). Found by its class, or
    else by its layout, for files where stray bytes have thrown the numbering off."""
    for r in recs:
        if r.offset < after:
            continue
        if r.offset > after + 1500:
            break
        if r.cls == "moFaceRefPlnData_c":
            return _face_frame_at(b, _data_start(b, r))
    for s0 in range(after, min(after + 1500, len(b) - 121)):
        got = _face_frame_at(b, s0)
        if got:
            return got
    return None


def _plane_before(b, recs, k, by_id, by_off):
    """The plane reference written right before recs[k] (a sketch or a feature), read."""
    j = k - 1
    while j >= 0 and recs[j].cls.startswith("pre") and recs[k].offset - recs[j].offset < 600:
        j -= 1
    if j < 0 or recs[j].cls != "moCompRefPlane_c" or recs[k].offset - recs[j].offset >= 600:
        return None, "no plane reference before it"
    return _plane_from_ref(b, recs, recs[j], by_id, by_off)


def _plane_from_ref(b, recs, ref, by_id, by_off):
    got = _plane_record(b, ref.offset, ref.new_class)
    if not got:
        return None, "plane reference not read"
    pid, after = got
    t = next(_triads(b, after, after + 200), None)
    if t is not None:
        v = struct.unpack_from("<12d", b, t)
        return ((v[0:3], v[3:6], v[6:9]), v[9:12]), "rotation in the plane reference"
    if pid == 0xFFFFFFFF:
        face = _face_plane(b, recs, after)
        if face:
            return face, "face the sketch is on"
        nxt = sorted(o for o in by_off if after <= o < after + 400)
        if nxt:
            return by_off[nxt[0]], "plane object after the reference"
        cands = _face_candidates(b, recs, after, after + 1500)
        if cands:
            return cands, "face the sketch is on, its axes tried"
        return None, "sketch on a face: plane not read"
    if pid in by_id:
        return by_id[pid], f"plane feature {pid}"
    return None, f"plane feature {pid} not found"


@dataclass
class _Ref:
    offset: int
    new_class: bool = False


# (a flag byte 01 can sit in the zero run: _plane_record checks the rest)
_REF_SHAPE = re.compile(rb"[\x00-\xff][\x80-\xff][\x00-\xff][\x80-\xff]\x02\x00(?:\x00{40}|\x00{20,39}\x01\x00{1,20})", re.S)


def _plane_refs(b: bytes, recs: list, lo: int, hi: int) -> list:
    """Plane references between two offsets: the records numbered as moCompRefPlane_c, or else
    anything with their shape (tag, sub-tag, `02 00`, a long zero run) whose plane id reads, for
    files where stray bytes have thrown the numbering off."""
    refs = [x for x in recs if lo < x.offset < hi and x.cls == "moCompRefPlane_c"]
    if refs:
        return refs
    out = []
    for m in _REF_SHAPE.finditer(b, lo, hi):
        if _plane_record(b, m.start(), False):
            out.append(_Ref(m.start()))
    return out


def _plane_inside(b, recs, s, e, by_id, by_off):
    """A sketch's plane written inside its own records: a Hole Wizard hole's placement sketch
    lists its points first, then the plane reference (`moCompRefPlane_c`) and the face it is
    on."""
    named = [(r.offset, r.new_class) for r in recs if s <= r.offset < e and r.cls == "moCompRefPlane_c"]
    # where the numbering drifts, by their shape (as _plane_refs)
    shaped = [(m.start(), False) for m in _REF_SHAPE.finditer(b, s, e)]
    for off, new_class in named + [x for x in shaped if x[0] not in {o for o, _n in named}]:   # (a named one may not read)
        got = _plane_record(b, off, new_class)
        if not got:
            continue
        pid, after = got
        t = next(_triads(b, after, after + 200), None)
        if t is not None:
            v = struct.unpack_from("<12d", b, t)
            return ((v[0:3], v[3:6], v[6:9]), v[9:12]), "rotation in its plane reference"
        if pid == 0xFFFFFFFF:
            face = _face_plane(b, recs, after)
            if face:
                return face, "face it is on (after its points)"
            nxt = sorted(o for o in by_off if after <= o < after + 400)
            if nxt:
                return by_off[nxt[0]], "plane object after its plane reference (after its points)"
            # the plane object's frame by its shape (nine orthonormal doubles, a translation),
            # where the numbering drifts and its class isn't named
            t = next(_triads(b, after, min(after + 1500, e)), None)
            if t is not None:
                v = struct.unpack_from("<12d", b, t)
                return ((v[0:3], v[3:6], v[6:9]), v[9:12]), "frame after its plane reference, by shape (after its points)"
            cands = _face_candidates(b, recs, after, e)
            if cands:
                return cands, "face it is on (after its points), its axes tried"
        elif pid in by_id:
            return by_id[pid], f"plane feature {pid} (after its points)"
    return None, ""


def _sketch_plane(b, recs, k, by_id, by_off):
    """The plane of the sketch whose record is recs[k]: the plane reference written right before
    it (checked against the sketches' dimension normals: 68 of 73 agree)."""
    j = k - 1
    while j >= 0 and recs[j].cls.startswith("pre") and recs[k].offset - recs[j].offset < 600:
        j -= 1
    if j < 0 or recs[j].cls != "moCompRefPlane_c" or recs[k].offset - recs[j].offset >= 600:
        return None, "no plane reference before the sketch"
    got = _plane_record(b, recs[j].offset, recs[j].new_class)
    if not got:
        return None, "plane reference not read"
    pid, after = got
    t = next(_triads(b, after, after + 200), None)
    if t is not None:
        v = struct.unpack_from("<12d", b, t)
        return ((v[0:3], v[3:6], v[6:9]), v[9:12]), "rotation in the plane reference"
    if pid == 0xFFFFFFFF:
        face = _face_plane(b, recs, after)
        if face:
            return face, "face the sketch is on"
        nxt = sorted(o for o in by_off if after <= o < after + 400)
        if nxt:
            return by_off[nxt[0]], "plane object after the reference"
        cands = _face_candidates(b, recs, after, after + 1500)
        if cands:
            return cands, "face the sketch is on, its axes tried"
        return None, "sketch on a face: plane not read"
    if pid in by_id:
        return by_id[pid], f"plane feature {pid}"
    return None, f"plane feature {pid} not found"


# --- sketch entities --------------------------------------------------------------------------
def _class_tags(recs: list) -> dict:
    return {0x8000 | (r.number - 1): r.cls for r in recs if r.new_class}


def _region_curves(b: bytes, s: int, e: int, tags: dict) -> list:
    """The curves the sketch's region records name, as (kind, curve id): the region is the closed
    shape SolidWorks made, so it says which curves bound it and, for each, whether it is a line
    or an arc — the one place a curve read from a single point can be told from a circle. Each
    curve is written `<tag> <id> FF FF FF FF 00 00`, the tag being the file's own number for
    `sgLineHandle` / `sgArcHandle`."""
    out = []
    i = b.find(b"moSketchRegion_c", s, e)
    while i >= 0:
        j = i + len(b"moSketchRegion_c")
        stop = b.find(b"moSketchChain_c", j, e)
        stop = stop if stop > 0 else min(e, j + 8192)
        words = [struct.unpack_from("<H", b, k)[0] for k in range(j, max(j, stop - 1), 2)]
        for k in range(len(words) - 3):
            cls = tags.get(words[k])
            if cls in ("sgArcHandle", "sgLineHandle") and words[k + 1] < 4000 \
                    and words[k + 2] == 0xFFFF and words[k + 3] == 0xFFFF:
                kind = "arc" if cls == "sgArcHandle" else "line"
                if (kind, words[k + 1]) not in out:
                    out.append((kind, words[k + 1]))
        i = b.find(b"moSketchRegion_c", stop, e)
    return out


def _chain_points(b: bytes, s: int, e: int) -> list:
    """The points a sketch's `moSketchChain_c` record names, in order: a `u16` count, then that
    many `u32` point ids. 196 parts write one, at the end of the sketch, and its ids are the
    sketch's own point numbers (Bucket: 12 ids, its 12 lines' points; spring_holder_v1: 10;
    PartT_7: 18, 19, 20, 17). It says which points a chain runs through, not which way its curves
    go, and a one-point curve is named no differently from a circle's, so it does not settle
    F-047 either."""
    out: list = []
    i = b.find(b"moSketchChain_c", s, e)
    if i < 0:
        return out
    j = i + len(b"moSketchChain_c")
    n = struct.unpack_from("<H", b, j)[0]
    if not 0 < n < 4096 or j + 2 + 4 * n > len(b):
        return out
    for k in range(n):
        pid = struct.unpack_from("<I", b, j + 2 + 4 * k)[0]
        if pid == 0xFFFFFFFF:
            return out   # a count that ran past the record: nothing to trust
        out.append(pid)
    return out


def _read_sketch(b: bytes, tags: dict, sk: Sketch, s: int, e: int, learned: dict | None = None) -> None:
    """Points (u32 id, `FF FF 1F 00`, …, `1E 00`, x, y) and the curves each lies on (handles:
    class tag or new-class header, u16 curve id, FF FF FF FF, 4 zero bytes).

    Where the stream's numbering has drifted, a handle class brought in inline (new-class
    header) is then used by a tag the numbering doesn't give that class: such a tag is taken as
    the handle class brought in most recently that no tag has yet (learned per sketch, and
    used for the sketch's dimensions and relations too). `learned`: such tags from the sketches
    before (a class is brought in once, in the first sketch using it); it gets this one's."""
    base = tags
    tags = dict(tags)
    tags.update(learned or {})   # (learned where the numbering gave a tag the wrong class too)
    inline: list[str] = []   # handle classes brought in inline here, no tag known for them yet
    unknown: dict = {}       # (tag, curve id) -> points, for handle tags of no known class
    known_tag = {v: t for t, v in tags.items() if v.endswith("Handle")}
    curves: dict[tuple[str, int], list[int]] = {}
    plain: list[int] = []   # points on no curve (arc centres among them), in record order
    entries: list = []      # every handle in a point's list: (tag or None, class brought in, curve id, point)
    pts_order: list[int] = []
    for m in re.finditer(rb"\xff\xff\x1f\x00", b[s:e]):
        i = s + m.start()
        j = b.find(b"\x1e\x00", i + 30, i + 80)
        # the point's x, y follow `F0 3F 1E 00`; newer files put 8 zero bytes before the `1E 00`
        if j < 0 or j + 22 > len(b) or not (b[j - 2:j] == b"\xf0\x3f" or b[j - 10:j] == b"\xf0\x3f" + bytes(8)):
            continue
        pid = struct.unpack_from("<I", b, i - 4)[0]
        if pid == 0xFFFFFFFF:
            continue  # positions of dimension text, not points
        x, y = struct.unpack_from("<dd", b, j + 2)
        if not (abs(x) < 100 and abs(y) < 100):
            continue
        sk.points[pid] = (x, y)
        if i + 18 <= len(b):
            sk.point_flags[pid] = b[i + 17]     # 0 a point SolidWorks made, 1 / 2 one the user placed (so far)
        k = j + 18 + 4
        n_on = 0
        pts_order.append(pid)
        for _ in range(16):
            if b[k:k + 2] == b"\xff\xff":
                ln = struct.unpack_from("<H", b, k + 4)[0]
                cname = b[k + 6:k + 6 + ln].decode("latin1")
                tag = None          # (a class brought in here: no tag)
                if cname.endswith("Handle") and cname not in inline:
                    inline.append(cname)
                k += 6 + ln
            else:
                tag = struct.unpack_from("<H", b, k)[0]
                if not tag & 0x8000 or tag == 0xFFFF:
                    break
                cname = tags.get(tag, "")
                k += 2
            cid = struct.unpack_from("<H", b, k)[0]
            if b[k + 2:k + 6] != b"\xff\xff\xff\xff":
                break
            entries.append((tag, cname if tag is None else None, cid, pid))
            if cname in ("sgLineHandle", "sgArcHandle"):
                curves.setdefault((cname, cid), []).append(pid)
                n_on += 1
            elif tag is not None and cname not in ("sgLineHandle", "sgArcHandle"):
                unknown.setdefault((tag, cid), []).append(pid)   # a handle whose class isn't known
            k += 10
        if not n_on:
            plain.append(pid)
    # Handle tags of no known class (the numbering drifted, or gave a point's handle list a
    # point class: a point lies on curves, never on a point). A class's tag is the object count
    # when it was brought in, so classes brought in inline here take the unknown tags in order:
    # the earliest class the smallest tag. Checked: a line has two ends.
    by_tag: dict = {}
    for (t, cid), ps in unknown.items():
        by_tag.setdefault(t, []).append((cid, ps))
    order = [c for c in inline if c in ("sgLineHandle", "sgArcHandle")]
    # The same, where the numbering is off by a class or so: it can give a tag the class of a
    # neighbour, a curve class among them. A tag it gives a class this sketch brings in is no
    # more certain than one it doesn't know (Boom: line and arc handles under the point's and
    # the line's numbers), so those take the classes in order too.
    curve_cls = ("sgLineHandle", "sgArcHandle")
    listed: dict = {}
    for t, _c, cid, pid in entries:
        if t is not None:
            listed.setdefault(t, {}).setdefault(cid, []).append(pid)
    cand = sorted(t for t in listed if t not in (learned or {}) and
                  not (tags.get(t) in curve_cls and tags.get(t) not in order))
    if order and len(cand) == len(order) and any(tags.get(t) in curve_cls for t in cand) and \
            not any(c == "sgLineHandle" and any(len(set(ps)) > 2 for ps in listed[t].values())
                    for t, c in zip(cand, order)):
        give = dict(zip(cand, order))
        curves = {}
        for t, c, cid, pid in entries:
            nm = c if t is None else give.get(t, tags.get(t, ""))
            if nm in curve_cls:
                curves.setdefault((nm, cid), []).append(pid)
        tags.update(give)
        on = {pid for ps in curves.values() for pid in ps}
        plain[:] = [x for x in pts_order if x not in on]
        by_tag = {}
    utags = sorted(by_tag)
    if order and len(utags) == len(order):
        for t, cname in zip(utags, order):
            if cname == "sgLineHandle" and any(len(set(ps)) > 2 for _c, ps in by_tag[t]):
                break
        else:
            for t, cname in zip(utags, order):
                for cid, ps in by_tag[t]:
                    curves.setdefault((cname, cid), []).extend(ps)
                tags[t] = cname
            on = {pid for items in by_tag.values() for _c, ps in items for pid in ps}
            plain[:] = [x for x in plain if x not in on]
            by_tag = {}
    # an unknown handle tag every curve of which has one point only is a circle's (a line or an
    # arc has two ends); its points are on a curve after all
    for t, items in by_tag.items():
        if all(len(set(ps)) == 1 for _c, ps in items):
            for cid, ps in items:
                key = ("sgArcHandle", cid)
                if key not in curves:
                    curves[key] = list(ps)
                    if ps[0] in plain:
                        plain.remove(ps[0])
                    tags[t] = "sgArcHandle"
    if learned is not None:
        learned.update({t: v for t, v in tags.items() if base.get(t) != v and v.endswith("Handle")})
    P = sk.points
    d = lambda a, c: math.hypot(P[a][0] - P[c][0], P[a][1] - P[c][1])
    sk.region = _region_curves(b, s, e, tags)   # what the file's own region is made of
    sk.chain = _chain_points(b, s, e)           # the points its chain runs through, in order
    # An arc's centre: SolidWorks numbers an arc's points as it makes them (start, end, centre),
    # so the centre is the first point on no curve numbered after the arc's own points, among
    # those at the same distance from both ends. A full circle has one point, then its centre.
    used: set[int] = set()
    partial: dict[int, list[int]] = {}   # lines read with one end only
    line_ends = [tuple(dict.fromkeys(ps)) for (cn, _c), ps in curves.items() if cn == "sgLineHandle" and len(set(ps)) == 2]

    # a circle's point and its centre are numbered one after the other: where the next number is
    # a point on no arc (a line may start at the centre), it is that circle's, and no other's
    one_end = {ps[0] for (cn, _c), ps in curves.items() if cn == "sgArcHandle" and len(set(ps)) == 1}
    on_arc = {p for (cn, _c), ps in curves.items() if cn == "sgArcHandle" for p in ps}
    reserved = {q + 1 for q in one_end if q + 1 in P and q + 1 not in on_arc and d(q, q + 1) > TOL}

    def centre_for(ends: list[int]) -> int | None:
        top = max(ends)
        if len(ends) == 1 and top + 1 in reserved:
            return top + 1
        if len(ends) == 1 and top + 1 in one_end:
            # its next number is another circle's point (circles drawn one after another, their
            # centres on points already there): the nearest point not a circle's or an arc's
            near = sorted((c for c in P if c not in on_arc and c not in reserved and d(c, top) > TOL),
                          key=lambda c: d(c, top))
            if near:
                return near[0]
        if len(ends) == 1:  # a circle: its centre is the next point on no curve
            cands = sorted(c for c in plain if c > top and c not in used and c not in reserved and d(c, ends[0]) > TOL)
            if not cands:   # concentric circles (a ring) share their centre
                cands = sorted(c for c in plain if c > top and d(c, ends[0]) > TOL)
            if not cands:
                # none after it (a circle drawn on a point already there, e.g. a rectangle's
                # corner): the nearest point on no curve
                near = sorted((c for c in plain if c not in used and d(c, ends[0]) > TOL), key=lambda c: d(c, ends[0])) or \
                    sorted((c for c in plain if d(c, ends[0]) > TOL), key=lambda c: d(c, ends[0]))   # a ring's shared centre
                return near[0] if near else None
            return cands[0]
        # an arc: a point on no curve at the same distance from both ends. Several can be (the
        # far corner of a slot, the next fillet's centre); prefer the one that makes the arc
        # tangent to the lines it meets (fillets, slots, rounded outlines), then SolidWorks' id
        # order (start, end, centre), then the nearest.
        cands = [c for c in plain if c not in used and abs(d(c, ends[0]) - d(c, ends[1])) < TOL
                 and d(c, ends[0]) > TOL]
        if not cands:
            # concentric arcs share their centre: a point another arc already has will do
            cands = [c for c in plain if abs(d(c, ends[0]) - d(c, ends[1])) < TOL and d(c, ends[0]) > TOL]
        if not cands:
            # a centre a line is drawn from (a slot's axis, a radius line): a point on a curve
            cands = [c for c in P if c not in ends and abs(d(c, ends[0]) - d(c, ends[1])) < TOL and d(c, ends[0]) > TOL]
        if not cands:
            return None

        def tangent_joins(c: int) -> int:
            n = 0
            for e in ends:
                for a2, b2 in line_ends:
                    if e in (a2, b2):
                        o = b2 if e == a2 else a2
                        ux, uy = P[o][0] - P[e][0], P[o][1] - P[e][1]
                        rx, ry = P[e][0] - P[c][0], P[e][1] - P[c][1]
                        if abs(ux * rx + uy * ry) <= 1e-6 * math.hypot(ux, uy) * math.hypot(rx, ry):
                            n += 1
            return n
        return min(cands, key=lambda c: (-tangent_joins(c), c <= top, d(c, ends[0]), c))

    for (cname, cid), ps in sorted(curves.items(), key=lambda kv: max(kv[1])):
        ps = list(dict.fromkeys(ps))
        if cname == "sgLineHandle":
            if len(ps) == 2:
                sk.lines.append((ps[0], ps[1]))
                sk.curve_of[("line", cid)] = f"l{len(sk.lines)}"
            else:
                sk.problems.append(f"line {cid} has {len(ps)} end points")
                partial[cid] = ps
        elif len(ps) in (1, 2):
            c = centre_for(ps)
            if c is None:
                sk.problems.append(f"arc {cid}: no centre found (ends {ps})")
                continue
            used.add(c)
            if len(ps) == 2:
                sk.arcs.append((ps[0], ps[1], c))
                sk.curve_of[("arc", cid)] = f"a{len(sk.arcs)}"
            else:
                sk.circles.append((c, d(c, ps[0])))
                sk.curve_of[("arc", cid)] = f"c{len(sk.circles)}"
        else:
            sk.problems.append(f"arc {cid} has {len(ps)} points")
    _read_segments(b, sk, s, e, partial)
    # a line read with one end only (the other a point that isn't read: projected geometry,
    # often a centreline) is left out and noted; if an outline needed it, its loop doesn't close
    # and the rebuild check says so
    for pr in [x for x in sk.problems if re.fullmatch(r"line \d+ has 1 end points", x)]:
        sk.problems.remove(pr)
        sk.dropped.append(pr)
    # The region's curves are kept for the reading to be checked against (SolidWorks writes one
    # record per closed region). They are not yet used to change the reading: the handle class
    # it names is `sgArcHandle`, which covers circles as well as arcs, so one point and an arc
    # tag is not enough to tell an arc whose other end wasn't written from a circle.
    _tangent_centres(sk)
    _alternative_centres(sk)
    if any(v == "sgTextHandle" for v in tags.values()) and b.find(b"sgTextHandle", s, e) >= 0:
        # the words, their size and place are stored (moDimText_c, utCharFormat_c), not the letters'
        # outlines: SolidCraft would draw its own, which the rebuild check can't match exactly
        sk.problems.append("sketch text: SolidWorks keeps the words, size and place but not the letters' shapes, so SolidCraft's own lettering can't be matched to the solid exactly")
    _read_dimensions(b, tags, sk, s, e)
    _read_relations(b, tags, sk, s, e)
    _centres_from_relations(sk)


def _centres_from_relations(sk: Sketch) -> None:
    """A circle read from one point whose centre wasn't found: its centre's point record may be
    missing, its id still next to the circle's point (a circle's point and centre are numbered
    one after the other). A coincident relation (9) that puts that id on a point read places the
    centre there (Concentric: a circle's centre coincident with the sketch origin)."""
    for pr in list(sk.problems):
        m = re.fullmatch(r"arc (\d+): no centre found \(ends \[(\d+)\]\)", pr)
        if not m:
            continue
        cid, end = int(m.group(1)), int(m.group(2))
        at = None
        for t, groups in sk.relations:
            if t != 9:
                continue
            for g in groups:
                ids = [h + 1 for kind, h in g if kind == "point"]   # a point handle's id is the point's - 1
                if len(ids) != 2:
                    continue
                for a, c in (ids, ids[::-1]):
                    if a in (end - 1, end + 1) and a not in sk.points and c in sk.points and c != end:
                        at = at or c
        if at is None or math.dist(sk.points[at], sk.points[end]) < TOL:
            continue
        sk.problems.remove(pr)
        sk.circles.append((at, math.dist(sk.points[at], sk.points[end])))
        sk.curve_of[("arc", cid)] = f"c{len(sk.circles)}"


def _tangent_centres(sk: Sketch) -> None:
    """An arc whose centre, as read, leaves every line meeting it at a corner, where another point
    of the sketch is as far from both its ends and makes every one of those lines tangent: that
    point is its centre (a hub's outline read with the top of a lobe as its big arc's centre, the
    true centre the origin)."""
    P = sk.points

    def tangent(e, o, cx, cy):
        ux, uy = P[o][0] - P[e][0], P[o][1] - P[e][1]
        rx, ry = P[e][0] - cx, P[e][1] - cy
        return abs(ux * rx + uy * ry) <= 1e-6 * math.hypot(ux, uy) * math.hypot(rx, ry)

    for n, (a, c, ctr) in enumerate(sk.arcs):
        meet = [(e, lb if e == la else la) for la, lb in sk.lines for e in (a, c) if e in (la, lb)]
        if not meet or any(tangent(e, o, *P[ctr]) for e, o in meet):
            continue
        for q in sorted(P):
            if q in (a, c, ctr):
                continue
            qx, qy = P[q]
            da, dc = math.hypot(P[a][0] - qx, P[a][1] - qy), math.hypot(P[c][0] - qx, P[c][1] - qy)
            if da > TOL and abs(da - dc) <= 1e-6 * da and all(tangent(e, o, qx, qy) for e, o in meet):
                sk.arcs[n] = (a, c, q)
                break


def _alternative_centres(sk: Sketch) -> None:
    """An arc's other possible centre. Through its two ends there are two circles of its
    radius, mirror images across the chord; the point taken as its centre may be the wrong one
    (idler_differential_arm, a 2013 file: no point record at the true centre, the point taken is
    its mirror). Where no line meets the arc tangentially at either end (a tangency would
    settle it), the mirror is kept as an alternative for the rebuild check to choose."""
    P = sk.points
    for n, (a, c, ctr) in enumerate(sk.arcs):
        (ax, ay), (bx, by), (cx, cy) = P[a], P[c], P[ctr]
        chord = math.hypot(bx - ax, by - ay)
        if chord < TOL:
            continue
        tangent = False
        for la, lb in sk.lines:
            for e in (a, c):
                if e in (la, lb):
                    o = lb if e == la else la
                    ux, uy = P[o][0] - P[e][0], P[o][1] - P[e][1]
                    rx, ry = P[e][0] - cx, P[e][1] - cy
                    if abs(ux * rx + uy * ry) <= 1e-6 * math.hypot(ux, uy) * math.hypot(rx, ry):
                        tangent = True
        if tangent:
            continue
        # reflect the centre across the chord's line
        dx, dy = (bx - ax) / chord, (by - ay) / chord
        t = (cx - ax) * dx + (cy - ay) * dy
        fx, fy = ax + t * dx, ay + t * dy
        mx, my = 2 * fx - cx, 2 * fy - cy
        if math.hypot(mx - cx, my - cy) > TOL:
            sk.alt_centres[n] = (mx, my)


def with_centres(sk: Sketch, flips) -> Sketch:
    """The sketch with the arcs in `flips` turned about their alternative centre."""
    if not flips:
        return sk
    import copy
    s2 = copy.copy(sk)
    s2.points = dict(sk.points)
    s2.arcs = list(sk.arcs)
    for n in flips:
        if n in sk.alt_centres:
            pid = 10_000_000 + n          # a point of its own (no record holds the true centre)
            s2.points[pid] = sk.alt_centres[n]
            a, c, _ctr = s2.arcs[n]
            s2.arcs[n] = (a, c, pid)
    return s2


_SEGMENT = re.compile(rb"\xff\xff\x1f\x00", re.S)


def _read_segments(b: bytes, sk: Sketch, s: int, e: int, partial: dict) -> None:
    """Construction lines, from the sketch's segment records: the same header as a point's but
    no coordinates; u32 curve id before `FF FF 1F 00`, then after `F0 3F` (2015+: and 8 zero
    bytes) the start and end point (point id - 1) and a flag, 0 for construction geometry.
    A construction line whose ends are points on no curve (a centre rectangle's diagonals) has
    no handles in its points, so it is only found here; one already read is marked.
    This numbering holds in some files only (over the samples about a fifth of the records
    match the lines read from point handles; older files number them otherwise), so a
    sketch's records are used only when at least half of its normal records, and at least two,
    give the ends of a line or arc already read."""
    segs = []
    for m in _SEGMENT.finditer(b, s, e):
        i = m.start()
        if i < s + 4:
            continue
        cid = struct.unpack_from("<I", b, i - 4)[0]
        if cid > 0xFFFF:   # (curve ids and point ids are numbered apart: a curve can share a point's id)
            continue
        j = b.find(b"\xf0\x3f", i, i + 80)
        if j < 0 or b"\x1e\x00" in (b[j + 2:j + 4], b[j + 10:j + 12]):
            continue      # a point record: its coordinates follow `1E 00`
        k = j + 2 + (8 if b[j + 2:j + 10] == bytes(8) else 0)   # (older files: start, end, flag can't all be 0)
        if k + 6 > len(b):
            continue
        a, c, flag = struct.unpack_from("<HHH", b, k)
        segs.append((cid, a + 1, c + 1, flag))
    pairs = {frozenset(ln) for ln in sk.lines} | {frozenset(ar[:2]) for ar in sk.arcs}
    normal = [frozenset((a, c)) for _cid, a, c, f in segs if f == 1]
    good = sum(1 for pr in normal if pr in pairs)
    if good < 2 or 2 * good < len(normal):
        return
    for cid, a, c, flag in segs:
        if a == c or a not in sk.points or c not in sk.points or math.dist(sk.points[a], sk.points[c]) < TOL:
            continue
        key = ("line", cid)
        if key in sk.curve_of:
            n = int(sk.curve_of[key][1:]) - 1
            if flag == 0 and sk.curve_of[key][0] == "l" and set(sk.lines[n]) == {a, c}:
                sk.construction.add(n)
            continue
        if cid in partial and set(partial[cid]) <= {a, c}:
            # a line read with one end only (its other end a point on no curve, e.g. the origin)
            sk.lines.append((a, c))
            sk.curve_of[key] = f"l{len(sk.lines)}"
            sk.problems = [pr for pr in sk.problems if pr != f"line {cid} has {len(partial[cid])} end points"]
            if flag == 0:
                sk.construction.add(len(sk.lines) - 1)
            continue
        if flag != 0 or any(set(ln) == {a, c} for ln in sk.lines):
            continue
        sk.lines.append((a, c))
        sk.construction.add(len(sk.lines) - 1)
        sk.curve_of[key] = f"l{len(sk.lines)}"


_DIM_CLASSES = ("sgPntPntDist", "sgPntPntHorDist", "sgPntPntVertDist", "sgCircleDim", "sgPntLineDist",
                "sgLLDist", "sgAnglDim", "sgSkOffsetDim")


def _read_dimensions(b: bytes, tags: dict, sk: Sketch, s: int, e: int) -> None:
    """The sketch's dimensions: each a record of a dimension class, its parameter (name, value)
    and handles naming the points or curves it measures. A dimension can be written twice (an
    earlier state, then the current one); the last record of each name wins."""
    starts = []
    for m in re.finditer(rb"\xff\xff\x01\x00(.)\x00", b[s:e], re.S):
        i = s + m.start()
        n = b[i + 4]
        name = b[i + 6:i + 6 + n].decode("latin1", "replace")
        if name in _DIM_CLASSES:
            starts.append((i, name, i + 6 + n))
    tag_of = {v: k for k, v in tags.items()}
    for cls in _DIM_CLASSES:
        t = tag_of.get(cls)
        if t is None or t > 0xFFFF:
            continue
        for m in re.finditer(re.escape(struct.pack("<H", t)) + rb"\x00\x00\x00\x00", b[s:e]):
            i = s + m.start()
            starts.append((i, cls, i + 2))
    starts.sort()
    found = {}
    for n, (i, cls, data) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else min(e, i + 600)
        j = b.find(b"\xff\xfe\xff", data, data + 40)
        if j < 0:
            continue
        nm = b[j + 4:j + 4 + 2 * b[j + 3]].decode("utf-16le", "replace")
        v = _param_value(b, j - 2)
        if v is None or not nm:
            continue
        handles = []
        k = j
        rel = _REL_HEAD.search(b, j, end)   # the relation list after the last dimension isn't its
        if rel:
            end = rel.start()
        while k < end - 12:
            if b[k + 1] == 0x80 and b[k + 4:k + 8] == b"\xff\xff\xff\xff" and b[k + 8:k + 12] == bytes(4):
                cname = tags.get(struct.unpack_from("<H", b, k)[0], "")
                handles.append((cname, struct.unpack_from("<H", b, k + 2)[0]))
                k += 12
            else:
                k += 1
        found[nm] = (cls, v, handles)
    sk.dims = [(nm, cls, v, h) for nm, (cls, v, h) in found.items()]


_REL_HEAD = re.compile(rb"([\x00-\xff])\x00\x00\x00\x02\x00\x00\x00(?:\x00\x00){1,2}\xfe\xff\x00\x00", re.S)
_HANDLE = re.compile(rb"([\x00-\xff][\x80-\xff])([\x00-\xff]{2})\xff\xff\xff\xff\x00\x00\x00\x00", re.S)


def _read_relations(b: bytes, tags: dict, sk: Sketch, s: int, e: int) -> None:
    """The sketch's relations: u32 type, u32 2, 4 zero bytes, `FE FF 00 00`, then handles to
    the entities related (`<class tag> <u16 id> FF FF FF FF 00 00 00 00`), in groups that end
    with an `FFFF FFFF` pair. Stored raw: (type, [[(kind, id), ...], ...]) with kind point /
    line / arc and the handle's own id."""
    heads = list(_REL_HEAD.finditer(b, s, e))
    for n, m in enumerate(heads):
        end = heads[n + 1].start() if n + 1 < len(heads) else min(e, m.end() + 200)
        groups, cur = [], []
        for h in _HANDLE.finditer(b, m.end(), min(end, m.end() + 200)):
            tag, hid = struct.unpack("<H", h.group(1))[0], struct.unpack("<H", h.group(2))[0]
            if tag == 0xFFFF:
                if cur:
                    groups.append(cur)
                cur = []
                continue
            cls = tags.get(tag, "")
            kind = {"sgPointHandle": "point", "sgLineHandle": "line", "sgArcHandle": "arc"}.get(cls, cls or "?")
            cur.append((kind, hid))
        if cur:
            groups.append(cur)
        sk.relations.append((m.group(1)[0], groups))


# KeyWords' feature types (SolidWorks localizes them) for classes a feature can be recovered as
_KW_TYPES = {"Fillet": FILLET, "Скругление": FILLET, "Congé": FILLET, "Verrundung": FILLET,
             "Filete": FILLET, "Redondeo": FILLET, "Raccordo": FILLET,
             "Chanfro": "Chamfer_c", "Chaflán": "Chamfer_c", "Smusso": "Chamfer_c",
             "Chamfer": "Chamfer_c", "Фаска": "Chamfer_c", "Chanfrein": "Chamfer_c", "Fase": "Chamfer_c"}


_BOSS_TYPES = {"Boss-Extrude", "Бобышка-Вытянуть", "Boss.-Extru.", "Ressalto-extrusão", "Saliente-Extruir",
               "Aufsatz-Extrusion", "Estrusione base"}
_CUT_TYPES = {"Cut-Extrude", "Enlèv. mat.-Extru.", "Вырез-Вытянуть", "Corte-extrusão", "Cortar-Extruir",
              "Schnitt-Extrusion", "Taglio estruso"}


def _kw_features(kw: str) -> list:
    """KeyWords' features: (element, name, type or None), in its order. Features are listed as
    `<Feature>`, extrudes as `<Extrusion>`, Hole Wizard holes as `<HoleWizard>`, some cuts as
    `<Cut>`."""
    out = []
    for e, rest in re.findall(r'<(Feature|Extrusion|HoleWizard|Cut|Sketch) ([^>]*)>', kw):
        n = re.search(r'Name="([^"]+)"', rest)
        t = re.search(r'Type="([^"]+)"', rest)
        if not n:
            continue
        name = html.unescape(n.group(1))
        # a sketch: the user's (Dissectable), not the origin KeyWords lists among them
        if e == "Sketch" and ('Dissectable="true"' not in rest or name in _ORIGIN_NAMES):
            continue
        out.append((e, name, html.unescape(t.group(1)) if t else None))
    return out


_ORIGIN_NAMES = {"Origin", "Origine", "Ursprung", "Origen", "Исходная точка"}


def _recover(b: bytes, named: list, kw: str) -> list:
    """Features KeyWords lists that the record numbering missed (where it drifts, a feature's
    class tag isn't recognised), found by their name: `<class tag> <node tag> FF FE FF` length,
    UTF-16 name. Their class: an extrude's by its KeyWords type (boss or cut), a Hole Wizard
    hole's by its element; others by their KeyWords type as the features found in this file
    have it, or a table of the types seen; failing those, the class of a feature found with
    the same class tag. An extrude KeyWords types as a boss or a cut is that, whatever its tag
    said. Returned with the rest, in stream order."""
    listed = _kw_features(kw)
    by_name = {n: (e, t) for e, n, t in listed}
    # correct boss / cut where KeyWords says which
    fixed = []
    for k, r, nm in named:
        e_t = by_name.get(nm)
        if e_t and e_t[0] in ("Extrusion", "Cut") and r.cls not in ("moCut_c",):
            want = BOSS if e_t[1] in _BOSS_TYPES else CUT if e_t[1] in _CUT_TYPES else r.cls
            if want not in (BOSS, CUT):   # a drifted tag read it as something else (a fillet …)
                want = CUT if e_t[0] == "Cut" or re.search(r"cut|вырез|enl|corte|cortar|schnitt|taglio|řez", nm, re.I) else \
                    BOSS if re.search(r"boss|бобышка|ressalto|saliente|aufsatz|estrusione|bossage|výstupek", nm, re.I) else want
            if want != r.cls:
                r = archive.Record(r.offset, r.number, want, r.new_class)
        fixed.append((k, r, nm))
    named = fixed
    found = {nm for _k, _r, nm in named}
    learned = {by_name[nm][1]: r.cls for _k, r, nm in named if nm in by_name and by_name[nm][1]}
    tag_cls = {}
    for _k, r, _nm in named:
        if not r.new_class and r.offset + 2 <= len(b):
            tag_cls.setdefault(struct.unpack_from("<H", b, r.offset)[0], r.cls)
    taken = {r.offset for _k, r, _nm in named}
    extra = []
    for e, nm, t in listed:
        if nm in found or len(nm) > 255:
            continue
        if e == "HoleWizard":
            cls = HOLE
        elif e == "Sketch":
            cls = SKETCH
        elif e == "Extrusion" and t in _BOSS_TYPES:
            cls = BOSS
        elif e == "Extrusion" and t in _CUT_TYPES:
            cls = CUT
        else:
            cls = (learned.get(t) or _KW_TYPES.get(t)) if t else None
        needle = b"\xff\xfe\xff" + bytes([len(nm)]) + nm.encode("utf-16le")
        i = b.find(needle)
        while i >= 4:
            if b[i - 1] & 0x80 and b[i - 3] & 0x80 and i - 4 not in taken:
                c = cls or tag_cls.get(struct.unpack_from("<H", b, i - 4)[0])
                if e in ("Extrusion", "Cut") and c not in (BOSS, CUT, "moCut_c"):
                    # an extrude is a boss or a cut, whatever a drifted tag says
                    c = CUT if e == "Cut" or re.search(r"cut|вырез|enl|corte|cortar|schnitt|taglio|řez", nm, re.I) else BOSS if re.search(r"boss|бобышка|ressalto|saliente|aufsatz|estrusione|bossage|výstupek", nm, re.I) else None
                if c and is_feature_class(c):
                    extra.append((None, archive.Record(i - 4, -1, c, False), nm))
                break
            i = b.find(needle, i + 1)
    return sorted(named + extra, key=lambda x: x[1].offset)


def _fid(b: bytes, r: archive.Record) -> int:
    """A feature's id: the u16 8 bytes after its name (7 zero bytes and a flag byte between)."""
    i = b.find(b"\xff\xfe\xff", r.offset, r.offset + 40)
    if i < 0:
        return 0
    j = i + 4 + 2 * b[i + 3]
    return struct.unpack_from("<H", b, j + 8)[0]


_FACE_REF = re.compile(rb"([\x00-\xff][\x80-\xff])\x00\x00([\x00-\xff][\x80-\xff])[\x00-\xff]{2}"
                       rb"([\x00-\xff]{4})[\x00-\xff]{4}([\x00-\xff]{4})([\x00-\xff]{4})", re.S)
_RESULT = ("moCompEdge_c", "edgeRadiusObject_c", "moCompFace_c")


def _edge_refs(b: bytes, recs: list, k: int | None, end: int, fids: set, own: int, s0: int | None = None) -> list:
    """The edges a fillet rounds. Each edge is named by four face references: the two faces
    that meet there, then the two at its ends. A face reference: class tag, 2 zero bytes, a
    feature reference (tag, 2 bytes, u32 feature id, u32 save stamp), then for a face made from
    a sketch entity the entity's number, for an end face 0 (start) or 1 (end) and one more u32.

    How many: the fillet first lists its own faces, numbered 1…N, one per edge it rounds, so
    the selection is the first 4N references to other features. (Where that list isn't found,
    the selection is the run of face-reference records after the feature.) `s0`: where the
    feature starts, for a feature found by name rather than by its record (`k` None)."""
    s0 = recs[k].offset if s0 is None else s0
    raw, own_faces, i = [], [], s0
    while True:
        m = _FACE_REF.search(b, i, end)
        if not m:
            break
        fd = struct.unpack("<I", m.group(3))[0]
        if fd not in fids:
            i = m.start() + 1
            continue
        v, nxt = struct.unpack("<I", m.group(4))[0], struct.unpack("<I", m.group(5))[0]
        if fd == own:
            if not raw:
                own_faces.append(v)
        else:
            raw.append((struct.unpack("<H", m.group(1))[0], fd, v, nxt, m.start()))
        i = m.start() + 20
    # its own faces: `<tag> <2 bytes> <tag> <2 bytes> <u32 own id> <u32 stamp> <u32 1, 2, 3 …>`
    # (read at every occurrence of its id, not by matching the whole reference: the list's header
    # overlaps its first entry)
    first = raw[0][4] if raw else end
    key, own_faces, j = struct.pack("<I", own), [], s0
    while True:
        j = b.find(key, j, first)
        if j < 0 or j + 12 > len(b):
            break
        if j >= 4 and b[j - 3] & 0x80:      # a feature reference: its tag sits 4 bytes before
            own_faces.append(struct.unpack_from("<I", b, j + 8)[0])
        j += 1
    n_faces = 0
    if 1 in own_faces:                      # (the list's own header comes first)
        own_faces = own_faces[own_faces.index(1):]
    for n, v in enumerate(own_faces, 1):   # the running numbers 1, 2, 3 … of its own faces
        if v != n:
            break
        n_faces = n
    if n_faces and len(raw) >= 4 * n_faces:
        refs = raw[:4 * n_faces]
    elif k is not None:
        # the run of face-reference records after the feature; the first other record ends it
        stop, started = end, False
        for x in recs[k + 1:]:
            if x.offset >= end:
                break
            ref_rec = x.cls.endswith("IdRep_c") or x.cls in ("moFR_c", "moEdgeRef_c")
            if x.cls in _RESULT or (started and not ref_rec):
                stop = x.offset
                break
            started = started or ref_rec
        refs = [r for r in raw if r[4] < stop]
    else:
        return []
    if not refs or len(refs) % 4:
        return []
    # which class tag is the end face: by name where this stream defines the class, else the tag
    # whose references are all 0 or 1 (a sketch entity's number runs higher)
    tags = _class_tags(recs)
    named = {t for t, *_r in refs if tags.get(t) == "moEndFaceSurfIdRep_c"}
    if not named:
        small = {t for t, *_r in refs} - {t for t, _fd, v, _n, _o in refs if v > 1}
        named = small if len(small) == 1 else {t for t, _fd, v, nxt, _o in refs if v in (0, 1) and nxt < 16}
    faces = [("end" if t in named else "side", fd, v) for t, fd, v, _n, _o in refs]
    return [(faces[n], faces[n + 1], faces[n + 2], faces[n + 3]) for n in range(0, len(faces), 4)]


def _param_value(b: bytes, s: int) -> float | None:
    """The value of a dimension's parameter record starting at s: its name (`FF FE FF`, u8
    length, UTF-16, e.g. "D1"), 8 flag bytes, `FF FF FF FF` and 4 zero bytes, then (2015+) an
    empty text field, then 2 zero bytes and the value as a double, in metres or radians."""
    i = b.find(b"\xff\xfe\xff", s, s + 16)
    if i < 0:
        return None
    i += 4 + 2 * b[i + 3] + 8
    if b[i:i + 4] != b"\xff\xff\xff\xff":
        return None
    i += 8
    if b[i:i + 3] == b"\xff\xfe\xff":
        i += 4 + 2 * b[i + 3]
    if b[i:i + 2] != b"\x00\x00":
        return None
    return struct.unpack_from("<d", b, i + 2)[0]


# the length units KeyWords can show a document's sizes in, as mm: mm, inch, cm, m, foot
_UNITS = (1.0, 25.4, 10.0, 1000.0, 304.8)


def _kw_length(text: str, b: bytes, lo: int, hi: int, unit: list) -> float | None:
    """A KeyWords length in mm. KeyWords shows it in the document's units, rounded as it displays
    it; the feature's record (`b[lo:hi]`) keeps it exact in metres. For each unit (the one found
    earlier in this file first), the record's doubles that round to the shown value are found;
    the commonest is the value, and its unit is kept in `unit[0]`. Where none matches, the value
    as shown, in the unit found earlier (mm if none)."""
    m = re.search(r"-?\d+(?:\.(\d+))?", html.unescape(text or ""))
    if not m:
        return None
    v, dec = float(m.group()), len(m.group(1) or "")
    # once the unit is known only it; before, the two common ones (a wider unit's window would
    # take unrelated doubles)
    order = [unit[0]] if unit[0] else list(_UNITS[:2])
    for u in order:
        want, half = v * u, 0.5 * 10 ** -dec * u + 1e-9
        found: dict = {}
        for i in range(lo, max(lo, hi - 8)):
            d = struct.unpack_from("<d", b, i)[0] * 1000
            if d == d and abs(d - want) <= half and d > 0:
                found[d] = found.get(d, 0) + 1
        if found:
            unit[0] = u
            return max(found, key=lambda d: (found[d], -abs(d - want)))
    return v * (unit[0] or 1.0)


def _sketch_unit(kw: str, sk: "Sketch") -> float | None:
    """The unit KeyWords shows lengths in (as mm), from a sketch's dimensions: KeyWords' value of
    a length dimension against the sketch's own (exact, in metres)."""
    m = re.search(r'<Sketch [^>]*Name="%s"[^>/]*>(.*?)</Sketch>' % re.escape(html.escape(sk.name)), kw, re.S)
    if not m:
        return None
    shown = dict(re.findall(r'<Dimension Name="(D\d+)">([^<]*)</Dimension>', m.group(1)))
    for name, _cls, val, _h in sk.dims:
        t = html.unescape(shown.get(name, ""))
        x = re.search(r"-?\d+(?:\.(\d+))?", t)
        if not x or "°" in t or not val or float(x.group()) == 0:
            continue
        v, dec = float(x.group()), len(x.group(1) or "")
        for u in _UNITS:
            if abs(abs(val) * 1000 - abs(v) * u) <= 0.5 * 10 ** -dec * u + 1e-9 and abs(v) * u > 10 ** -dec * u:
                return u
    return None


def _depth(b: bytes, recs: list, k: int, end: int) -> float | None:
    """An extrude's depth: the value of its first length parameter, or else of its first distance
    dimension (`ParallelPlaneDistanceDim_c`)."""
    inside = [r for r in recs[k + 1:] if r.offset < end]
    for cls in ("moLengthParameter_c", "ParallelPlaneDistanceDim_c"):
        for r in inside:
            if r.cls == cls:
                v = _param_value(b, _data_start(b, r))
                if v is not None and 1e-7 < abs(v) < 100:
                    return v
                break
    return None


# --- the tree ---------------------------------------------------------------------------------
def read(sw) -> list[Feature] | None:
    """The part's features in order, or None when the stream can't be numbered yet (files saved
    before 2015 carry on the numbering from another section; not settled)."""
    b = sw.streams.get(STREAM)
    if not b:
        return None
    start = archive.start_number(b)
    old_file = start is None
    outside = None
    if start is None:
        # files saved before 2015 carry on Contents/Config-0's numbering
        main = sw.streams.get(STREAM.replace("-ResolvedFeatures", ""))
        if main:
            outside = set(archive.class_numbers(archive.records(main, 0)).values())
        start = archive.old_start_number(b, outside)
        if start is None:
            return None
    recs = archive.records(b, start, outside, resync=True)
    # each sketch's current dimensions by name, from KeyWords (a stale record isn't listed)
    kw = sw.xml("swXmlContents/KeyWords") or ""
    kw_dims = {html.unescape(m.group(1)): set(re.findall(r'<Dimension Name="([^"]+)"', m.group(2)))
               for m in re.finditer(r'<Sketch id="\d+" Name="([^"]*)"[^>/]*>(.*?)</Sketch>', kw, re.S)}
    kw_sketches = {html.unescape(m.group(1)) for m in re.finditer(r'<Sketch id="\d+" Name="([^"]*)"', kw)}
    tags = _class_tags(recs)
    by_id, by_off = _plane_frames(b, recs)
    named = []
    origin_seen = False
    for k, r in enumerate(recs):
        if r.cls == "moOriginProfileFeature_c":
            origin_seen = True   # the three standard planes come before it; planes after it are features
        if not is_feature_class(r.cls) or (r.cls == "moRefPlane_c" and not origin_seen):
            continue
        nm = _name(b, r)
        if nm:
            named.append((k, r, nm))
    named = _recover(b, named, kw)
    learned: dict = {}   # handle tags the numbering doesn't give, learned sketch by sketch
    local = None         # the local bodies (an import's own), read when an import needs them
    out: list[Feature] = []
    last_sketch = None
    unit: list = [None]  # the unit KeyWords shows lengths in (as mm), once a value has shown it
    fids = {_fid(b, r) for _k, r, _nm in named}
    rec_offsets = [x.offset for x in recs]
    for n, (k, r, nm) in enumerate(named):
        end = named[n + 1][1].offset if n + 1 < len(named) else len(b)
        if k is None and r.cls not in (FILLET, CHAMFER):
            # found by name (KeyWords), not by its record: the records nearby stand in for it
            import bisect
            k = max(0, bisect.bisect_right(rec_offsets, r.offset) - 1)
        if r.cls == SKETCH:
            sk = Sketch(nm, r.offset, end)
            _read_sketch(b, tags, sk, r.offset, end, learned)
            if nm in kw_sketches:
                keep = kw_dims.get(nm, set())
                sk.dims = [d for d in sk.dims if d[0] in keep]
            pl, how = _sketch_plane(b, recs, k, by_id, by_off)
            if pl:
                sk.add_plane(pl, how)
            else:
                prev = named[n - 1][1].offset if n else 0
                refs = _plane_refs(b, recs, prev, r.offset)
                if refs:
                    pl, how = _plane_from_ref(b, recs, refs[-1], by_id, by_off)
                    if pl:
                        sk.add_plane(pl, "plane reference before it: " + how)
                        # some files write a sketch's plane reference after it, among its own
                        # records (the one before is then another's): tried too
                        pl2, how2 = _plane_inside(b, recs, r.offset, end, by_id, by_off)
                        for one in (pl2 if isinstance(pl2, list) else [pl2] if pl2 else []):
                            sk.add_plane(one, "plane reference after it: " + how2)
            if not sk.planes:
                pl, how = _plane_inside(b, recs, r.offset, end, by_id, by_off)
                for one in (pl if isinstance(pl, list) else [pl] if pl else []):
                    sk.add_plane(one, how)
            f = Feature("sketch", nm, r.offset, r.cls, sketch=sk)
            last_sketch = f
            if not unit[0]:
                unit[0] = _sketch_unit(kw, sk)
        elif r.cls in ("moBossThin_c", "moCutThin_c", "moExtruThin_c"):
            # a thin extrude: KeyWords' D1 its depth, D5 its wall's thickness
            f = Feature("cut" if r.cls == "moCutThin_c" else "boss", nm, r.offset, r.cls,
                        profile=last_sketch.name if last_sketch else None)
            m = re.search(r'<(\w+) [^>]*Name="%s"[^>]*>(.*?)</\1>' % re.escape(html.escape(nm)), kw, re.S)
            dims = dict(re.findall(r'<Dimension Name="(D\d+)">([^<]*)</Dimension>', m.group(2))) if m else {}
            f.depth_mm = _kw_length(dims.get("D1"), b, r.offset, end, unit)
            f.thin_mm = _kw_length(dims.get("D5"), b, r.offset, end, unit)
            if not f.depth_mm or not f.thin_mm:
                f.kind, f.reason = "tbd", "thin extrude's depth or thickness not read"
        elif r.cls in (BOSS, CUT, "moCut_c"):   # moCut_c: KeyWords lists it as <Cut>
            f = Feature("boss" if r.cls == BOSS else "cut", nm, r.offset, r.cls,
                        depth_mm=None, profile=last_sketch.name if last_sketch else None)
            # where the stream's numbering drifts, a boss can read as a cut: a default name that
            # says the other kind is tried too (names can be changed, so it doesn't decide)
            if f.kind == "cut" and re.match(r"(Boss|Бобышка)", nm):
                f.alt_kind = "boss"
            elif f.kind == "boss" and re.match(r"(Cut|Вырез|Enl)", nm):
                f.alt_kind = "cut"

            dep = _depth(b, recs, k, end)
            if dep is None:
                m = re.search(r'<Extrusion [^>]*Name="%s"[^>/]*>(.*?)</Extrusion>' % re.escape(html.escape(nm)), kw, re.S)
                d1 = re.search(r'<Dimension Name="D1">([^<]*)</Dimension>', m.group(1)) if m else None
                mm = _kw_length(d1.group(1), b, r.offset, end, unit) if d1 else None
                dep = mm / 1000 if mm else None
            if dep is None:
                # no distance in the file: an end condition such as through all or up to a face.
                # Through all is tried; the rebuild check rejects it when it's something else.
                f.through_all = True
            else:
                f.depth_mm = dep * 1000
            # a thin extrude kept under the plain class (older files): KeyWords gives its wall as D5
            m = re.search(r'<Extrusion ([^>]*Name="%s"[^>/]*)>(.*?)</Extrusion>' % re.escape(html.escape(nm)), kw, re.S)
            d5 = re.search(r'<Dimension Name="D5">([^<]*)</Dimension>', m.group(2)) if m else None
            if d5 and ("Thin" in nm or "Thin" in m.group(1)):
                f.thin_mm = _kw_length(d5.group(1), b, r.offset, end, unit)
        elif r.cls in (REVOLVE, REVCUT):
            f = Feature("revolve" if r.cls == REVOLVE else "revcut", nm, r.offset, r.cls,
                        profile=last_sketch.name if last_sketch else None)
            ang = None
            for x in recs[k + 1:]:
                if x.offset >= end:
                    break
                if x.cls == "moAngleParameter_c":
                    ang = _param_value(b, _data_start(b, x))
                    break
            f.angle_deg = math.degrees(ang) if ang and 1e-6 < abs(ang) <= 2 * math.pi + 1e-9 else 360.0
        elif r.cls in (FILLET, CHAMFER):
            f = Feature("fillet" if r.cls == FILLET else "chamfer", nm, r.offset, r.cls)
            rad = None
            for x in (recs[k + 1:] if k is not None else []):
                if x.offset >= end:
                    break
                if x.cls == "moLengthParameter_c":
                    rad = _param_value(b, _data_start(b, x))
                    break
            if rad is None:      # found by name: its radius is its parameter D1
                j = b.find(b"\xff\xfe\xff\x02D\x001\x00", r.offset, end)
                rad = _param_value(b, j) if j >= 0 else None
            groups = _edge_refs(b, recs, k, end, fids, _fid(b, r), r.offset)
            f.edges = [g[:2] for g in groups]
            f.edge_ends = [g[2:] for g in groups]
            if f.kind == "chamfer":
                # a chamfer: D1 its distance; D2 its angle (an angle parameter, radians) or a
                # second distance
                j = b.find(b"\xff\xfe\xff\x02D\x001\x00", r.offset, end)
                rad = _param_value(b, j) if j >= 0 else None
                j2 = b.find(b"\xff\xfe\xff\x02D\x002\x00", r.offset, end)
                d2 = _param_value(b, j2) if j2 >= 0 else None
                owner = [x for x in recs if x.offset <= j2][-1:] if j2 >= 0 and recs else []
                if d2 is not None and ((owner and owner[0].cls == "moAngleParameter_c") or 0.1 < d2 < math.pi):
                    f.chamfer_deg = round(math.degrees(d2), 6)
                elif d2 is not None and 1e-7 < d2 < 10:
                    f.chamfer_mm2 = d2 * 1000
                else:
                    f.chamfer_deg = 45.0
            if rad and 1e-7 < rad < 10 and f.edges:
                f.radius_mm = rad * 1000
            else:
                f.kind, f.reason = "tbd", f"{f.kind}'s size or edges not read"
        elif r.cls == HOLE:
            # its placement sketch and profile sketch follow it; its sizes are named parameters
            # after them ("Hole Dia.", "C'Sink Angle" …)
            f = Feature("hole", nm, r.offset, r.cls)
            stop = next((x[1].offset for x in named[n + 1:] if x[1].cls != SKETCH), len(b))
            f.hole = _hole_params(b, r.offset, stop)
            if "diameter" not in f.hole:
                f.kind, f.reason = "tbd", "hole's size not read"
        elif r.cls == "moShell_c":
            # a shell: KeyWords' D1 its thickness; the face it opens named like a mirror's
            f = Feature("shell", nm, r.offset, r.cls)
            m = re.search(r'<Feature [^>]*Name="%s"[^>]*>(.*?)</Feature>' % re.escape(html.escape(nm)), kw, re.S)
            d1 = re.search(r'<Dimension Name="D1">([^<]*)</Dimension>', m.group(1)) if m else None
            f.thin_mm = _kw_length(d1.group(1), b, r.offset, end, unit) if d1 else None
            for mm in _FACE_REF.finditer(b, r.offset, min(end, r.offset + 2000)):
                fd = struct.unpack("<I", mm.group(3))[0]
                if fd in fids and fd != _fid(b, r):
                    v, nxt = struct.unpack("<I", mm.group(4))[0], struct.unpack("<I", mm.group(5))[0]
                    f.mirror_face = ("end" if v in (0, 1) and (nxt < 16 or nxt == 100000) else "side", fd, v)
                    break
            if not f.thin_mm:
                f.kind, f.reason = "tbd", "shell's thickness not read"
        elif r.cls in ("moCosmeticThread_c", "moRefAxis_c", "moRefPoint_c", "moSensor_c", "moHelix_c", "moRefCurve_c",
                       "moSketchBitmap_c", "moExtObject_c"):
            # no solid: a cosmetic thread is an annotation, an axis or point reference geometry.
            # Kept in the tree (TBD), not written, and doesn't stop the part rebuilding
            f = Feature("absorbed", nm, r.offset, r.cls,
                        reason=f"{r.cls}: reference geometry or annotation, no solid; not converted yet")
        elif r.cls == "moCombineBodies_c":
            # the converter joins each boss into the body as it goes, so a combine that adds the
            # bodies is already done; KeyWords doesn't say which kind it is, and the rebuild's
            # comparison with the part's own solid is what shows a subtracting one
            f = Feature("absorbed", nm, r.offset, r.cls,
                        reason="combine of bodies: the converter joins bodies as it goes")
        elif r.cls in ("moSweep_c", "moSweepCut_c"):
            # a sweep: a profile and a path, the two sketches before it (the profile the one with
            # a closed loop; the search tries them the other way round too)
            f = Feature("sweep" if r.cls == "moSweep_c" else "sweepcut", nm, r.offset, r.cls)
            two = [x for x in out if x.kind == "sketch"][-2:]
            if len(two) == 2:
                a, c = two
                closed = lambda x: bool(profile_loops(x.sketch))  # noqa: E731
                prof, path = (a, c) if closed(a) and not closed(c) else (c, a)
                f.profile, f.path = prof.name, path.name
                prof.sketch.used = path.sketch.used = True
            else:
                f.kind, f.reason = "tbd", "sweep's profile and path not found"
        elif r.cls == "moScale_c":
            # a scale: its factors are the first three doubles in its record that are all sizes
            # (KeyWords lists no dimension for it); what it scales about is chosen in the rebuild
            f = Feature("scale", nm, r.offset, r.cls)
            f.scale = _scale_factors(b, r.offset, end)
            if not f.scale:
                f.kind, f.reason = "tbd", "scale's factors not read"
        elif r.cls == "moDome_c":
            # a dome: its height is KeyWords' D1 for it; the face it sits on is chosen in the rebuild
            f = Feature("dome", nm, r.offset, r.cls)
            m = re.search(r'<Feature [^>]*Name="%s"[^>]*>(.*?)</Feature>' % re.escape(html.escape(nm)), kw, re.S)
            d1 = re.search(r'<Dimension Name="D1">([^<]*)</Dimension>', m.group(1)) if m else None
            mm = _kw_length(d1.group(1), b, r.offset, end, unit) if d1 else None
            if mm:
                f.dome_mm = mm
            else:
                f.kind, f.reason = "tbd", "dome's height not read"
        elif r.cls in PATTERNS:
            # its counts and spacings are KeyWords' dimensions for it: a number alone is a count,
            # a length a spacing, an angle (circular) the angle; in the order D1 count, D3
            # spacing / angle, D2 the second count, D4 the second spacing
            f = Feature("pattern", nm, r.offset, r.cls)
            m = re.search(r'<Feature [^>]*Name="%s"[^>]*>(.*?)</Feature>' % re.escape(html.escape(nm)), kw, re.S)
            dims = dict(re.findall(r'<Dimension Name="(D\d+)">([^<]*)</Dimension>', m.group(1))) if m else {}
            val = lambda k: (lambda x: float(x.group()) if x else None)(re.search(r"-?\d+(?:\.\d+)?", html.unescape(dims.get(k, ""))))  # noqa: E731
            kind = PATTERNS[r.cls]
            angle = next((val(k) for k, v in dims.items() if "°" in html.unescape(v)), None)
            f.pattern = {"kind": kind, "count1": val("D1")}
            if kind == "circular":
                f.pattern["angle"] = angle
            else:
                f.pattern.update(spacing1=_kw_length(dims.get("D3"), b, r.offset, end, unit), count2=val("D2"),
                                 spacing2=_kw_length(dims.get("D4"), b, r.offset, end, unit))
            if not f.pattern["count1"] or (kind == "circular" and not angle) or (kind == "linear" and not f.pattern["spacing1"]):
                f.kind, f.reason = "tbd", "pattern's counts not read"
        elif r.cls == THREAD:
            # a modelled thread: its sizes are KeyWords' dimensions for it (`<MOD-DIAM>4` the
            # diameter; of the other lengths the smaller is the pitch, the larger the length)
            f = Feature("thread", nm, r.offset, r.cls)
            m = re.search(r'<Feature [^>]*Name="%s"[^>]*>(.*?)</Feature>' % re.escape(html.escape(nm)), kw, re.S)
            dims = re.findall(r'<Dimension Name="D\d+">([^<]*)</Dimension>', m.group(1)) if m else []
            lengths = []
            for v in dims:
                v = html.unescape(v)
                num = re.search(r"-?\d+(?:\.\d+)?", v)
                if not num or "°" in v:
                    continue
                if "MOD-DIAM" in v:
                    f.thread["diameter"] = _kw_length(v.replace("<MOD-DIAM>", ""), b, r.offset, end, unit)
                else:
                    lengths.append(_kw_length(v, b, r.offset, end, unit))
            if len(lengths) >= 2 and "diameter" in f.thread:
                f.thread["pitch"], f.thread["length"] = min(lengths), max(lengths)
            elif len(lengths) == 1 and "diameter" in f.thread:
                f.thread["pitch"] = lengths[0]       # no length: the thread runs the face's length
            else:
                f.kind, f.reason = "tbd", "thread's sizes not read"
        elif r.cls in MIRRORS:
            # the face or plane it mirrors about: the first face reference in its record (a
            # face named by the sketch entity or end face that made it), and any plane reference
            f = Feature("mirror", nm, r.offset, r.cls)
            for m in _FACE_REF.finditer(b, r.offset, min(end, r.offset + 2000)):
                fd = struct.unpack("<I", m.group(3))[0]
                if fd in fids and fd != _fid(b, r):
                    v, nxt = struct.unpack("<I", m.group(4))[0], struct.unpack("<I", m.group(5))[0]
                    f.mirror_face = ("end" if v in (0, 1) and (nxt < 16 or nxt == 100000) else "side", fd, v)
                    break
            for ref in _plane_refs(b, recs, r.offset, end):
                pl, _how = _plane_from_ref(b, recs, ref, by_id, by_off)
                for one in (pl if isinstance(pl, list) else [pl] if pl else []):
                    f.mirror_planes.append(one)
        elif r.cls in IMPORTED:
            # SolidWorks has no history for it either: it converts as SolidCraft's import of the
            # body, as it was imported (kept under the feature's name among the local bodies)
            f = Feature("import", nm, r.offset, r.cls)
            if local is None:
                from . import geometry
                local = geometry.local_bodies(sw)
            f.import_body = local.get(nm)
        elif r.cls == "moRefPlane_c":
            # a plane the user added: written at the place it ends up (its definition, offset or
            # angle from other geometry, is not decoded yet)
            f = Feature("plane", nm, r.offset, r.cls)
            f.frame = by_off.get(r.offset)
            if f.frame is None:
                f.kind, f.reason = "tbd", "plane's placement not read"
        else:
            f = Feature("tbd", nm, r.offset, r.cls, reason=f"{r.cls} not converted yet")
        if r.cls != SKETCH and last_sketch and not last_sketch.sketch.used:
            # every feature is preceded by the plane of the sketch it uses (in files before 2015
            # this is the sketch's real plane; the one before the sketch says Front regardless)
            last_sketch.sketch.used = True
            prev = named[n - 1][1].offset if n else 0
            refs = _plane_refs(b, recs, prev, r.offset)
            if refs:
                pl, how = _plane_from_ref(b, recs, refs[-1], by_id, by_off)
                if pl:
                    last_sketch.sketch.add_plane(pl, "plane of the feature using it: " + how,
                                                 first=old_file)
        f.fid = _fid(b, r)
        out.append(f)
    return _place_holes(out)


def _scale_factors(b: bytes, s: int, e: int) -> tuple | None:
    """A scale's x, y and z factors: the first three doubles in a row, each a size (between a
    thousandth and a thousand), after its name (a casting pattern's shrinkage scale: 1.06 three
    times)."""
    i = b.find(b"\xff\xfe\xff", s, s + 40)
    start = i + 4 + 2 * b[i + 3] if i >= 0 else s
    for k in range(start, min(e, len(b)) - 24):
        v = struct.unpack_from("<3d", b, k)
        if all(1e-3 < x < 1e3 for x in v):
            return v
    return None


def _hole_params(b: bytes, s: int, e: int) -> dict:
    """A Hole Wizard hole's sizes: its named parameters (`FF FE FF` length, UTF-16 name, then
    the parameter's value as for D1), lengths in mm, angles in degrees."""
    out = {}
    for m in re.finditer(rb"\xff\xfe\xff([\x04-\x30])", b[s:e]):
        j = s + m.start()
        name = b[j + 4:j + 4 + 2 * m.group(1)[0]].decode("utf-16le", "replace")
        key = _HOLE_PARAMS.get(name)
        if not key or key in out:
            continue
        v = _param_value(b, j)
        if v is None or not 0 < v < 10:
            continue
        out[key] = round(math.degrees(v), 6) if key.endswith("angle") else round(v * 1000, 9)
    return out


def _place_holes(feats: list) -> list:
    """A hole's placement sketch (its points) comes after it in the file; SolidCraft's hole
    drills at a sketch's points, so the sketch goes first. The sketch after that is the
    hole's profile, which SolidCraft's hole makes itself: kept in the tree, not written."""
    out = list(feats)
    for f in [x for x in out if x.kind == "hole"]:
        i = out.index(f)
        after = out[i + 1:i + 3]
        if not after or after[0].kind != "sketch" or not after[0].sketch.points:
            f.kind, f.reason = "tbd", "hole's placement sketch not found"
            continue
        place = after[0]
        out.remove(place)
        out.insert(i, place)
        f.profile = place.name
        if len(after) > 1 and after[1].kind == "sketch":
            after[1].kind, after[1].reason = "absorbed", ""
    # a frame read as a rotation from a plane reference: its transpose too, as a later candidate
    # (spring_base_tab: the Right plane comes out mirrored as read and right as transposed;
    # symmetric sketches can't tell them apart, so the rebuild check chooses)
    for f in out:
        if f.kind != "sketch":
            continue
        for (x, y, n), t, how in list(f.sketch.planes):
            if "rotation" in how:
                rows = (tuple(x), tuple(y), tuple(n))
                tr = tuple(tuple(rows[j][i] for j in range(3)) for i in range(3))
                f.sketch.add_plane(((tr[0], tr[1], tr[2]), t), how + " (transposed)")
    # a sketch a second feature uses: SolidWorks records an empty copy, `Sketch3<3>`, for it; the
    # feature uses the sketch itself (Flywheel: a boss and a cut from one sketch)
    names = {f.name: f for f in out if f.kind == "sketch"}
    for f in out:
        m = re.fullmatch(r"(.+)<\d+>", f.name)
        if f.kind == "sketch" and m and m.group(1) in names and not f.sketch.points:
            for g in out:
                if g.profile == f.name:
                    g.profile = m.group(1)
            f.kind, f.reason = "absorbed", f"the same sketch as {m.group(1)}, for a second feature"
    # an extrude or revolve whose sketch wasn't found (none before it, or not a sketch read) can't
    # be built
    sketches = {f.name for f in out if f.kind == "sketch"}
    for f in out:
        if f.kind in ("boss", "cut", "revolve", "revcut") and f.profile not in sketches:
            f.kind, f.reason = "tbd", "the sketch it uses wasn't found"
    # one whose sketch has no curves read (an older layout) has nothing to build from
    empty = {f.name for f in out if f.kind == "sketch" and not (f.sketch.lines or f.sketch.arcs or f.sketch.circles)}
    for f in out:
        if f.kind in ("boss", "cut", "revolve", "revcut") and f.profile in empty:
            f.kind, f.reason = "tbd", "its sketch's curves weren't read"
    # a sketch no feature uses (SolidWorks allows them) whose plane isn't read doesn't touch the
    # solid: it stays in the tree as TBD, and isn't written
    used = {f.profile for f in out if f.profile}
    for f in out:
        if f.kind == "sketch" and f.name not in used and not f.sketch.planes:
            f.kind, f.reason = "absorbed", "sketch plane not read (no feature uses this sketch)"
    # a profile with points but none of its curves read (records the numbering doesn't name)
    # can't make the feature that uses it (a hole's placement sketch is points only)
    shaped = {f.profile for f in out if f.profile and f.kind != "hole"}
    for f in out:
        if f.kind == "sketch" and f.name in shaped and f.sketch.points and \
                not (f.sketch.lines or f.sketch.arcs or f.sketch.circles):
            f.kind, f.reason = "tbd", "sketch curves not read"
    return _after_what_it_rounds(out)


def _after_what_it_rounds(out: list) -> list:
    """Records come in the order features were made; a fillet or chamfer dragged up the tree
    afterwards keeps its place in them but names the faces of features after it (Bucket's first
    fillets). A feature can't round faces not made yet: it goes right after the latest feature
    its edges name."""
    for f in [x for x in out if x.kind in ("fillet", "chamfer") and x.edges]:
        pos = {x.fid: i for i, x in enumerate(out) if x.fid is not None and x.kind != "sketch"}
        here = out.index(f)
        named = {r[1] for e in list(f.edges) + list(f.edge_ends or []) for r in e}
        latest = max((pos[n] for n in named if n in pos and n != f.fid), default=-1)
        if latest > here:
            out.remove(f)
            out.insert(latest, f)        # (latest moved down one when f was taken out)
    return out


# --- SolidCraft features ------------------------------------------------------------------------
def sketch_feature(sk: Sketch, fid: int, constraints: bool = True) -> dict:
    """A SolidCraft sketch feature: the sketch on a custom plane (origin, x and y directions in
    model space, mm), its points and curves."""
    (x, y, _n), t = sk.plane
    pts = [{"fixed": True, "id": "origin", "pos": [0.0, 0.0]}]
    index = {}

    def pt(pid):
        if pid not in index:
            u, v = sk.points[pid]
            if pid == 1 and abs(u) < 1e-12 and abs(v) < 1e-12:
                index[pid] = 0          # SolidWorks' point 1 is the sketch origin: SolidCraft's fixed origin
                return 0
            index[pid] = len(pts)
            pts.append({"fixed": False, "id": f"p{pid}", "pos": [u * 1000, v * 1000]})
        return index[pid]

    curves = []
    for n, (a, c) in enumerate(sk.lines):
        curves.append({"a": pt(a), "b": pt(c), "construction": n in sk.construction, "id": f"l{n + 1}", "type": "line"})
    for n, (a, c, ctr) in enumerate(sk.arcs):
        # SolidCraft runs an arc anticlockwise from a to b; the file's handles don't say which end
        # is the start. Where a line meets the arc smoothly, the arc must carry on in the line's
        # direction (else the outline doubles back); otherwise take the shorter way round.
        a, c = _arc_ends(sk, a, c, ctr)
        curves.append({"a": pt(a), "b": pt(c), "c": pt(ctr), "construction": False, "id": f"a{n + 1}", "type": "arc"})
    for n, (ctr, r) in enumerate(sk.circles):
        curves.append({"c": pt(ctr), "construction": False, "id": f"c{n + 1}", "r": r * 1000, "type": "circle"})
    for pid in sorted(sk.points):   # the rest (virtual sharps, centres, points on no curve)
        pt(pid)
    plane = {"type": "custom", "plane": {"origin": [c * 1000 for c in t], "x_dir": list(x), "y_dir": list(y)}}
    cons, params = sketch_constraints(sk, index, curves) if constraints else ([], [])
    sk.params = params
    return {"id": fid, "name": sk.name, "plane": plane, "suppressed": False, "type": "sketch",
            "sketch": {"constraints": cons, "curves": curves, "points": pts,
                       "counters": {"a": len(sk.arcs), "c": len(sk.circles), "k": len(cons), "l": len(sk.lines)}}}


def param_name(sketch: str, dim: str) -> str:
    """A SolidCraft parameter name for SolidWorks' `D1@Sketch2`: `Sketch2_D1`."""
    return re.sub(r"\W", "_", f"{sketch}_{dim}")


def sketch_constraints(sk: Sketch, index: dict, curves: list) -> tuple[list, list]:
    """The sketch's dimensions as SolidCraft driving dimensions, each with a model parameter
    named after the SolidWorks one. A dimension whose stored value doesn't match a reading of its
    points or curve is left out (its meaning isn't decoded) and noted in sk.problems_soft."""
    P = sk.points
    cindex = {c["id"]: n for n, c in enumerate(curves)}
    cons, params = [], []
    sk.dims_skipped = []
    sk.offsets = []
    offset_done: set = set()
    origin = [pid for pid, (u, v) in P.items() if pid == 1 and abs(u) < 1e-12 and abs(v) < 1e-12]

    def pidx(pid):
        if pid in origin:
            return 0
        return index.get(pid)

    for nm, cls, val, handles in sk.dims:
        pts = [h + 1 for c, h in handles if c == "sgPointHandle"]  # a point handle's id is the point's id - 1
        crv = [(("line" if c == "sgLineHandle" else "arc"), h) for c, h in handles if c in ("sgLineHandle", "sgArcHandle")]
        mm = val * 1000
        con = None
        if cls in ("sgPntPntDist", "sgPntPntHorDist", "sgPntPntVertDist") and len(pts) == 2 and all(p in P for p in pts):
            (ax, ay), (bx, by) = P[pts[0]], P[pts[1]]
            pi, qi = pidx(pts[0]), pidx(pts[1])
            if pi is None or qi is None:
                pass
            elif cls != "sgPntPntVertDist" and abs(abs(bx - ax) - val) < 1e-9 and (cls == "sgPntPntHorDist" or abs(by - ay) > 1e-9):
                p, q = (pi, qi) if bx >= ax else (qi, pi)
                con = {"type": "distance_x", "p": p, "q": q}
            elif cls != "sgPntPntHorDist" and abs(abs(by - ay) - val) < 1e-9 and (cls == "sgPntPntVertDist" or abs(bx - ax) > 1e-9):
                p, q = (pi, qi) if by >= ay else (qi, pi)
                con = {"type": "distance_y", "p": p, "q": q}
            elif abs(math.hypot(bx - ax, by - ay) - val) < 1e-9:
                con = {"type": "distance", "p": pi, "q": qi}
        elif cls == "sgCircleDim" and len(crv) == 1 and crv[0] in sk.curve_of:
            cid = sk.curve_of[crv[0]]
            c = curves[cindex[cid]]
            r = c.get("r")
            if r is None:  # an arc: its radius from its points
                ctr = [k for k, v in index.items() if v == c["c"]]
                st = [k for k, v in index.items() if v == c["a"]]
                r = math.hypot(P[st[0]][0] - P[ctr[0]][0], P[st[0]][1] - P[ctr[0]][1]) * 1000 if ctr and st else None
            if r is not None and abs(r - mm) < 1e-6:
                con = {"type": "radius", "c": cindex[cid]}
            elif r is not None and abs(2 * r - mm) < 1e-6:
                con = {"type": "diameter", "c": cindex[cid]}
        elif cls == "sgSkOffsetDim":
            pname = param_name(sk.name, nm)
            off, loop, sources = _offset_constraints(sk, index, cindex, val, pname, offset_done)
            if off:
                sk.offsets.append({"loop": loop, "sources": sources, "param": pname, "value": round(mm, 9)})
                for c in off:
                    c["id"] = f"k{len(cons) + 1}"
                    cons.append(c)
                params.append({"name": pname, "expr": repr(round(mm, 9)), "model": True, "unit": "mm"})
                continue
        if con is None:
            sk.dims_skipped.append(f"{nm} ({cls})")
            continue
        pname = param_name(sk.name, nm)
        con.update({"id": f"k{len(cons) + 1}", "param": pname, "value": round(mm, 9)})
        cons.append(con)
        params.append({"name": pname, "expr": repr(round(mm, 9)), "model": True, "unit": "mm"})
    for con in relation_constraints(sk, index, curves):
        con["id"] = f"k{len(cons) + 1}"
        cons.append(con)
    return cons, params


def _offset_constraints(sk: Sketch, index: dict, cindex: dict, val: float, pname: str, done: set) -> list:
    """An offset (`sgSkOffsetDim`, Sketch > Offset Entities) as SolidCraft constraints, which has
    no offset of its own. The offset curves are those no relation or dimension names (the offset
    holds them); each must lie `val` from a named curve: a line parallel to its partner at that
    distance, an arc concentric with its partner, radius `val` larger or smaller. Written as
    parallel + point-line distance (driven by the offset's parameter) and concentric, plus
    tangent where an offset arc meets an offset line smoothly. Nothing if any offset curve has
    no partner."""
    P = sk.points
    named = set()
    for _t, groups in sk.relations:
        for g in groups:
            named.update(sk.curve_of.get(x) for x in g if x[0] != "point")
    for _nm, _cls, _v, hs in sk.dims:
        named.update(sk.curve_of.get(("line" if c == "sgLineHandle" else "arc", h)) for c, h in hs
                     if c in ("sgLineHandle", "sgArcHandle"))
    lines = {f"l{n + 1}": ln for n, ln in enumerate(sk.lines) if n not in sk.construction}
    arcs = {f"a{n + 1}": (P[a3[2]], math.dist(P[a3[0]], P[a3[2]])) for n, a3 in enumerate(sk.arcs)}
    arcs.update({f"c{n + 1}": (P[c], r) for n, (c, r) in enumerate(sk.circles)})
    unnamed = {k for k in list(lines) + list(arcs) if k not in named and k not in done and k in cindex}
    if not unnamed:
        return [], [], []
    # the whole loop an unnamed curve is on is the offset (a relation can still name one of its
    # curves, e.g. equal to another line)
    free = []
    for ids, _poly in _loops(sk):
        if unnamed & set(ids):
            free += [k for k in ids if k not in done and k in cindex]
    free += [k for k in sorted(unnamed) if k not in free]
    named = {k for k in list(lines) + list(arcs)} - set(free)
    T = 1e-7

    def dist_pl(p, ln):
        (ax, ay), (bx, by) = P[ln[0]], P[ln[1]]
        L = math.hypot(bx - ax, by - ay)
        return abs((p[0] - ax) * (by - ay) - (p[1] - ay) * (bx - ax)) / L if L else -1

    out, sources = [], []
    for k in free:
        partner = None
        if k in lines:
            a, b = lines[k]
            for k2, ln2 in lines.items():
                if k2 in named and abs(dist_pl(P[a], ln2) - val) < T and abs(dist_pl(P[b], ln2) - val) < T:
                    partner = k2
                    break
            if partner is None:
                return [], [], []
            sources.append(partner)
            out += [{"type": "parallel", "a": cindex[k], "b": cindex[partner]},
                    {"type": "point_line_distance", "p": index[a], "l": cindex[partner], "param": pname,
                     "value": round(val * 1000, 9)}]
        else:
            c, r = arcs[k]
            for k2, (c2, r2) in arcs.items():
                if k2 in named and math.dist(c, c2) < T and abs(abs(r - r2) - val) < T:
                    partner = k2
                    break
            if partner is None:
                return [], [], []
            sources.append(partner)
            out.append({"type": "concentric", "a": cindex[k], "b": cindex[partner]})
            if k[0] == "a":
                n = int(k[1:]) - 1
                s0, e0, ctr = sk.arcs[n]
                for kl, (la, lb) in lines.items():
                    if kl not in free:
                        continue
                    for end in (s0, e0):
                        if end in (la, lb) and abs(dist_pl(P[ctr], (la, lb)) - r) < T:
                            out.append({"type": "tangent", "a": cindex[k], "b": cindex[kl]})
    done.update(free)
    return out, free, sources


def relation_constraints(sk: Sketch, index: dict, curves: list) -> list:
    """The sketch's relations as SolidCraft constraints. Types decoded (checked on the sample
    sets): 4 horizontal, 5 vertical, 6 tangent, 7 parallel, 8 perpendicular, 9 coincident / point
    on a curve, 12 midpoint, 13 a point at two lines' intersection, 14 and 57 equal, 27 collinear,
    28 concentric, 11 symmetric about a line, 25 / 26 two points level or plumb. A relation is
    written only when everything it names was read and it holds in the sketch as read; the rest
    are counted in sk.relations_skipped."""
    P = sk.points
    cindex = {c["id"]: n for n, c in enumerate(curves)}
    T = 1e-9
    out = []
    sk.relations_skipped = 0

    def ent(kind, hid):
        if kind == "point":
            pid = hid + 1
            if pid not in P or pid not in index:
                return None
            return ("point", index[pid], P[pid])
        key = sk.curve_of.get((kind, hid))
        if not key or key not in cindex:
            return None
        n = int(key[1:]) - 1
        if key[0] == "l":
            a, b = sk.lines[n]
            return ("line", cindex[key], (P[a], P[b]))
        if key[0] == "a":
            a, b, c = sk.arcs[n]
            return ("arc", cindex[key], (P[c], math.dist(P[a], P[c])))
        c, r = sk.circles[n]
        return ("arc", cindex[key], (P[c], r))

    def dv(l):
        return (l[1][0] - l[0][0], l[1][1] - l[0][1])

    def on_line(p, l):
        d = dv(l)
        n = math.hypot(*d)
        return n > T and abs((p[0] - l[0][0]) * d[1] - (p[1] - l[0][1]) * d[0]) <= T * n

    def cross_dot(l1, l2):
        u, v = dv(l1), dv(l2)
        n = math.hypot(*u) * math.hypot(*v)
        return (abs(u[0] * v[1] - u[1] * v[0]) / n, abs(u[0] * v[0] + u[1] * v[1]) / n) if n else (1, 1)

    for t, groups in sk.relations:
        for g in groups:
            es = [ent(k, h) for k, h in g]
            if not es or any(e is None for e in es):
                sk.relations_skipped += 1
                continue
            kinds = [e[0] for e in es]
            L = [e for e in es if e[0] == "line"]
            A = [e for e in es if e[0] == "arc"]
            Pp = [e for e in es if e[0] == "point"]
            con = None
            if t == 4 and kinds == ["line"] and abs(dv(L[0][2])[1]) < T:
                con = [{"type": "horizontal", "l": L[0][1]}]
            elif t == 5 and kinds == ["line"] and abs(dv(L[0][2])[0]) < T:
                con = [{"type": "vertical", "l": L[0][1]}]
            elif t == 6 and len(es) == 2 and not Pp:
                if len(A) == 1 and len(L) == 1:
                    (c, r), l = A[0][2], L[0][2]
                    d = dv(l); n = math.hypot(*d)
                    if n and abs(abs((c[0] - l[0][0]) * d[1] - (c[1] - l[0][1]) * d[0]) / n - r) < T:
                        con = [{"type": "tangent", "a": es[0][1], "b": es[1][1]}]
                elif len(A) == 2:
                    dist = math.dist(A[0][2][0], A[1][2][0])
                    if abs(dist - (A[0][2][1] + A[1][2][1])) < T or abs(dist - abs(A[0][2][1] - A[1][2][1])) < T:
                        con = [{"type": "tangent", "a": es[0][1], "b": es[1][1]}]
            elif t in (7, 8, 27) and len(L) == 2 and len(es) == 2:
                c_, d_ = cross_dot(L[0][2], L[1][2])
                if t == 7 and c_ < T:
                    con = [{"type": "parallel", "a": L[0][1], "b": L[1][1]}]
                elif t == 8 and d_ < T:
                    con = [{"type": "perpendicular", "a": L[0][1], "b": L[1][1]}]
                elif t == 27 and c_ < T and on_line(L[1][2][0], L[0][2]):
                    con = [{"type": "collinear", "a": L[0][1], "b": L[1][1]}]
            elif t in (14, 57) and len(es) == 2 and not Pp:
                if len(L) == 2:
                    if abs(math.hypot(*dv(L[0][2])) - math.hypot(*dv(L[1][2]))) < T:
                        con = [{"type": "equal", "a": L[0][1], "b": L[1][1]}]
                elif len(A) == 2 and abs(A[0][2][1] - A[1][2][1]) < T:
                    con = [{"type": "equal", "a": A[0][1], "b": A[1][1]}]
            elif t == 28 and len(A) == 2 and len(es) == 2 and math.dist(A[0][2][0], A[1][2][0]) < T:
                con = [{"type": "concentric", "a": A[0][1], "b": A[1][1]}]
            elif t in (9, 12) and len(es) == 2:
                if len(Pp) == 2 and math.dist(Pp[0][2], Pp[1][2]) < T and Pp[0][1] != Pp[1][1]:
                    con = [{"type": "coincident", "p": Pp[0][1], "q": Pp[1][1]}]
                elif len(Pp) == 1 and len(L) == 1 and on_line(Pp[0][2], L[0][2]):
                    m = ((L[0][2][0][0] + L[0][2][1][0]) / 2, (L[0][2][0][1] + L[0][2][1][1]) / 2)
                    if t == 12 and math.dist(Pp[0][2], m) < T:
                        con = [{"type": "midpoint", "p": Pp[0][1], "l": L[0][1]}]
                    else:
                        con = [{"type": "point_on_curve", "p": Pp[0][1], "c": L[0][1]}]
                elif len(Pp) == 1 and len(A) == 1 and abs(math.dist(Pp[0][2], A[0][2][0]) - A[0][2][1]) < T:
                    con = [{"type": "point_on_curve", "p": Pp[0][1], "c": A[0][1]}]
            elif t == 13 and len(Pp) == 1 and len(L) == 2 and all(on_line(Pp[0][2], l[2]) for l in L):
                con = [{"type": "point_on_curve", "p": Pp[0][1], "c": l[1]} for l in L]
            elif t == 11 and len(Pp) == 2 and len(L) == 1:
                a, b = Pp[0][2], Pp[1][2]
                m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                ab = (b[0] - a[0], b[1] - a[1]); d = dv(L[0][2])
                if on_line(m, L[0][2]) and abs(ab[0] * d[0] + ab[1] * d[1]) < T * max(math.hypot(*ab), T) * math.hypot(*d):
                    con = [{"type": "symmetric", "p": Pp[0][1], "q": Pp[1][1], "l": L[0][1]}]
            elif t in (25, 26) and len(Pp) == 2 and len(es) == 2:
                if abs(Pp[0][2][1] - Pp[1][2][1]) < T:
                    con = [{"type": "horizontal_points", "p": Pp[0][1], "q": Pp[1][1]}]
                elif abs(Pp[0][2][0] - Pp[1][2][0]) < T:
                    con = [{"type": "vertical_points", "p": Pp[0][1], "q": Pp[1][1]}]
            if con is None:
                sk.relations_skipped += 1
                continue
            out.extend(con)
    # one constraint once (a relation can be stored twice)
    seen, uniq = set(), []
    for c in out:
        key = tuple(sorted(c.items()))
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    return uniq


def _arc_ends(sk: Sketch, a: int, c: int, ctr: int) -> tuple[int, int]:
    """(start, end) so that the arc runs anticlockwise from start to end as drawn."""
    P = sk.points
    key = lambda pid: (round(P[pid][0], 9), round(P[pid][1], 9))
    cx, cy = P[ctr]
    for e, other_end in ((a, c), (c, a)):
        for l1, l2 in sk.lines:
            if key(e) not in (key(l1), key(l2)):
                continue
            o = l2 if key(e) == key(l1) else l1
            dx, dy = P[e][0] - P[o][0], P[e][1] - P[o][1]          # the line arriving at e
            rx, ry = P[e][0] - cx, P[e][1] - cy
            L = math.hypot(dx, dy) * math.hypot(rx, ry)
            if L == 0 or abs(dx * rx + dy * ry) > 1e-6 * L:
                continue                                         # not a smooth joint
            ccw_leaves = -ry * dx + rx * dy > 0                  # anticlockwise from e carries on
            return (e, other_end) if ccw_leaves else (other_end, e)
    (ax, ay), (bx, by) = P[a], P[c]
    sweep = (math.atan2(by - cy, bx - cx) - math.atan2(ay - cy, ax - cx)) % (2 * math.pi)
    return (c, a) if sweep > math.pi + 1e-12 else (a, c)


def _loops(sk: Sketch) -> list[tuple[list[str], list[tuple[float, float]]]]:
    """Closed loops of the sketch's curves: (curve ids as sketch_feature names them, a polygon
    through the loop for nesting tests)."""
    P = sk.points
    edges = []  # (curve id, a, b, sample points)
    for n, (a, c) in enumerate(sk.lines):
        if n not in sk.construction:      # construction lines bound no profile
            edges.append((f"l{n + 1}", a, c, [P[a], P[c]]))
    for n, (a, c, ctr) in enumerate(sk.arcs):
        cx, cy = P[ctr]
        r = math.hypot(P[a][0] - cx, P[a][1] - cy)
        a2, c2 = _arc_ends(sk, a, c, ctr)      # anticlockwise from start to end, as the design writes it
        t0 = math.atan2(P[a2][1] - cy, P[a2][0] - cx); t1 = math.atan2(P[c2][1] - cy, P[c2][0] - cx)
        if t1 <= t0:
            t1 += 2 * math.pi
        # the whole arc, not its chord: whether a loop lies inside another is decided by these
        # points, and an arc bulging outward can put a hole outside its outline's chord
        # (Boom's fourth pin hole, inside a 2.275 mm round end, read as an island)
        k = max(2, int(math.ceil((t1 - t0) / (math.pi / 8))))
        poly = [(cx + r * math.cos(t0 + (t1 - t0) * i / k), cy + r * math.sin(t0 + (t1 - t0) * i / k))
                for i in range(k + 1)]
        edges.append((f"a{n + 1}", a, c, poly))
    loops = []
    for n, (ctr, r) in enumerate(sk.circles):
        cx, cy = P[ctr]
        loops.append(([f"c{n + 1}"], [(cx + r * math.cos(2 * math.pi * k / 16), cy + r * math.sin(2 * math.pi * k / 16)) for k in range(16)]))
    # join points at the same place (a junction can be two point records)
    key = lambda pid: (round(P[pid][0], 9), round(P[pid][1], 9))
    at = {}
    for e in edges:
        at.setdefault(key(e[1]), []).append(e); at.setdefault(key(e[2]), []).append(e)
    used = set()
    for e in edges:
        if e[0] in used:
            continue
        ids, poly, cur, here = [e[0]], list(e[3]), e, key(e[2])
        used.add(e[0])
        start = key(e[1])
        ok = False
        for _ in range(len(edges)):
            if here == start:
                ok = True
                break
            nxt = [x for x in at.get(here, []) if x[0] not in used]
            if len(nxt) != 1:
                break
            x = nxt[0]; used.add(x[0]); ids.append(x[0])
            fwd = key(x[1]) == here
            poly += x[3] if fwd else x[3][::-1]
            here = key(x[2]) if fwd else key(x[1])
        if ok:
            loops.append((ids, poly))
    return loops


def _inside(pt, poly) -> bool:
    x, y = pt
    c = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-30) + x1:
            c = not c
    return c


def revolve_axes(sk: Sketch) -> list[str]:
    """Lines a revolve can turn about: the sketch's lines on no closed loop (a centreline)."""
    in_loops = {c for ids, _ in _loops(sk) for c in ids}
    free = [n for n in range(len(sk.lines)) if f"l{n + 1}" not in in_loops]
    return [f"l{n + 1}" for n in sorted(free, key=lambda n: n not in sk.construction)]  # centrelines first


def revolve_axis_options(sk: Sketch) -> list[dict]:
    """What a revolve may turn about, most likely first: a line on no loop (a centreline), the
    sketch's own x and y axes (an axis through the origin, often drawn as nothing), then a line
    of the profile itself (the profile sitting on its axis)."""
    free = revolve_axes(sk)
    in_loops = {c for ids, _ in _loops(sk) for c in ids if c.startswith("l")}
    return ([{"type": "sketch_line", "curve": c} for c in free] +
            [{"type": "sketch_axis", "axis": "x"}, {"type": "sketch_axis", "axis": "y"}] +
            [{"type": "sketch_line", "curve": c} for c in sorted(in_loops)])


def profile_loops(sk: Sketch) -> list[list[str]]:
    """The loops to extrude: those nested inside an even number of others (outlines and islands);
    the loops inside them are holes, as SolidWorks extrudes a sketch."""
    loops = _loops(sk)
    out = []
    for ids, poly in loops:
        # test a point just inside the loop next to one of its edges: a corner can lie on another
        # loop's edge, and the loop's middle can lie in a hole of its own
        probe = poly[0]
        for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
            L = math.hypot(x2 - x1, y2 - y1)
            if L < 1e-9:
                continue
            mx, my, nx, ny = (x1 + x2) / 2, (y1 + y2) / 2, -(y2 - y1) / L, (x2 - x1) / L
            for sgn in (1, -1):
                q = (mx + sgn * nx * 1e-6, my + sgn * ny * 1e-6)
                if _inside(q, poly):
                    probe = q
                    break
            else:
                continue
            break
        depth = sum(1 for ids2, poly2 in loops if ids2 is not ids and _inside(probe, poly2))
        if depth % 2 == 0:
            out.append(ids)
    return out


def extrude_feature(f: Feature, fid: int, sketch_id: int, direction: str, operation: str,
                    loops: list | None = None, to: list | None = None) -> dict:
    prof = {"type": "curves", "loops": loops} if loops else {"type": "all"}
    if to is not None:    # up to a face (SolidWorks' up to next / up to surface): a point on it
        return {"id": fid, "name": f.name, "type": "extrude", "sketch": sketch_id, "suppressed": False,
                "operation": operation, "profiles": prof,
                "extent": {"convention": "total_distance", "direction": direction, "distance": "0", "to": list(to)},
                **({"body_names": [f.name]} if operation == "new_body" else {})}
    return {"id": fid, "name": f.name, "type": "extrude", "sketch": sketch_id, "suppressed": False,
            "operation": operation, "profiles": prof,
            "extent": ({"convention": "total_distance", "direction": direction, "distance": "0", "through_all": True}
                       if f.through_all else
                       {"convention": "total_distance", "direction": direction, "distance": repr(round(f.depth_mm, 9))}),
            **({"body_names": [f.name]} if operation == "new_body" else {})}


def design(name: str, feats: list[Feature], choices: dict, planes: dict | None = None,
           constraints: bool = True, fillets: dict | None = None, upto: str | None = None) -> dict:
    """A single-body SolidCraft design from fully decoded features. `choices` gives each extrude's
    (direction, operation) by name; defaults: positive, new body first then join (cut for cuts).
    `upto`: stop after that feature."""
    out, ids, sk_of = [], {}, {}
    nid = 1
    first = True
    for f in feats:
        if f.kind == "sketch":
            f.sketch.choice = (planes or {}).get(f.name, 0)
            sk = with_centres(f.sketch, choices.get("arcs:" + f.name))
            out.append(sketch_feature(sk, nid, constraints)); ids[f.name] = nid; sk_of[f.name] = sk
            f.sketch.params = sk.params   # (a copy with an arc turned holds them)
        elif f.kind in ("boss", "cut"):
            d, op = choices.get(f.name, ("positive", None))
            if op is None:
                op = "new_body" if first else ("cut" if f.kind == "cut" else "join")
            g = extrude_feature(f, nid, ids[f.profile], d, op, profile_loops(sk_of[f.profile]),
                                (fillets or {}).get("to:" + f.name))
            span = (fillets or {}).get("span:" + f.name)
            if span is not None:   # a boss through all: as far as the body reaches (verify)
                g["extent"] = {"convention": "total_distance", "direction": d, "distance": repr(round(span, 9))}
            start = (fillets or {}).get("start:" + f.name)
            if start is not None:   # starting at a face of the body so far (verify)
                g["extent"]["start_offset"] = repr(round(start, 9))
            if f.thin_mm:   # a wall along all its sketch's curves, on the side the search chooses
                sk = sk_of[f.profile]
                cur = [f"l{n + 1}" for n in range(len(sk.lines)) if n not in sk.construction] + \
                      [f"a{n + 1}" for n in range(len(sk.arcs))] + [f"c{n + 1}" for n in range(len(sk.circles))]
                g["thin"] = {"curves": cur, "thickness": repr(f.thin_mm),
                             "side": (fillets or {}).get("thin:" + f.name, "center")}
                g["profiles"] = {"type": "all"}
            out.append(g)
            first = False
        elif f.kind in ("revolve", "revcut"):
            sk = sk_of[f.profile]
            axes = revolve_axis_options(sk)
            ai, sign = choices.get(f.name, (0, 1))
            op = "new_body" if first else ("cut" if f.kind == "revcut" else "join")
            out.append({"id": nid, "name": f.name, "type": "revolve", "sketch": ids[f.profile], "suppressed": False,
                        "operation": op, "profiles": {"type": "curves", "loops": profile_loops(sk)},
                        "axis": axes[ai % len(axes)],
                        "angle": repr(round(sign * f.angle_deg, 9)), "convention": "sketch_normal",
                        **({"body_names": [f.name]} if op == "new_body" else {})})
            first = False
        elif f.kind in ("fillet", "chamfer"):
            picked = (fillets or {}).get(f.name)
            if picked is None:      # its edges are found in the design up to here (sw2sc.fillets)
                d = design_tail(name, feats, out, nid)
                d["pending"] = f.name
                return d
            picked = list({n: (m, n) for m, n in picked}.values())   # an edge two SolidWorks faces share: once
            g = {"id": nid, "name": f.name, "type": f.kind, "suppressed": False,
                 "edges": [list(m) for m, _n in picked], "edge_names": [n for _m, n in picked]}
            if f.kind == "fillet":
                g["radius"] = param_name(f.name, "D1")
            else:
                # which face the distance runs along: SolidCraft's `flip`, tried both ways
                g["distance"] = param_name(f.name, "D1")
                if f.chamfer_mm2 is not None:
                    g["distance2"] = param_name(f.name, "D2")
                elif abs(f.chamfer_deg - 45) > 1e-9:
                    g["angle"] = f"{round(f.chamfer_deg, 9)} deg"
                if (fillets or {}).get("flip:" + f.name):
                    g["flip"] = True
            out.append(g)
        elif f.kind == "shell":
            got = (fillets or {}).get("shell:" + f.name)
            if got is None:
                d = design_tail(name, feats, out, nid)
                d["pending"] = f.name
                return d
            out.append({"id": nid, "name": f.name, "type": "shell", "suppressed": False,
                        "faces": [list(p) for p in got], "thickness": repr(f.thin_mm)})
        elif f.kind in ("sweep", "sweepcut"):
            swap = (fillets or {}).get("swap:" + f.name, False)
            prof, path = (f.path, f.profile) if swap else (f.profile, f.path)
            psk = sk_of[path]
            path_curves = [f"l{n + 1}" for n in range(len(psk.lines)) if n not in psk.construction] + \
                          [f"a{n + 1}" for n in range(len(psk.arcs))]
            op = "new_body" if first else ("cut" if f.kind == "sweepcut" else "join")
            out.append({"id": nid, "name": f.name, "type": "sweep", "suppressed": False, "sketch": ids[prof],
                        "profiles": {"type": "curves", "loops": profile_loops(sk_of[prof])} if profile_loops(sk_of[prof]) else {"type": "all"},
                        "path_sketch": ids[path], "path": path_curves, "operation": op,
                        **({"body_names": [f.name]} if op == "new_body" else {})})
            first = False
        elif f.kind == "scale":
            got = (fillets or {}).get("scale:" + f.name)
            if got is None:        # the point it scales about is chosen in the design so far (verify)
                d = design_tail(name, feats, out, nid)
                d["pending"] = f.name
                return d
            body = next((x["body_names"][0] for x in out if x.get("body_names")), None)
            sx, sy, sz = f.scale
            g = {"id": nid, "name": f.name, "type": "scale", "suppressed": False,
                 "bodies": [body] if body else [], "origin": list(got)}
            if abs(sx - sy) < 1e-12 and abs(sx - sz) < 1e-12:
                g["factor"] = repr(sx)
            else:
                g["factors"] = [repr(sx), repr(sy), repr(sz)]
            out.append(g)
        elif f.kind == "dome":
            got = (fillets or {}).get("dome:" + f.name)
            if got is None:        # the circular face it sits on is chosen in the design so far (verify)
                d = design_tail(name, feats, out, nid)
                d["pending"] = f.name
                return d
            # SolidCraft has no dome feature; it makes domes as a revolve of an arc (its button
            # heads do): a quarter profile on a plane through the face's axis, turned about it
            c, n, r = got
            h = f.dome_mm
            u = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0)
            dot = sum(p * q for p, q in zip(u, n))
            u = [p - dot * q for p, q in zip(u, n)]
            ln = sum(x * x for x in u) ** 0.5
            u = [x / ln for x in u]
            big = (r * r + h * h) / (2 * h)
            pts = [{"fixed": True, "id": "origin", "pos": [0.0, 0.0]}, {"fixed": False, "id": "rim", "pos": [r, 0.0]},
                   {"fixed": False, "id": "apex", "pos": [0.0, h]}, {"fixed": False, "id": "ctr", "pos": [0.0, h - big]}]
            curves = [{"a": 0, "b": 1, "construction": False, "id": "l1", "type": "line"},
                      {"a": 1, "b": 2, "c": 3, "construction": False, "id": "a1", "type": "arc"},
                      {"a": 2, "b": 0, "construction": False, "id": "l2", "type": "line"}]
            out.append({"id": nid, "name": f.name + " profile", "type": "sketch", "suppressed": False,
                        "plane": {"type": "custom", "plane": {"origin": list(c), "x_dir": u, "y_dir": list(n)}},
                        "sketch": {"constraints": [], "curves": curves, "points": pts,
                                   "counters": {"a": 1, "c": 0, "k": 0, "l": 2}}})
            nid += 1
            out.append({"id": nid, "name": f.name, "type": "revolve", "sketch": nid - 1, "suppressed": False,
                        "operation": "join", "profiles": {"type": "curves", "loops": [["l1", "a1", "l2"]]},
                        "axis": {"type": "sketch_line", "curve": "l2"}, "angle": "360", "convention": "sketch_normal"})
        elif f.kind == "pattern":
            got = (fillets or {}).get("pattern:" + f.name)
            if got is None:        # its direction or axis and what it repeats are chosen (verify)
                d = design_tail(name, feats, out, nid)
                d["pending"] = f.name
                return d
            pat, what = got
            by_name = {x["name"]: x["id"] for x in out}
            out.append({"id": nid, "name": f.name, "type": "pattern", "suppressed": False,
                        "features": [by_name[n] for n in what if n in by_name], "pattern": pat})
        elif f.kind == "thread":
            got = (fillets or {}).get("thread:" + f.name)
            if got is None:        # its face and start are chosen in the design so far (verify)
                d = design_tail(name, feats, out, nid)
                d["pending"] = f.name
                return d
            face, start = got
            t = f.thread
            out.append({"id": nid, "name": f.name, "type": "thread", "suppressed": False, "face": list(face),
                        "from": list(start), "designation": f"M{t['diameter']:g}x{t['pitch']:g}",
                        **({"length": repr(t["length"])} if "length" in t else {}),
                        "modeled": True, "continuous_flanks": True})
        elif f.kind == "mirror":
            got = (fillets or {}).get("mirror:" + f.name)
            if got is None:        # its plane and what it mirrors are chosen in the design so far (verify)
                d = design_tail(name, feats, out, nid)
                d["pending"] = f.name
                return d
            plane, what = got
            g = {"id": nid, "name": f.name, "type": "mirror", "suppressed": False, "plane": {"type": "custom", "plane": plane}}
            if what == "body":     # the body so far, mirrored and joined
                body = next((x["body_names"][0] for x in out if x.get("body_names")), None)
                g.update({"features": [], "bodies": [body] if body else [], "combine": True})
            else:                  # these features replayed on the other side
                by_name = {x["name"]: x["id"] for x in out}
                g["features"] = [by_name[n] for n in what if n in by_name]
            out.append(g)
        elif f.kind == "hole":
            sk = sk_of[f.profile]
            through, flip = (fillets or {}).get("hole:" + f.name, (False, False))
            (_x, _y, nrm), t = sk.plane
            pids = [p for p in sorted(sk.points) if not (p == 1 and max(map(abs, sk.points[p])) < 1e-12)]
            # the hole points are the sketch's own points, not the ends or centres of curves
            # drawn in it (construction to place them)
            on_curve = {q for ln in sk.lines for q in ln} | {q for a in sk.arcs for q in a} | {c for c, _r in sk.circles}
            pids = [p for p in pids if p not in on_curve] or pids
            chosen = (fillets or {}).get("holepts:" + f.name)
            if chosen:
                pids = [p for p in pids if p in chosen] or pids
            g = {"id": nid, "name": f.name, "type": "hole", "suppressed": False,
                 "diameter": param_name(f.name, "diameter"),
                 "direction": [-c for c in nrm],
                 "position": [t[k] * 1000 + sk.points[pids[0]][0] * 1000 * sk.plane[0][0][k] +
                              sk.points[pids[0]][1] * 1000 * sk.plane[0][1][k] for k in range(3)] if pids else [0, 0, 0],
                 "points": {"sketch": ids[f.profile], "ids": [f"p{p}" for p in pids], **({"flip": True} if flip else {})}}
            h = f.hole
            if "depth" in h and not through:
                g["depth"] = param_name(f.name, "depth")
            if "cs_diameter" in h:
                g["hole"] = {"type": "countersink", "cs_diameter": param_name(f.name, "cs_diameter"),
                             "cs_angle": f"{h.get('cs_angle', 90)} deg"}
            elif "cb_diameter" in h:
                g["hole"] = {"type": "counterbore", "cb_diameter": param_name(f.name, "cb_diameter"),
                             "cb_depth": param_name(f.name, "cb_depth")}
            elif "tip_angle" in h and "depth" in g:
                g["hole"] = {"type": "drilled", "tip_angle": f"{h['tip_angle']} deg"}
            out.append(g)
        elif f.kind == "import":
            # the body as it was imported, the features after it built on it
            if f.import_step is None and f.import_body:
                from . import geometry
                f.import_step = geometry.body_step(f.import_body, f.name) or ""
            out.append({"id": nid, "name": f.name, "type": "import", "suppressed": False,
                        "file": f.name + ".step", "step": f.import_step or ""})
            first = False
        elif f.kind == "plane":
            (x, y, _n), t = f.frame
            base = {"type": "custom", "plane": {"origin": [c * 1000 for c in t], "x_dir": list(x), "y_dir": list(y)}}
            out.append({"id": nid, "name": f.name, "type": "construction_plane", "suppressed": False,
                        "plane": {"type": "offset", "base": base, "distance": "0"}})
        nid += 1
        if f.name == upto:
            break
    return design_tail(name, feats, out, nid)


def design_tail(name: str, feats: list[Feature], out: list, nid: int) -> dict:
    """The design from its features: the model parameters the sketches' dimensions, the
    extrudes' depths and the fillets' radii drive."""
    written = {g["name"] for g in out}
    params = [p for f in feats if f.kind == "sketch" and f.name in written for p in f.sketch.params]
    params += [{"name": param_name(f.name, "D1"), "expr": repr(round(f.radius_mm, 9)), "model": True, "unit": "mm"}
               for f in feats if f.kind in ("fillet", "chamfer") and f.name in written]
    params += [{"name": param_name(f.name, "D2"), "expr": repr(round(f.chamfer_mm2, 9)), "model": True, "unit": "mm"}
               for f in feats if f.kind == "chamfer" and f.chamfer_mm2 is not None and f.name in written]
    params += [{"name": param_name(f.name, k), "expr": repr(v), "model": True, "unit": "mm"}
               for f in feats if f.kind == "hole" and f.name in written for k, v in f.hole.items()
               if k in ("diameter", "depth", "cs_diameter", "cb_diameter", "cb_depth")]
    for g in out:  # each extrude's depth as a model parameter, named after SolidWorks' D1@<feature>
        ext = g.get("extent") if g.get("type") == "extrude" else None
        if ext and not ext.get("through_all"):
            pname = param_name(g["name"], "D1")
            params.append({"name": pname, "expr": ext["distance"], "model": True, "unit": "mm"})
            ext["distance"] = pname
    return {"format": "solidcraft/55", "name": name, "units": "mm", "params": params, "features": out, "next_id": nid}
