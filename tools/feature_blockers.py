"""Which single fix would unlock the most parts (F-006): for every part read, the kinds of
thing still blocking a full rebuild; prints how many parts are blocked by one kind only."""
import argparse
import collections
import os
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sw2sc import features  # noqa: E402
from sw2sc.swfile import SwFile  # noqa: E402
from feature_survey import parts  # noqa: E402


def blocker_kinds(path):
    try:
        feats = features.read(SwFile(path))
    except Exception:  # noqa: BLE001
        return None
    if feats is None:
        return {"pre-2015 numbering"}
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
    return kinds


def summarize(groups):
    only = collections.Counter()
    anyc = collections.Counter()
    for kinds in groups:
        if kinds is None:
            continue
        for kind in kinds:
            anyc[kind] += 1
        if len(kinds) == 1:
            only[next(iter(kinds))] += 1
        elif not kinds:
            only["(nothing: fully decoded)"] += 1
    return only, anyc


def scan(paths, jobs=8):
    paths = list(paths)
    if not paths:
        return summarize([])
    workers = max(1, min(int(jobs), len(paths)))
    if workers == 1:
        groups = map(blocker_kinds, paths)
        return summarize(groups)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return summarize(pool.map(blocker_kinds, paths))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("folders", nargs="+")
    parser.add_argument("--jobs", type=int, default=8)
    args = parser.parse_args(argv)
    only, anyc = scan(parts(args.folders), args.jobs)
    print("parts blocked by one kind only:")
    for kind, count in only.most_common(20):
        print(f"  {count:4d}  {kind}")
    print("parts blocked by each kind (any):")
    for kind, count in anyc.most_common(20):
        print(f"  {count:4d}  {kind}")


if __name__ == "__main__":
    main()
