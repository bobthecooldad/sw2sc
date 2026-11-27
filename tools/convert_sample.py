"""Run the plugin's converter (`convert_one`, the Rust build) on a sample of parts in parallel,
record each outcome, and compare with an earlier run.

    python tools/convert_sample.py LIST_OR_FOLDER OUT.jsonl [--n 200] [--seed 1] [--jobs 20] [--timeout 900] [--large-mb 250] [--memory-mb 8192] [--baseline OLD.jsonl] [--exe CONVERTER]
    Add --cycle to keep running, --cycles N for a bounded run, and --include PATH to pin a regression.

LIST_OR_FOLDER is a text file with one part path per line or a folder searched recursively.
Lock files are excluded; the same seed picks the same first sample. Cycles cover every path before
reshuffling and write OUT-cycle-NNNN.jsonl. With --baseline, cycles merge results without learning
new losses. Each result records expected versus delivered sketch dimensions; the summary prints
only totals. Exit code 1 when a part rebuilt in the baseline and doesn't now, or the converter
crashed on a part it didn't crash on before.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from feature_survey import parts as model_parts  # noqa: E402
from sw2sc import features  # noqa: E402
from sw2sc.swfile import SwFile  # noqa: E402
import process_limit  # noqa: E402
EXE = os.path.join(ROOT, "plugin", "target", "release", "examples", "convert_one" + (".exe" if os.name == "nt" else ""))


def paths_of(source: str) -> list[str]:
    if os.path.isdir(source):
        return list(model_parts([source]))
    return [ln.strip() for ln in open(source, encoding="utf-8") if ln.strip().lower().endswith(".sldprt")]


def sample_paths(paths: list[str], n: int, seed: int, cycle: int = 0, include=()) -> list[str]:
    """Randomized chunks covering every path before the next shuffle; pinned paths repeat."""
    included = list(dict.fromkeys(p for p in include if p in paths))
    rest = [p for p in paths if p not in included]
    slots = max(1, n - len(included))
    batches = max(1, (len(rest) + slots - 1) // slots)
    random.Random(seed + cycle // batches).shuffle(rest)
    start = (cycle % batches) * slots
    return included + rest[start:start + slots]


def dimension_coverage(feats, shown: dict, design: dict) -> dict:
    """Delivered sketch dimensions against current saved dimensions and those read from records.
    MOD-DIAM alone is metadata; once validated into a raw dimension it is expected too."""
    actual = {p.get("name") for p in design.get("params", [])}
    expected = set()
    for f in feats or []:
        if f.kind != "sketch" or not f.sketch:
            continue
        names = {d[0] for d in f.sketch.dims}
        names.update(nm for nm, text in shown.get(f.name, []) if "MOD-DIAM" not in text.upper())
        expected.update(features.param_name(f.name, nm) for nm in names)
    return {"expected": len(expected), "written": len(expected & actual), "missing": sorted(expected - actual)}


def run(path: str, timeout: int = 900, memory_mb: int = 8192) -> dict:
    t = time.time()
    dimensions = None
    try:
        with tempfile.TemporaryDirectory(prefix="sw2sc-sample-") as tmp:
            design_path = os.path.join(tmp, "design.solidcraft")
            r = process_limit.run([EXE, path, "--design-out", design_path], timeout=timeout, memory_mb=memory_mb)
            txt = r.stdout.strip()
            rep = json.loads(txt) if txt.startswith("{") else {"error": (txt or r.stderr)[-300:]}
            if os.path.isfile(design_path):
                try:
                    with open(design_path, encoding="utf-8") as fh:
                        design = json.load(fh)
                    sw = SwFile(path)
                    dimensions = dimension_coverage(features.read(sw), features._kw_sketch_dimensions(sw.xml("swXmlContents/KeyWords") or ""), design)
                except Exception as e:  # noqa: BLE001
                    dimensions = {"error": f"{type(e).__name__}: {e}"}
    except subprocess.TimeoutExpired:
        rep = {"error": f"timeout {timeout} s"}
    except Exception as e:  # noqa: BLE001
        rep = {"error": f"{type(e).__name__}: {e}"}
    return {"file": path, "seconds": round(time.time() - t, 1), "summary": rep.get("summary"), "error": rep.get("error"),
            "items": [(i["severity"], i["title"], i["message"][:120]) for i in rep.get("items", [])],
            "rebuild": (rep.get("details") or {}).get("rebuild"), "dimensions": dimensions}


def outcome(r: dict) -> str:
    if r.get("error"):
        return "crash" if "panicked" in r["error"] else "error"
    s = re.sub(r"^.*?: ", "", r.get("summary") or "")
    if s.startswith("rebuilt from"):
        return "rebuilt"
    if "didn't match" in s:
        return "no build" if "no build" in str((r.get("rebuild") or {}).get("closest")) else "built, no match"
    if "not every feature" in s:
        return "TBD"
    if "no feature history" in s:
        return "no history"
    return s[:50]


def merge_baseline(results_path: str, baseline_path: str) -> None:
    """Merge a cycle into its private per-file baseline without baselining away a new loss."""
    before = {}
    if os.path.exists(baseline_path):
        with open(baseline_path, encoding="utf-8") as fh:
            before = {r["file"]: r for r in map(json.loads, fh)}
    with open(results_path, encoding="utf-8") as fh:
        current = [json.loads(ln) for ln in fh]
    for result in current:
        old = before.get(result["file"])
        if old and ((outcome(old) == "rebuilt" and outcome(result) != "rebuilt") or
                    (outcome(result) == "crash" and outcome(old) != "crash")):
            continue
        before[result["file"]] = result
    os.makedirs(os.path.dirname(os.path.abspath(baseline_path)), exist_ok=True)
    with open(baseline_path, "w", encoding="utf-8") as fh:
        for result in before.values():
            fh.write(json.dumps(result) + "\n")


def split_large(paths, large_mb):
    if large_mb <= 0:
        return [], list(paths)
    limit = large_mb * 1024 * 1024
    large = [p for p in paths if os.path.getsize(p) >= limit]
    normal = [p for p in paths if os.path.getsize(p) < limit]
    return large, normal


def run_batch(paths, jobs, timeout, fh, results, memory_mb=8192):
    if not paths:
        return
    with ThreadPoolExecutor(jobs) as pool:
        for r in pool.map(lambda p: run(p, timeout, memory_mb), paths):
            fh.write(json.dumps(r) + "\n")
            fh.flush()
            results.append(r)


def run_once(a, out: str, seed: int, cycle: int = 0) -> int:
    paths = sample_paths(paths_of(a.list), a.n, seed, cycle, a.include)
    large, normal = split_large(paths, a.large_mb)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        results = []
        run_batch(large, 1, a.timeout, fh, results, a.memory_mb)
        run_batch(normal, a.jobs, a.timeout, fh, results, a.memory_mb)
        if len(results) % 10 == 0:
            print(f"{len(results)} of {len(paths)} complete", flush=True)
    now = {r["file"]: outcome(r) for r in results}
    count = collections.Counter(now.values())
    dimensions = [r["dimensions"] for r in results if isinstance(r.get("dimensions"), dict) and "expected" in r["dimensions"]]
    expected = sum(d["expected"] for d in dimensions)
    written = sum(d["written"] for d in dimensions)
    print(f"dimensions: {written} of {expected} retained; {sum('error' in r.get('dimensions', {}) for r in results if isinstance(r.get('dimensions'), dict))} coverage errors", flush=True)
    bad = []
    if a.baseline and os.path.exists(a.baseline):
        with open(a.baseline, encoding="utf-8") as fh:
            before = {json.loads(ln)["file"]: outcome(json.loads(ln)) for ln in fh}
        was = collections.Counter(before.get(f) for f in now)
        for k in sorted(set(count) | set(was) - {None}, key=lambda k: -count[k]):
            print(f"{was[k]:4d} -> {count[k]:4d}  {k}")
        bad = [f for f, o in now.items() if (before.get(f) == "rebuilt" and o != "rebuilt") or (o == "crash" and before.get(f) != "crash")]
        for f in bad:
            print(f"  lost: {before.get(f)} -> {now[f]}: part #{paths.index(f)}")
    else:
        for k, v in count.most_common():
            print(f"{v:4d}  {k}")
    return 1 if bad else 0


def main(argv=None) -> int:
    global EXE
    ap = argparse.ArgumentParser()
    ap.add_argument("list")
    ap.add_argument("out")
    ap.add_argument("--exe", default=EXE, help="converter executable; a copied binary avoids locking the build output")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=20)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--large-mb", type=int, default=250)
    ap.add_argument("--memory-mb", type=int, default=8192)
    ap.add_argument("--baseline")
    ap.add_argument("--include", action="append", default=[], help="pin a path in every cycle; repeat as needed")
    ap.add_argument("--cycle", action="store_true", help="keep covering shuffled chunks until stopped")
    ap.add_argument("--cycles", type=int, help="run this many cycles (also useful for a bounded check)")
    a = ap.parse_args(argv)
    EXE = os.path.abspath(a.exe)
    if a.cycles is not None and a.cycles < 1:
        ap.error("--cycles must be positive")
    if not a.cycle and a.cycles is None:
        return run_once(a, a.out, a.seed)
    status = 0
    cycle = 0
    while True:
        root, extension = os.path.splitext(a.out)
        out = f"{root}-cycle-{cycle:04d}{extension}"
        print(f"cycle {cycle}", flush=True)
        status |= run_once(a, out, a.seed, cycle)
        if a.baseline:
            merge_baseline(out, a.baseline)
        cycle += 1
        if a.cycles is not None and cycle >= a.cycles:
            return status


if __name__ == "__main__":
    sys.exit(main())
