"""A fillet's edges in the rebuilt SolidCraft design (F-032).

SolidWorks names a fillet's edges by the faces meeting there (sw2sc.features._edge_refs): a
face swept by a sketch entity of a feature, or a feature's end face (0 start, 1 end).
SolidCraft names an edge the same way (`F5:side:l3|F5:top`, `model.edges`). What the file's
names don't give directly is which of our sketch curves an entity number is (that numbering is
the sketch's own and isn't decoded in every file) and which end face is SolidCraft's start or
top. Both are solved for: an assignment is kept when every edge SolidWorks names is an edge of
the rebuilt body. All assignments that fit are returned; the rebuild check against the part's
own solid picks between them.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess

MAX_SOLUTIONS = 40    # assignments kept per fillet
BUDGET = 200_000      # matches tried per start before giving it up (no start: the part keeps its solid)
# a face split in pieces carries `#[its neighbours]`; SolidWorks names every piece by its entity too
_FACE = re.compile(r"F(\d+):(?:side:([A-Za-z]+\d+)(?:#\[[^\]]*\])?|(start|top|bottom|end)(?:#\[[^\]]*\])?|blend\((.*)\))$")


def _split(name: str) -> list:
    """An edge name's two faces: split at the `|` outside parentheses."""
    parts, depth, cur = [], 0, ""
    for ch in name:
        if ch == "|" and depth == 0:
            parts.append(cur)
            cur = ""
            continue
        depth += (ch == "(") - (ch == ")")
        cur += ch
    return parts + [cur]


def _faces(name: str):
    """(kind, feature id, which) for each face: a side from a sketch curve, an end face (start
    or top), or a fillet's blend, named by the edge it rounds."""
    out = []
    for part in _split(name or ""):
        m = _FACE.match(part)
        if not m:
            return None
        fid = int(m.group(1))
        out.append(("side", fid, m.group(2)) if m.group(2) else ("end", fid, m.group(3)) if m.group(3)
                   else ("blend", fid, m.group(4)))
    return tuple(out) if len(out) == 2 else None


def body_faces(design: dict, cli: str, tmp: str) -> list | None:
    """Every face of the design's bodies as `model.faces` gives it (name, plane_normal for a
    flat one, centroid, point)."""
    from .verify import past_deadline
    if past_deadline():
        return None
    src, out, script = (os.path.join(tmp, n) for n in ("pref.solidcraft", "pref.json", "faces.json"))
    with open(src, "w", encoding="utf-8") as fh:
        json.dump(design, fh)
    try:
        ev = json.loads(subprocess.run([cli, "eval", src], capture_output=True, timeout=300).stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    names = [b["name"] for b in ev.get("bodies", []) if b.get("name")]
    if not names:
        return None
    with open(script, "w", encoding="utf-8") as fh:
        json.dump({"commands": [{"command": "model.faces", "params": {"body": n}} for n in names]}, fh)
    if os.path.exists(out):
        os.remove(out)
    try:
        subprocess.run([cli, "run", script, "--in", src, "--results", "--json-out", out], capture_output=True, timeout=300)
        res = json.load(open(out, encoding="utf-8"))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    return [face for r in (res if isinstance(res, list) else []) for face in r.get("faces", [])]


def body_edges(design: dict, cli: str, tmp: str, raw: list | None = None) -> list | None:
    """Every edge of the design's bodies: (faces, mid point, name). `raw` gets every edge as
    (mid point, name), those whose faces aren't read too (a hole's bore, `F4:bore:side:2`)."""
    from .verify import past_deadline
    if past_deadline():
        return None
    src, out, script = (os.path.join(tmp, n) for n in ("pre.solidcraft", "pre.json", "edges.json"))
    with open(src, "w", encoding="utf-8") as fh:
        json.dump(design, fh)
    try:
        ev = json.loads(subprocess.run([cli, "eval", src], capture_output=True, timeout=300).stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    names = [b["name"] for b in ev.get("bodies", []) if b.get("name")]
    if not names:
        return None
    with open(script, "w", encoding="utf-8") as fh:
        json.dump({"commands": [{"command": "model.edges", "params": {"body": n}} for n in names]}, fh)
    if os.path.exists(out):
        os.remove(out)
    try:
        subprocess.run([cli, "run", script, "--in", src, "--results", "--json-out", out], capture_output=True, timeout=300)
        res = json.load(open(out, encoding="utf-8"))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    edges = []
    for r in res if isinstance(res, list) else []:
        for e in r.get("edges", []):
            if raw is not None and e.get("mid") is not None:
                raw.append((e["mid"], e.get("name")))
            fc = _faces(e.get("name"))
            if fc:
                edges.append((fc, e["mid"], e["name"]))
    return edges


def solve(sw_edges: list, sc_edges: list, design_id: dict, sketch_curves: dict, known: list | None = None,
          blends: dict | None = None, ends: list | None = None, all_edges: list | None = None) -> list:
    """Assignments of SolidWorks faces to SolidCraft's that make every edge in `sw_edges` an
    edge of `sc_edges`; each solution is the list of SolidCraft edges (mid point, name), in the
    order SolidWorks lists them, with every assignment that reaches it (the same edges can be
    reached with two entities swapped, and a later fillet may tell them apart). `design_id`:
    SolidWorks feature id -> design feature id; `sketch_curves`: design feature id -> the curve
    ids its faces can come from; `blends`: design id of an earlier fillet -> its edges' names
    (its faces are the rounds of those edges); `known`: the assignments earlier fillets left
    open (an entity number means the same curve in every fillet).

    A constraint search: the edge with the fewest consistent matches goes next, and a branch
    stops as soon as some edge has none. `ends`: for each edge the two faces at its ends; each
    borders a face of the edge, so their SolidCraft faces must share an edge too (`all_edges`:
    every edge of the body, smooth ones included)."""
    blends = blends or {}
    solutions = []
    plain = lambda f: f if f[0] != "side" else ("side", f[1], f[2])  # noqa: E731
    touching = {frozenset(map(plain, fc)) for fc, _m, _n in (all_edges or sc_edges)}
    # (face ref, face ref) pairs that must touch: an edge's end faces border its faces
    borders: dict = {}
    for (a, b), e2 in zip(sw_edges, ends or []):
        for x in e2:
            for y in (a, b):
                if x != y and x[0] == y[0] == "side":
                    borders.setdefault(x, set()).add(y)
                    borders.setdefault(y, set()).add(x)
    # a curve whose face comes in pieces (SolidCraft's `#[...]` names) can be several SolidWorks
    # entities: SolidWorks drew collinear lines where the sketch as read has one
    pieces: dict = {}
    for _fc, _m, name in (all_edges or sc_edges):
        for m in re.finditer(r"F(\d+):side:([A-Za-z]+\d+)(#\[[^\]]*\])", name):
            pieces.setdefault((int(m.group(1)), m.group(2)), set()).add(m.group(3))
    split = {k: len(v) for k, v in pieces.items()}   # a curve in n pieces hosts up to n entities

    def fits(ref, face, amap):
        """The bindings `ref -> face` adds to `amap`, or None if it can't."""
        kind, fid, v = ref
        d = design_id.get(fid)
        if d is None or face[1] != d:
            return None
        if ref in amap:
            return {} if amap[ref] == face else None
        if kind == "side":
            want = "blend" if d in blends else "side"
            pool = blends[d] if d in blends else sketch_curves.get(d, [])
            if face[0] != want or face[2] not in pool:
                return None
            for nb in borders.get(ref, ()):
                if nb in amap and amap[nb] != face and frozenset((face, amap[nb])) not in touching:
                    return None   # SolidWorks says these faces meet; these SolidCraft faces don't
            sharers = [r2 for r2, val in amap.items() if r2 != ref and r2[0] == "side" and r2[1] == fid and val == face]
            # a curve in n pieces can be n entities; and SolidWorks may have drawn as two collinear
            # lines what the sketch as read has as one: an entity next to the one holding the
            # curve (their faces meet, SolidWorks says) may share it
            if len(sharers) >= split.get((face[1], face[2]), 1) and not all(x in borders.get(ref, ()) for x in sharers):
                return None   # other entities have that curve already
            return {ref: face}
        if face[0] != "end":
            return None
        other = amap.get(("end", fid, 1 - v))
        if other is not None and other[2] == face[2]:
            return None       # start and end are two faces
        return {ref: face}

    def kinds_fit(ref, face):
        d = design_id.get(ref[1])
        if d is None or face[1] != d:
            return False
        if ref[0] == "end":
            return face[0] == "end"
        return face[0] == ("blend" if d in blends else "side")

    # each SolidWorks edge's possible SolidCraft edges, by kind and feature alone
    # (an edge SolidWorks gives as one face twice, a cylinder's rim: any edge of that face)
    pool = [[e for e in sc_edges if (kinds_fit(a, e[0][0]) and kinds_fit(b, e[0][1])) or
             (kinds_fit(a, e[0][1]) and kinds_fit(b, e[0][0])) or
             (a == b and (kinds_fit(a, e[0][0]) or kinds_fit(a, e[0][1])))] for a, b in sw_edges]
    work = [0]

    def matches(i, amap, used):
        a, b = sw_edges[i]
        out = []
        for fc, mid, name in pool[i]:
            work[0] += 1
            for f1, f2 in ((fc[0], fc[1]), (fc[1], fc[0])):
                b1 = fits(a, f1, amap)
                if b1 is None:
                    continue
                if a == b:
                    # SolidWorks gives one face for it (a cylinder's rim between its end and its
                    # side): an edge of that face, the other face left open
                    b2 = {}
                else:
                    b2 = fits(b, f2, {**amap, **b1})
                    if b2 is None:
                        continue
                if name in used:
                    # an edge already taken: only by an entity sharing its curve with a neighbour
                    # (two collinear SolidWorks faces, one SolidCraft face, one edge along both)
                    shared = any(r[0] == "side" and any(r2 != r and amap.get(r2) == fb_ for r2 in amap)
                                 for r, fb_ in ((a, f1), (b, f2)))
                    if not shared:
                        continue
                out.append(((mid, name), {**b1, **b2}))
        # faces no other entity has first: sharing a split curve is the exception
        out.sort(key=lambda o: sum(1 for r, fc in o[1].items() if fc in amap.values()))
        return out

    def walk(left, amap, used, picked):
        if len(solutions) >= MAX_SOLUTIONS or work[0] > BUDGET:
            return
        if not left:
            solutions.append(([picked[i] for i in range(len(sw_edges))], amap))
            return
        best = None
        for i in left:
            opts = matches(i, amap, used)
            if not opts:
                return            # this branch can't name that edge
            if best is None or len(opts) < len(best[1]):
                best = (i, opts)
        i, opts = best
        rest = [j for j in left if j != i]
        for e, binds in opts:
            walk(rest, {**amap, **binds}, used | {e[1]}, {**picked, i: e})

    # restarts: each way of placing the most constrained edge is searched on its own budget,
    # so a wrong start that runs long can't starve the right one
    every_edge = list(range(len(sw_edges)))
    for k in known or [{}]:
        firsts = [(i, matches(i, dict(k), frozenset())) for i in every_edge]
        if any(not o for _i, o in firsts):
            continue
        i0, opts = min(firsts, key=lambda x: len(x[1]))
        for e, binds in opts:
            work[0] = 0
            walk([j for j in every_edge if j != i0], {**k, **binds}, frozenset({e[1]}), {i0: e})
            if len(solutions) >= MAX_SOLUTIONS:
                break
    # the same edges reached by different assignments are one answer, keeping the assignments
    groups: dict = {}
    for s, amap in solutions:
        key = frozenset(n for _m, n in s)
        if key not in groups:
            groups[key] = (s, [])
        if amap not in groups[key][1]:
            groups[key][1].append(amap)
    return list(groups.values())


def candidates(prefix: dict, fillet, feats: list, cli: str, tmp: str, known: list | None = None) -> list:
    """The edge sets the fillet `fillet` could round in the design `prefix` (everything before
    it), each with the assignments of SolidWorks faces that reach it. Smooth edges (an arc running on
    from a line) are no fillet's: they are left out."""
    raw: list = []
    sc = body_edges(prefix, cli, tmp, raw)
    if not sc:
        return []
    every = sc
    smooth = _smooth_pairs(prefix)
    sc = [e for e in sc if not (all(x[0] == "side" for x in e[0]) and
                                (e[0][0][1], frozenset((e[0][0][2], e[0][1][2]))) in smooth)]
    by_name = {f["name"]: f for f in prefix["features"]}
    design_id = {f.fid: by_name[f.name]["id"] for f in feats if f.name in by_name}
    sketches = {f["id"]: f for f in prefix["features"] if f.get("type") == "sketch"}
    curves = {}
    for f in prefix["features"]:
        sk = sketches.get(f.get("sketch")) if isinstance(f.get("sketch"), int) else None
        if sk:
            curves[f["id"]] = [c["id"] for c in sk["sketch"]["curves"] if not c.get("construction")]
    blends = {f["id"]: f["edge_names"] for f in prefix["features"] if f.get("type") == "fillet"}
    out = solve(fillet.edges, sc, design_id, curves, known, blends, fillet.edge_ends, every)
    def off_axis(m, p, d):
        w = [m[k] - p[k] for k in range(3)]
        t = sum(w[k] * d[k] for k in range(3))
        return math.sqrt(max(0.0, sum(w[k] * w[k] for k in range(3)) - t * t))
    # the edges its own faces in the part's solid round (each face a cylinder whose axis runs along
    # its edge, 1 to 3 radii from it): the nearest edge to each axis, tried first
    axes = getattr(fillet, "round_axes", None) or []
    if axes:
        got = []
        for p, d, r in axes:
            # (ties, a hole's two rims both a radius off: the one nearer the face's point along the axis)
            along = lambda m, p=p, d=d: abs(sum((m[k] - p[k]) * d[k] for k in range(3)))  # noqa: E731
            # a chamfer's cone: the edge it bevels lies at the cone's own radius (a hole's rim), not
            # the nearest edge (the hole's drill-point edge can be a hair nearer)
            cham = fillet.kind == "chamfer"
            score = (lambda o, r=r: abs(o - r)) if cham else (lambda o: o)  # noqa: E731
            # (a seam, one face meeting itself, is no edge to round)
            near = sorted(((off_axis(mid, p, d), mid, name) for mid, name in raw if len(_split(name or "")) == 2),
                          key=lambda x: (round(score(x[0]), 3), along(x[1])))
            near = [x for x in near if (abs(x[0] - r) <= 0.01 if cham else r * 0.999 <= x[0] <= 3 * r)]
            if not near:
                got = []
                break
            if (near[0][1], near[0][2]) not in got:
                got.append((near[0][1], near[0][2]))
        if got:
            out = [(got, [])] + [o for o in out if sorted(n for _m, n in o[0]) != sorted(n for _m, n in got)]
            return out
    # the edges on the lines the face tags give (the sharp edges it rounds), tried first
    lines = getattr(fillet, "edge_lines", None) or []
    if lines and all(ln is not None for ln in lines):
        got = []
        for (p, d) in lines:
            for _fc, mid, name in every:
                w = [mid[k] - p[k] for k in range(3)]
                t = sum(w[k] * d[k] for k in range(3))
                off = math.sqrt(max(0.0, sum(w[k] * w[k] for k in range(3)) - t * t))
                if off <= 1e-3 and (mid, name) not in got:
                    got.append((mid, name))
        if got and all(any(math.sqrt(max(0.0, sum((m[k] - p[k]) ** 2 for k in range(3)) - sum((m[k] - p[k]) * d[k] for k in range(3)) ** 2)) <= 1e-3
                               for m, _n in got) for p, d in lines):
            tagged = (got, [])
            out = [tagged] + [o for o in out if sorted(n for _m, n in o[0]) != sorted(n for _m, n in got)]
    return out


def _smooth_pairs(design: dict) -> set:
    """(extrude id, {curve, curve}) for curves of its sketch that meet tangentially."""
    out = set()
    sketches = {f["id"]: f["sketch"] for f in design["features"] if f.get("type") == "sketch"}
    for f in design["features"]:
        sk = sketches.get(f.get("sketch")) if isinstance(f.get("sketch"), int) else None
        if not sk:
            continue
        pts = [p["pos"] for p in sk["points"]]
        ends = {}
        for c in sk["curves"]:
            if c.get("construction") or c["type"] not in ("line", "arc"):
                continue
            for k in ("a", "b"):
                p = pts[c[k]]
                if c["type"] == "line":
                    q = pts[c["b" if k == "a" else "a"]]
                    t = (q[0] - p[0], q[1] - p[1])
                else:
                    o = pts[c["c"]]
                    t = (-(p[1] - o[1]), p[0] - o[0])
                ends.setdefault((round(p[0], 6), round(p[1], 6)), []).append((c["id"], t))
        for here in ends.values():
            for i, (c1, t1) in enumerate(here):
                for c2, t2 in here[i + 1:]:
                    n = (t1[0] ** 2 + t1[1] ** 2) ** 0.5 * (t2[0] ** 2 + t2[1] ** 2) ** 0.5
                    if n and abs(t1[0] * t2[1] - t1[1] * t2[0]) <= 1e-6 * n:
                        out.add((f["id"], frozenset((c1, c2))))
    return out
