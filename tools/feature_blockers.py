"""Which single fix would unlock the most parts (F-006): for every part read, the kinds of
thing still blocking a full rebuild; prints how many parts are blocked by one kind only."""
import argparse
import collections
from contextlib import nullcontext
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sw2sc import features  # noqa: E402
from sw2sc.swfile import SwFile  # noqa: E402
from feature_survey import parts  # noqa: E402
import process_limit  # noqa: E402


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


def read_one(path, timeout=300, memory_mb=2048):
    args = [sys.executable, os.path.abspath(__file__), "--one", path]
    try:
        result = process_limit.run(args, timeout=timeout, memory_mb=memory_mb)
    except Exception:  # noqa: BLE001
        return None
    if "memory limit" in result.stderr:
        return {"read memory limit"}
    if "timeout " in result.stderr:
        return {"read timeout"}
    try:
        kinds = json.loads(result.stdout)
    except ValueError:
        return None
    return None if kinds is None else set(kinds)


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


def scan(paths, jobs=8, timeout=300, memory_mb=2048, out=""):
    paths = list(paths)
    groups = []
    with open(out, "w", encoding="utf-8") if out else nullcontext(None) as fh:
        with ThreadPoolExecutor(max_workers=max(1, min(int(jobs), len(paths)))) as pool:
            pending = [pool.submit(read_one, path, timeout, memory_mb) for path in paths]
            for n, future in enumerate(as_completed(pending), 1):
                kinds = future.result()
                groups.append(kinds)
                if fh:
                    fh.write(json.dumps({"kinds": None if kinds is None else sorted(kinds)}) + "\n")
                    fh.flush()
                if n % 10 == 0 or n == len(paths):
                    print(f"{n} of {len(paths)} blocker reads complete", file=sys.stderr, flush=True)
    return summarize(groups)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("folders", nargs="+")
    parser.add_argument("--one", action="store_true")
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--memory-mb", type=int, default=2048)
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)
    if args.one:
        kinds = blocker_kinds(args.folders[0])
        print(json.dumps(None if kinds is None else sorted(kinds)))
        return
    only, anyc = scan(parts(args.folders), args.jobs, args.timeout, args.memory_mb, args.out)
    print("parts blocked by one kind only:")
    for kind, count in sorted(only.items(), key=lambda item: (-item[1], item[0]))[:20]:
        print(f"  {count:4d}  {kind}")
    print("parts blocked by each kind (any):")
    for kind, count in sorted(anyc.items(), key=lambda item: (-item[1], item[0]))[:20]:
        print(f"  {count:4d}  {kind}")


if __name__ == "__main__":
    main()
