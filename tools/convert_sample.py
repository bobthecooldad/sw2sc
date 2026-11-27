"""Run the plugin's converter (`convert_one`, the Rust build) on a sample of parts in parallel,
record each outcome, and compare with an earlier run.

    python tools/convert_sample.py LIST_OR_FOLDER OUT.jsonl [--n 200] [--seed 1] [--jobs 20] [--timeout 900] [--large-mb 250] [--memory-mb 8192] [--baseline OLD.jsonl]

LIST_OR_FOLDER is a text file with one part path per line or a folder searched recursively.
Lock files are excluded; the same seed picks the same sample. Exit
code 1 when a part rebuilt in the baseline and doesn't now, or the converter crashed on a part it
didn't crash on before.
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
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from feature_survey import parts as model_parts  # noqa: E402
import process_limit  # noqa: E402
EXE = os.path.join(ROOT, "plugin", "target", "release", "examples", "convert_one" + (".exe" if os.name == "nt" else ""))


def paths_of(source: str) -> list[str]:
    if os.path.isdir(source):
        return list(model_parts([source]))
    return [ln.strip() for ln in open(source, encoding="utf-8") if ln.strip().lower().endswith(".sldprt")]


def run(path: str, timeout: int = 900, memory_mb: int = 8192) -> dict:
    t = time.time()
    try:
        r = process_limit.run([EXE, path], timeout=timeout, memory_mb=memory_mb)
        txt = r.stdout.strip()
        rep = json.loads(txt) if txt.startswith("{") else {"error": (txt or r.stderr)[-300:]}
    except subprocess.TimeoutExpired:
        rep = {"error": f"timeout {timeout} s"}
    except Exception as e:  # noqa: BLE001
        rep = {"error": f"{type(e).__name__}: {e}"}
    return {"file": path, "seconds": round(time.time() - t, 1), "summary": rep.get("summary"), "error": rep.get("error"),
            "items": [(i["severity"], i["title"], i["message"][:120]) for i in rep.get("items", [])],
            "rebuild": (rep.get("details") or {}).get("rebuild")}


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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("list")
    ap.add_argument("out")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=20)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--large-mb", type=int, default=250)
    ap.add_argument("--memory-mb", type=int, default=8192)
    ap.add_argument("--baseline")
    a = ap.parse_args(argv)
    paths = paths_of(a.list)
    random.Random(a.seed).shuffle(paths)
    paths = paths[:a.n]
    large, normal = split_large(paths, a.large_mb)
    with open(a.out, "w", encoding="utf-8") as fh:
        results = []
        run_batch(large, 1, a.timeout, fh, results, a.memory_mb)
        run_batch(normal, a.jobs, a.timeout, fh, results, a.memory_mb)
        if len(results) % 10 == 0:
            print(f"{len(results)} of {len(paths)} complete", flush=True)
    now = {r["file"]: outcome(r) for r in results}
    count = collections.Counter(now.values())
    bad = []
    if a.baseline and os.path.exists(a.baseline):
        before = {json.loads(ln)["file"]: outcome(json.loads(ln)) for ln in open(a.baseline, encoding="utf-8")}
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


if __name__ == "__main__":
    sys.exit(main())
