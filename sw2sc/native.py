"""SolidWorks sketch features written as SolidCraft's own (F-038).

An Offset Entities in SolidWorks is one dimension holding a whole loop. SolidCraft has the same
thing, an associative offset (`sketch.offset`: one offset distance dimension, outputs that
follow their sources). Its stored form (an offset chain with a topology of roles) is made by
SolidCraft itself: the design is written with the offset loop as plain curves held by
constraints (features.sketch_constraints), then solidcraft-cli replaces that loop with a native
offset of its partner loop, driven by the same parameter. The offset is kept only when its
outputs are the loop SolidWorks drew; the side is tried both ways. The extrudes that used the
loop are pointed at the outputs.
"""
from __future__ import annotations

import copy
import io
import json
import math
import os
import shutil
import subprocess
import tempfile
import zipfile

TOL = 1e-6  # mm


def offsets(built: dict, feats: list, cli: str) -> dict | None:
    """`built` with every offset loop as a native SolidCraft offset, or None if any can't be."""
    sketches = {f.name: f.sketch for f in feats if f.kind == "sketch" and f.sketch.offsets}
    if not sketches:
        return None
    doc = copy.deepcopy(built)
    tmp = tempfile.mkdtemp(prefix="sw2sc-offset-")
    try:
        for g in [f for f in doc["features"] if f.get("type") == "sketch" and f["name"] in sketches]:
            for off in sketches[g["name"]].offsets:
                doc = _one(doc, g["name"], off, cli, tmp)
                if doc is None:
                    return None
        return doc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _geometry(sk: dict, cid: str):
    """A curve's shape for matching: ("line", {end, end}) or ("arc", centre, radius, {ends})."""
    pts = [p["pos"] for p in sk["points"]]
    c = next((c for c in sk["curves"] if c["id"] == cid), None)
    if c is None:
        return None
    if c["type"] == "line":
        return ("line", pts[c["a"]], pts[c["b"]])
    if c["type"] == "arc":
        return ("arc", pts[c["c"]], math.dist(pts[c["a"]], pts[c["c"]]), pts[c["a"]], pts[c["b"]])
    if c["type"] == "circle":
        return ("circle", pts[c["c"]], c["r"])
    return None


def _inspected(c: dict):
    if c["type"] == "line":
        return ("line", c["start_at"], c["end_at"])
    if c["type"] == "arc":
        return ("arc", c["center_at"], c["radius"], c["start_at"], c["end_at"])
    if c["type"] == "circle":
        return ("circle", c["center_at"], c["radius"])
    return None


def _same(a, b) -> bool:
    if not a or not b or a[0] != b[0]:
        return False
    close = lambda p, q: math.dist(p, q) < TOL  # noqa: E731
    if a[0] == "line":
        return (close(a[1], b[1]) and close(a[2], b[2])) or (close(a[1], b[2]) and close(a[2], b[1]))
    if not close(a[1], b[1]) or abs(a[2] - b[2]) > TOL:
        return False
    if a[0] == "arc":
        return (close(a[3], b[3]) and close(a[4], b[4])) or (close(a[3], b[4]) and close(a[4], b[3]))
    return True


def _one(doc: dict, sketch: str, off: dict, cli: str, tmp: str) -> dict | None:
    g = next(f for f in doc["features"] if f.get("type") == "sketch" and f["name"] == sketch)
    sk = g["sketch"]
    old = {cid: _geometry(sk, cid) for cid in off["loop"]}
    if any(v is None for v in old.values()):
        return None
    base = copy.deepcopy(doc)
    # the constraints standing in for the offset and its parameter go; SolidCraft makes its own
    bsk = next(f for f in base["features"] if f.get("type") == "sketch" and f["name"] == sketch)["sketch"]
    bsk["constraints"] = [c for c in bsk["constraints"] if c.get("param") != off["param"]]
    base["params"] = [p for p in base.get("params", []) if p["name"] != off["param"]]
    src = os.path.join(tmp, "in.solidcraft")
    with open(src, "w", encoding="utf-8") as fh:
        json.dump(base, fh)
    for flip in (False, True):
        script, out, saved = (os.path.join(tmp, n) for n in ("s.json", "r.json", "out.sc"))
        params = {"curves": [off["sources"][0]], "distance": repr(off["value"]), "param": off["param"], "chain": True}
        if flip:
            params["flip"] = True
        with open(script, "w", encoding="utf-8") as fh:
            json.dump({"commands": [
                {"command": "sketch.edit", "params": {"sketch": sketch}},
                {"command": "sketch.delete", "params": {"entities": off["loop"]}},
                {"command": "sketch.offset", "params": params},
                {"command": "sketch.inspect", "params": {}},
                {"command": "sketch.finish", "params": {}}]}, fh)
        for f in (out, saved):
            if os.path.exists(f):
                os.remove(f)
        try:
            subprocess.run([cli, "run", script, "--in", src, "--results", "--allow-errors", "--save", saved,
                            "--json-out", out], capture_output=True, timeout=300)
            res = json.load(open(out, encoding="utf-8"))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return None
        if not isinstance(res, list) or len(res) < 4 or not os.path.isfile(saved):
            continue
        made, ins = res[2], res[3]
        if not isinstance(made, dict) or not made.get("param") or ins.get("status") != "solved":
            continue
        shapes = {c["id"]: _inspected(c) for c in ins.get("curves", []) if c["id"] in made.get("curves", [])}
        rename = {}
        for cid, shape in old.items():
            hit = [n for n, s2 in shapes.items() if _same(shape, s2) and n not in rename.values()]
            if not hit:
                break
            rename[cid] = hit[0]
        if len(rename) != len(old) or len(shapes) != len(old):
            continue   # not the loop SolidWorks drew: the other side
        raw = open(saved, "rb").read()
        new = json.loads(raw) if raw[:1] == b"{" else json.loads(zipfile.ZipFile(io.BytesIO(raw)).read("document.json"))
        for f in new["features"]:   # extrudes and revolves that used the loop now use the outputs
            for loop in (f.get("profiles") or {}).get("loops", []) or []:
                loop[:] = [rename.get(c, c) for c in loop]
        return new
    return None
