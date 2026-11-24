"""Run the plugin's converter (`convert_one`, the Rust build) on a sample of parts in parallel,
record each outcome, and compare with an earlier run.

    python tools/convert_sample.py LIST OUT.jsonl [--n 200] [--seed 1] [--jobs 20] [--baseline OLD.jsonl]

LIST is a text file with one part path per line; the same seed picks the same sample. Exit
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
EXE = os.path.join(ROOT, "plugin", "target", "release", "examples", "convert_one" + (".exe" if os.name == "nt" else ""))


def run(path: str) -> dict:
    t = time.time()
    try:
        r = subprocess.run([EXE, path], capture_output=True, text=True, encoding="utf-8", timeout=900)
        txt = r.stdout.strip()
        rep = json.loads(txt) if txt.startswith("{") else {"error": (txt or r.stderr)[-300:]}
    except subprocess.TimeoutExpired:
        rep = {"error": "timeout 900 s"}
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("list")
    ap.add_argument("out")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=20)
    ap.add_argument("--baseline")
    a = ap.parse_args(argv)
    paths = [ln.strip() for ln in open(a.list, encoding="utf-8") if ln.strip().lower().endswith(".sldprt")]
    random.Random(a.seed).shuffle(paths)
    paths = paths[:a.n]
    with ThreadPoolExecutor(a.jobs) as pool, open(a.out, "w", encoding="utf-8") as fh:
        results = []
        for r in pool.map(run, paths):
            fh.write(json.dumps(r) + "\n")
            fh.flush()
            results.append(r)
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
