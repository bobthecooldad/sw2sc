"""How much of the feature trees sw2sc.features decodes, over some folders (F-006).

    python tools/feature_stats.py FOLDER [FOLDER...]

Counts sketches (plane found or not, by how; sketch problems), extrudes (depth read or not)
and features still TBD by class. Read only.
"""
from __future__ import annotations

import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sw2sc import features  # noqa: E402
from sw2sc.swfile import SwFile  # noqa: E402
from feature_survey import parts  # noqa: E402


def main(argv=None) -> int:
    c = collections.Counter()
    tbd = collections.Counter()
    for p in parts(sys.argv[1:] if argv is None else argv):
        try:
            feats = features.read(SwFile(p))
        except Exception as e:  # noqa: BLE001
            c["parts: reader error " + type(e).__name__] += 1
            continue
        if feats is None:
            c["parts: pre-2015, not numbered"] += 1
            continue
        c["parts: read"] += 1
        for f in feats:
            if f.kind == "sketch":
                s = f.sketch
                c["sketches"] += 1
                c["sketch plane: " + (re.sub(r"\d+", "N", s.plane_how) if s.plane else "MISSING (" + s.plane_how + ")")] += 1
                c["sketches with a problem"] += bool(s.problems)
                for pr in s.problems:
                    c["sketch problem: " + re.sub(r"\d+", "N", pr)] += 1
            elif f.kind in ("boss", "cut"):
                c["extrudes"] += 1
                c["extrude depth " + ("read" if f.depth_mm is not None else "MISSING")] += 1
            else:
                tbd[f.cls] += 1
    for k, n in sorted(c.items()):
        print(f"{n:6d}  {k}")
    print("TBD features by class:", tbd.most_common(15))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
