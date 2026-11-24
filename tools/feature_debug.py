"""Show one part's decoded features and every rebuild attempt against its solid (F-006).

    python tools/feature_debug.py PART.SLDPRT
"""
import itertools
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sw2sc import features, solidcraft  # noqa: E402
from sw2sc.swfile import SwFile  # noqa: E402
from feature_check import evaluate, same  # noqa: E402

p = sys.argv[1]
if not os.path.isfile(p):  # a part name: look in the sample sets
    import glob
    roots = [r"C:\Solidworks to Solidcraft\samples", r"C:\Solidworks to Solidcraft\Solidworks Example Grabcad",
             os.path.expanduser(r"~\Documents")]
    hits = [h for r in roots for h in glob.glob(os.path.join(r, "**", p + ".SLDPRT"), recursive=True)]
    p = hits[0]
feats = features.read(SwFile(p))
for f in feats:
    if f.kind == "sketch":
        s = f.sketch
        print(f"sketch {f.name}: {len(s.points)} points, {len(s.lines)} lines, {len(s.arcs)} arcs, {len(s.circles)} circles;"
              f" plane: {s.plane_how}; {s.plane and [tuple(round(c, 3) for c in v) for v in s.plane[0]]}"
              f" at {s.plane and tuple(round(c * 1000, 3) for c in s.plane[1])}; loops {features.profile_loops(s)}; {s.problems}")
    else:
        print(f"{f.kind} {f.name}: depth {f.depth_mm}, sketch {f.profile} {f.reason}")
tmp = tempfile.mkdtemp(prefix="sw2sc-fd-")
ref_d, _ = solidcraft.convert(p)
solidcraft.write(ref_d, os.path.join(tmp, "ref.solidcraft"))
ref = evaluate(os.path.join(tmp, "ref.solidcraft"))
print("reference:", ref)
extr = [f for f in feats if f.kind in ("boss", "cut")]
for combo in itertools.product(["positive", "negative", "symmetric"], repeat=len(extr)):
    d = features.design("t", feats, {f.name: (c, None) for f, c in zip(extr, combo)})
    path = os.path.join(tmp, "f.solidcraft")
    json.dump(d, open(path, "w", encoding="utf-8"))
    got = evaluate(path)
    print(combo, "MATCH" if same(got, ref) else "", got and {k: (round(v, 3) if isinstance(v, float) else v) for k, v in got.items()})
print("designs in", tmp)
