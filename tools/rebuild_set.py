"""Rebuild every part in a folder (or list) from its feature tree, in parallel, and say which
match the part's own solid; with a baseline, which matched before and don't now.

    python tools/rebuild_set.py PARTS... [--jobs 20] [--out results.json] [--baseline old.json]

PARTS are files, folders (searched for .sldprt) or text files listing one path per line. Exit
code 1 when a part that matched in the baseline doesn't match now.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parts_of(items: list[str]) -> list[str]:
    out = []
    for it in items:
        if os.path.isdir(it):
            for r, _d, fs in os.walk(it):
                out += [os.path.join(r, f) for f in fs if f.lower().endswith(".sldprt")]
        elif it.lower().endswith(".sldprt"):
            out.append(it)
        else:
            out += [ln.strip() for ln in open(it, encoding="utf-8") if ln.strip().lower().endswith(".sldprt")]
    return sorted(set(out))


def one(path: str) -> dict:
    sys.path.insert(0, ROOT)
    from sw2sc import features, solidcraft, verify
    from sw2sc.swfile import SwFile
    t = time.time()
    try:
        feats = features.read(SwFile(path))
        ref, _ = solidcraft.convert(path, feature_tree=False)
        d = verify.rebuild(feats, ref, "t") if feats else None
        res = {"match": bool(d)}
    except Exception as e:  # noqa: BLE001
        res = {"match": False, "error": f"{type(e).__name__}: {e}"[:300]}
    res.update(file=path, seconds=round(time.time() - t, 1))
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("parts", nargs="+")
    ap.add_argument("--jobs", type=int, default=20)
    ap.add_argument("--out")
    ap.add_argument("--baseline")
    a = ap.parse_args(argv)
    paths = parts_of(a.parts)
    with ProcessPoolExecutor(max(1, min(a.jobs, len(paths)))) as ex:
        results = list(ex.map(one, paths))
    for r in results:
        print(f"{r['seconds']:6.0f}s {'MATCH' if r['match'] else 'no   '} {os.path.basename(r['file'])}"
              + (f"  ({r['error']})" if r.get("error") else ""))
    n = sum(r["match"] for r in results)
    print(f"{n} of {len(results)} rebuild")
    if a.out:
        json.dump(results, open(a.out, "w", encoding="utf-8"), indent=1)
    lost = []
    if a.baseline and os.path.exists(a.baseline):
        before = {os.path.basename(r["file"]): r["match"] for r in json.load(open(a.baseline, encoding="utf-8"))}
        now = {os.path.basename(r["file"]): r["match"] for r in results}
        lost = sorted(k for k, v in before.items() if v and not now.get(k))
        gained = sorted(k for k, v in now.items() if v and not before.get(k))
        print(f"against the baseline: {len(gained)} more, {len(lost)} lost" + (f": {', '.join(lost)}" if lost else ""))
    return 1 if lost else 0


if __name__ == "__main__":
    sys.exit(main())
