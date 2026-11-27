"""Which single fix would unlock the most parts (F-006): for every part read, the kinds of
thing still blocking a full rebuild; prints how many parts are blocked by one kind only."""
import argparse
import collections
import copy
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


def dimension_kinds(sw, feats) -> set:
    """Dimension losses by raw record class, including saved dimensions never read and dimensions
    dropped while a shared sketch is filtered for a feature. No geometry evaluation is done."""
    shown = features._kw_sketch_dimensions(sw.xml("swXmlContents/KeyWords") or "")
    kinds = set()
    for feature in feats or []:
        if feature.kind != "sketch" or not feature.sketch:
            continue
        sk = feature.sketch
        raw = {d[0] for d in sk.dims}
        for name, text in shown.get(sk.name, []):
            if "MOD-DIAM" not in text.upper() and name not in raw:
                kinds.add("dimension record unread")
        uses = [f for f in feats if f.profile == sk.name and f.selected_loops is not None]
        for use in uses or [None]:
            selected = features.select_sketch_loops(sk, use.selected_loops) if use else copy.deepcopy(sk)
            if not selected.planes:
                continue
            try:
                features.sketch_feature(selected, 1)
            except Exception:  # noqa: BLE001
                kinds.add("dimension writer error")
                continue
            written = {p["name"] for p in selected.params}
            for name, cls, _value, _handles in sk.dims:
                if features.param_name(selected.name, name) not in written:
                    kinds.add("dimension " + cls)
    return kinds


def blocker_kinds(path, dimensions_only=False):
    try:
        sw = SwFile(path)
        feats = features.read(sw)
        if dimensions_only:
            return dimension_kinds(sw, feats)
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


def read_one(path, timeout=300, memory_mb=2048, dimensions_only=False):
    args = [sys.executable, os.path.abspath(__file__), "--one"]
    if dimensions_only:
        args.append("--dimensions-only")
    args.append(path)
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


def summarize(groups, dimensions_only=False):
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
            only["(nothing: no detected dimension loss)" if dimensions_only else "(nothing: fully decoded)"] += 1
    return only, anyc


def scan(paths, jobs=20, timeout=300, memory_mb=2048, out="", dimensions_only=False):
    paths = list(paths)
    groups = []
    with open(out, "w", encoding="utf-8") if out else nullcontext(None) as fh:
        with ThreadPoolExecutor(max_workers=max(1, min(int(jobs), len(paths)))) as pool:
            pending = [pool.submit(read_one, path, timeout, memory_mb, dimensions_only) for path in paths]
            for n, future in enumerate(as_completed(pending), 1):
                kinds = future.result()
                groups.append(kinds)
                if fh:
                    fh.write(json.dumps({"kinds": None if kinds is None else sorted(kinds)}) + "\n")
                    fh.flush()
                if n % 10 == 0 or n == len(paths):
                    print(f"{n} of {len(paths)} blocker reads complete", file=sys.stderr, flush=True)
    return summarize(groups, dimensions_only)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("folders", nargs="+")
    parser.add_argument("--one", action="store_true")
    parser.add_argument("--dimensions-only", action="store_true")
    parser.add_argument("--jobs", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--memory-mb", type=int, default=2048)
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)
    if args.one:
        kinds = blocker_kinds(args.folders[0], args.dimensions_only)
        print(json.dumps(None if kinds is None else sorted(kinds)))
        return
    only, anyc = scan(parts(args.folders), args.jobs, args.timeout, args.memory_mb, args.out, args.dimensions_only)
    print("parts with one dimension blocker only:" if args.dimensions_only else "parts blocked by one kind only:")
    for kind, count in sorted(only.items(), key=lambda item: (-item[1], item[0]))[:20]:
        print(f"  {count:4d}  {kind}")
    print("parts with each dimension blocker (any):" if args.dimensions_only else "parts blocked by each kind (any):")
    for kind, count in sorted(anyc.items(), key=lambda item: (-item[1], item[0]))[:20]:
        print(f"  {count:4d}  {kind}")


if __name__ == "__main__":
    main()
