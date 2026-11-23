"""Which single fix would unlock the most parts (F-006): for every part read, the kinds of
thing still blocking a full rebuild; prints how many parts are blocked by one kind only."""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sw2sc import features  # noqa: E402
from sw2sc.swfile import SwFile  # noqa: E402
from feature_survey import parts  # noqa: E402

only = collections.Counter()
anyc = collections.Counter()
for p in parts(sys.argv[1:]):
    try:
        feats = features.read(SwFile(p))
    except Exception:  # noqa: BLE001
        continue
    if feats is None:
        kinds = {"pre-2015 numbering"}
    else:
        kinds = set()
        for f in feats:
            if f.kind == "tbd":
                kinds.add("feature " + f.cls)
            elif f.kind == "sketch":
                if f.sketch.plane is None:
                    kinds.add("sketch plane")
                for pr in f.sketch.problems:
                    kinds.add("sketch: " + ("line ends" if pr.startswith("line") else "arc centre" if "centre" in pr else pr))
            elif f.kind in ("boss", "cut") and f.depth_mm is None and not f.through_all:
                kinds.add("extrude depth")
        if not any(f.kind in ("boss", "cut", "import", "revolve", "revcut") for f in feats):
            kinds.add("no solid feature")
    for k in kinds:
        anyc[k] += 1
    if len(kinds) == 1:
        only[next(iter(kinds))] += 1
    elif not kinds:
        only["(nothing: fully decoded)"] += 1
print("parts blocked by one kind only:")
for k, n in only.most_common(20):
    print(f"  {n:4d}  {k}")
print("parts blocked by each kind (any):")
for k, n in anyc.most_common(20):
    print(f"  {n:4d}  {k}")
