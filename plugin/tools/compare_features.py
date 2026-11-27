"""Compare the Rust port's feature reading with the Python reader's on every sample part."""
import glob
import json
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from sw2sc import features  # noqa: E402
from sw2sc.swfile import SwFile  # noqa: E402

EXE = os.path.join(os.path.dirname(HERE), "target", os.environ.get("PROFILE", "debug"), "examples", "dump_features.exe")


def face(f):
    return [f[0], f[1], f[2]] if f else None


def frame(fr):
    (x, y, n), t = fr
    return [[list(x), list(y), list(n)], list(t)]


def py_feature(f):
    s = f.sketch
    sk = None if s is None else {
        "name": s.name, "offset": s.offset, "end": s.end,
        "points": [[k, v[0], v[1]] for k, v in s.points.items()],
        "lines": [list(x) for x in s.lines], "construction": sorted(s.construction),
        "alt_centres": [[k, v[0], v[1]] for k, v in s.alt_centres.items()],
        "dropped": list(s.dropped), "point_flags": [[k, v] for k, v in s.point_flags.items()],
        "region": [list(x) for x in s.region], "chain": list(s.chain), "arcs": [list(a) for a in s.arcs],
        "circles": [list(c) for c in s.circles],
        "planes": [[frame((p[0], p[1])), p[2]] for p in s.planes], "problems": list(s.problems),
        "curve_of": [[k[0], k[1], v] for k, v in s.curve_of.items()],
        "dims": [[d[0], d[1], d[2], [list(h) for h in d[3]]] for d in s.dims],
        "relations": [[r[0], [[list(h) for h in g] for g in r[1]]] for r in s.relations],
        "used": s.used,
    }
    return {
        "kind": f.kind, "name": f.name, "offset": f.offset, "cls": f.cls, "sketch": sk,
        "depth_mm": f.depth_mm, "profile": f.profile, "reason": f.reason, "frame": frame(f.frame) if f.frame else None,
        "through_all": f.through_all, "mid_plane": f.mid_plane, "angle_deg": f.angle_deg, "fid": f.fid, "radius_mm": f.radius_mm,
        "chamfer_deg": f.chamfer_deg, "chamfer_mm2": f.chamfer_mm2, "hole": dict(f.hole), "alt_kind": f.alt_kind, "from_face": f.from_face,
        "edge_lines": f.edge_lines, "round_axes": f.round_axes,
        "mirror_face": face(f.mirror_face), "mirror_planes": [frame(p) for p in f.mirror_planes],
        "thread": dict(f.thread), "pattern": dict(f.pattern), "thin_mm": f.thin_mm, "dome_mm": f.dome_mm, "path": f.path, "translate": f.translate, "rib": [f.rib["origin"], f.rib["x"], f.rib["y"], f.rib["chain"]] if f.rib else None,
        "scale": list(f.scale) if f.scale else None,
        "draft_deg": f.draft_deg, "move_mm": f.move_mm,
        "edges": [[face(a), face(b)] for a, b in f.edges], "edge_ends": [[face(a), face(b)] for a, b in f.edge_ends],
    }


def diff(a, b, path=""):
    num = (int, float)
    if isinstance(a, num) and isinstance(b, num) and not isinstance(a, bool) and not isinstance(b, bool):
        if a == b or (math.isnan(a) and math.isnan(b)) or abs(a - b) <= 1e-9 * max(1.0, abs(a)):
            return None
        return f"{path}: {a!r} != {b!r}"
    if isinstance(a, dict) and isinstance(b, dict):
        for k in list(a) + [k for k in b if k not in a]:
            if k not in a or k not in b:
                return f"{path}.{k}: missing on one side ({a.get(k)!r} / {b.get(k)!r})"
            d = diff(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            return f"{path}: length {len(a)} != {len(b)}: {str(a)[:300]} / {str(b)[:300]}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = diff(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    return None if a == b else f"{path}: {a!r} != {b!r}"


def main():
    roots = sys.argv[1:]
    files = sorted({p for r in roots for ext in ("SLDPRT", "sldprt")
                    for p in glob.glob(os.path.join(r, "**", "*." + ext), recursive=True)})
    rust = {}
    for i in range(0, len(files), 40):
        out = subprocess.run([EXE] + files[i:i + 40], capture_output=True, text=True, encoding="utf-8")
        for line in out.stdout.splitlines():
            d = json.loads(line)
            rust[d["file"]] = d
        if out.returncode:
            print("rust failed on a batch:", out.stderr[-1500:])
    bad = 0
    for p in files:
        try:
            fs = features.read(SwFile(p))
            py = None if fs is None else [py_feature(f) for f in fs]
        except Exception as e:  # noqa: BLE001
            py = f"error: {e}"
        r = rust.get(p)
        if r is None:
            d = "no rust output"
        elif isinstance(py, str):
            d = None if "error" in r else f"python {py}"
        else:
            d = diff(py, r.get("features"), "")
        if d:
            bad += 1
            if bad <= 12:
                print("DIFF", os.path.basename(p), d[:500])
    print("files", len(files), "differ", bad)


if __name__ == "__main__":
    main()
