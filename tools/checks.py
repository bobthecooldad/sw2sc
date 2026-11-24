"""A check queue that runs on its own: every new commit on a branch gets the full check suite, one
job at a time, in a checkout of its own, with a report per commit. While the queue is empty the
long jobs (a big sample run) are done for the latest commit.

    python tools/checks.py watch [--branch dev]     # leave running: queue each new commit, run the queue
    python tools/checks.py suite REV [--long]       # queue the suite for one commit now
    python tools/checks.py status                   # the queue and the latest reports

Run it from a copy outside the checkout you edit (`SW2SC_REPO` names the repository). Everything it keeps (the queue, the checkout, the reports, baselines) is under `SW2SC_CHECKS`,
or `~/.sw2sc-checks`, never in the repository: reports name parts. Which parts it checks is in
`checks.json` in the private folder (`SW2SC_PRIVATE`, or `~/.sw2sc-private`):

    {
      "parity_roots": ["folders of parts the Rust and Python readers must read the same"],
      "design_diffs_ok": 2,                     # accepted one-line STEP rounding differences
      "samples": "folder holding samples/ and 'Solidworks Example Grabcad/' (for the tests)",
      "regression": ["folders or list files of parts that rebuild"],
      "sample_list": "a list file of parts for the long sample run", "sample_n": 200
    }

A step that fails doesn't stop the others; the report says which passed. Regressions are judged
against the baseline of the last commit whose suite passed, which then becomes the baseline.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time

# the repository whose branch is watched (a copy of this script can run from anywhere)
ROOT = os.environ.get("SW2SC_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.environ.get("SW2SC_CHECKS") or os.path.join(os.path.expanduser("~"), ".sw2sc-checks")
PRIVATE = os.environ.get("SW2SC_PRIVATE") or os.path.join(os.path.expanduser("~"), ".sw2sc-private")
QUEUE, REPORTS, BASE, WT = (os.path.join(HOME, d) for d in ("queue", "reports", "baseline", "checkout"))
PY = sys.executable


def now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def git(*args, cwd=ROOT) -> str:
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, check=True).stdout.strip()


def config() -> dict:
    p = os.path.join(PRIVATE, "checks.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}


def enqueue(rev: str, long: bool, coalesce: bool = True) -> None:
    """Queue the suite for `rev` (a full hash). With `coalesce`, an earlier commit's suite still
    waiting is dropped: only the newest is worth checking."""
    os.makedirs(QUEUE, exist_ok=True)
    if coalesce:
        for f in os.listdir(QUEUE):
            job = json.load(open(os.path.join(QUEUE, f), encoding="utf-8"))
            if job["rev"] != rev and not job.get("pinned"):
                os.remove(os.path.join(QUEUE, f))
    name = f"{time.strftime('%Y%m%d-%H%M%S')}-{rev[:8]}{'-long' if long else ''}.json"
    json.dump({"rev": rev, "long": long, "queued": now(), "pinned": not coalesce},
              open(os.path.join(QUEUE, name), "w", encoding="utf-8"))
    print(f"{now()} queued {rev[:8]}{' (with the long run)' if long else ''}")


def checkout(rev: str) -> str:
    """A checkout of `rev` of its own (a git worktree), with the sample folders linked in."""
    if not os.path.isdir(WT):
        os.makedirs(HOME, exist_ok=True)
        git("worktree", "add", "--detach", WT, rev)
    git("checkout", "--detach", "--force", rev, cwd=WT)
    git("clean", "-fdq", "-e", "plugin/target", "-e", "samples", "-e", "Solidworks Example Grabcad", cwd=WT)
    src = config().get("samples")
    for name in ("samples", "Solidworks Example Grabcad"):
        link, target = os.path.join(WT, name), os.path.join(src or "", name)
        if src and os.path.isdir(target) and not os.path.exists(link):
            if os.name == "nt":
                subprocess.run(["cmd", "/c", "mklink", "/J", link, target], capture_output=True)
            else:
                os.symlink(target, link)
    return WT


def step(log, title: str, cmd: list[str], cwd: str, env=None, ok=None, timeout=4 * 3600) -> tuple[bool, str]:
    """Run one step, its output into the log; `ok(output, code)` judges it (default: exit 0)."""
    log.write(f"\n### {title}\n\n```\n$ {' '.join(cmd)}\n")
    log.flush()
    t = time.time()
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=dict(os.environ, **(env or {})), timeout=timeout)
        out, code = (r.stdout + r.stderr), r.returncode
    except subprocess.TimeoutExpired:
        out, code = "timed out", -1
    tail = "\n".join(out.strip().splitlines()[-40:])
    log.write(tail + f"\n```\n({time.time() - t:.0f} s)\n")
    log.flush()
    good = ok(out, code) if ok else code == 0
    last = next((ln for ln in reversed(out.strip().splitlines()) if ln.strip()), "")
    return good, last[:160]


def run_suite(job: dict) -> bool:
    cfg = config()
    rev, long = job["rev"], job.get("long")
    wt = checkout(rev)
    os.makedirs(REPORTS, exist_ok=True)
    os.makedirs(BASE, exist_ok=True)
    subject = git("log", "-1", "--format=%s", rev)
    path = os.path.join(REPORTS, f"{time.strftime('%Y%m%d-%H%M%S')}-{rev[:8]}.md")
    results = []
    with open(path, "w", encoding="utf-8") as log:
        log.write(f"# Checks for {rev[:8]}: {subject}\n\nstarted {now()}\n")
        plugin = os.path.join(wt, "plugin")
        rel = {"PROFILE": "release"}
        results.append(("build", *step(log, "Build", ["cargo", "build", "--release", "-j", str(os.cpu_count() or 4),
                                                           "-p", "sw2sc-core", "--examples"], plugin)))
        roots = cfg.get("parity_roots", [])
        if roots:
            results.append(("parity: features", *step(
                log, "Rust and Python read the same", [PY, "-X", "utf8", "plugin/tools/compare_features.py", *roots], wt, rel,
                ok=lambda o, c: c == 0 and re.search(r"differ 0\b", o) is not None)))
            allowed = int(cfg.get("design_diffs_ok", 0))
            results.append(("parity: designs", *step(
                log, "Rust and Python write the same designs", [PY, "-X", "utf8", "plugin/tools/compare_designs.py", *roots], wt, rel,
                ok=lambda o, c: (m := re.search(r"differ (\d+)\b", o)) is not None and int(m.group(1)) <= allowed)))
        results.append(("Python tests", *step(log, "Python tests", [PY, "-m", "unittest", "discover", "-s", "tests"], wt,
                                              ok=lambda o, c: c == 0)))
        results.append(("Rust tests", *step(log, "Rust tests", ["cargo", "test", "--release", "-j", str(os.cpu_count() or 4),
                                                                "-p", "sw2sc-core"], plugin)))
        reg = cfg.get("regression", [])
        if reg:
            out = os.path.join(BASE, f"regression-{rev[:8]}.json")
            base = os.path.join(BASE, "regression.json")
            results.append(("regression", *step(log, "Parts that rebuild still rebuild",
                                                [PY, "-X", "utf8", "tools/rebuild_set.py", *reg, "--out", out, "--baseline", base], wt)))
        if long and cfg.get("sample_list"):
            out = os.path.join(BASE, f"sample-{rev[:8]}.jsonl")
            base = os.path.join(BASE, "sample.jsonl")
            results.append(("sample run", *step(log, "Sample run through the plugin's converter",
                                                [PY, "-X", "utf8", "tools/convert_sample.py", cfg["sample_list"], out,
                                                 "--n", str(cfg.get("sample_n", 200)), "--baseline", base], wt)))
        passed = all(g for _n, g, _l in results)
        log.write(f"\nfinished {now()}\n\n## {'PASSED' if passed else 'FAILED'}\n\n")
        for n, g, last in results:
            log.write(f"- {'ok  ' if g else 'FAIL'} {n}: {last}\n")
    if passed:
        # this commit's results are the baseline the next ones are judged against
        for kind, ext in (("regression", "json"), ("sample", "jsonl")):
            src = os.path.join(BASE, f"{kind}-{rev[:8]}.{ext}")
            if os.path.exists(src):
                shutil.copyfile(src, os.path.join(BASE, f"{kind}.{ext}"))
        json.dump({"rev": rev, "long": bool(long), "at": now()}, open(os.path.join(BASE, "passed.json"), "w"))
    line = f"{now()}  {rev[:8]}  {'PASSED' if passed else 'FAILED'}  {', '.join(n for n, g, _l in results if not g)}  {os.path.basename(path)}\n"
    open(os.path.join(HOME, "results.log"), "a", encoding="utf-8").write(line)
    print(line.strip())
    return passed


def next_job():
    if not os.path.isdir(QUEUE):
        return None
    files = sorted(os.listdir(QUEUE))
    if not files:
        return None
    p = os.path.join(QUEUE, files[0])
    job = json.load(open(p, encoding="utf-8"))
    os.remove(p)
    return job


def long_done(rev: str) -> bool:
    p = os.path.join(BASE, f"sample-{rev[:8]}.jsonl")
    return os.path.exists(p)


def watch(branch: str, poll: int) -> None:
    print(f"{now()} watching {branch}; reports in {REPORTS}")
    seen = None
    while True:
        try:
            head = git("rev-parse", branch)
        except subprocess.CalledProcessError:
            head = None
        if head and head != seen:
            if seen is not None or not os.path.exists(os.path.join(HOME, "results.log")) or head[:8] not in open(os.path.join(HOME, "results.log"), encoding="utf-8").read():
                enqueue(head, long=False)
            seen = head
        job = next_job()
        if job:
            print(f"{now()} checking {job['rev'][:8]}{' with the long run' if job.get('long') else ''}")
            try:
                run_suite(job)
            except Exception as e:  # noqa: BLE001
                print(f"{now()} the suite stopped: {type(e).__name__}: {e}")
            continue
        # idle: the long run for the newest commit, once
        if head and config().get("sample_list") and not long_done(head):
            enqueue(head, long=True)
            continue
        time.sleep(poll)


def status() -> None:
    files = sorted(os.listdir(QUEUE)) if os.path.isdir(QUEUE) else []
    print(f"queued: {len(files)}" + "".join(f"\n  {f}" for f in files))
    p = os.path.join(HOME, "results.log")
    if os.path.exists(p):
        print("latest results:")
        for ln in open(p, encoding="utf-8").read().splitlines()[-10:]:
            print("  " + ln)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("watch")
    w.add_argument("--branch", default="dev")
    w.add_argument("--poll", type=int, default=60)
    s = sub.add_parser("suite")
    s.add_argument("rev")
    s.add_argument("--long", action="store_true")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    if a.cmd == "watch":
        watch(a.branch, a.poll)
    elif a.cmd == "suite":
        enqueue(git("rev-parse", a.rev), a.long, coalesce=False)
    else:
        status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
