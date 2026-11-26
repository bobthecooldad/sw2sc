"""Where a part's rebuild stops (F-006): for each part named (or every part that is fully decoded
but doesn't match), how far the in-order build gets, what stops it, and how close the closest
complete design comes to the part's own solid.

    python tools/rebuild_triage.py FOLDER [FOLDER...] [--names A,B] [--budget 90] [--out FILE] [--jobs 8]
"""
import argparse
import itertools
import json
import os
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sw2sc import features, fillets, solidcraft, verify  # noqa: E402
from sw2sc.swfile import SwFile  # noqa: E402
from feature_survey import parts  # noqa: E402


def triage(path, cli, budget):
    feats = features.read(SwFile(path))
    if not feats or not verify.fully_decoded(feats):
        return {"result": "not fully decoded"}
    ref, _ = solidcraft.convert(path, feature_tree=False)
    tmp = tempfile.mkdtemp(prefix="sw2sc-tri-")
    q = os.path.join(tmp, "ref.solidcraft")
    json.dump(ref, open(q, "w"))
    rr = verify.evaluate(cli, q)
    if not rr:
        return {"result": "reference not evaluated"}
    order = [f for f in feats if f.kind in ("boss", "cut", "fillet", "chamfer", "hole", "mirror", "thread", "pattern",
                                            "dome", "sweep", "sweepcut", "shell")]
    deepest = {"step": -1, "name": None}
    stops = {}
    orig_prefix, orig_cand = verify._prefix, fillets.candidates

    def prefix(name, fs, choices, planes, constraints, picked, upto, c, t):
        d, r = orig_prefix(name, fs, choices, planes, constraints, picked, upto, c, t)
        k = next((n for n, f in enumerate(order) if f.name == upto), -1)
        if r and not r["errors"] and k > deepest["step"]:
            deepest.update(step=k, name=upto)
        if r and r["errors"]:
            stops.setdefault(upto, r["errors"][0][:160])
        return d, r

    def cand(prefix_d, f, *a, **k):
        res = orig_cand(prefix_d, f, *a, **k)
        if not res:
            stops.setdefault(f.name, "no edge set fits")
        return res
    verify._prefix, fillets.candidates = prefix, cand
    best = None
    verify._deadline[0] = time.time() + budget
    sks = [f for f in feats if f.kind == "sketch"]
    try:
        for pc in itertools.product(*[range(max(1, len(f.sketch.planes))) for f in sks]):
            if time.time() > verify._deadline[0]:
                break
            planes = {f.name: i for f, i in zip(sks, pc)}
            for d in verify._sequential("t", feats, {}, planes, True, cli, tmp, rr):
                p = os.path.join(tmp, "f.solidcraft")
                json.dump(d, open(p, "w"))
                r = verify.evaluate(cli, p)
                if r and r["volume"] and rr["area"]:
                    err = abs(r["area"] - rr["area"]) / rr["area"]
                    if rr["volume"]:
                        err = max(err, abs(r["volume"] - rr["volume"]) / rr["volume"])
                    if best is None or err < best:
                        best = err
                    if verify.same(r, rr):
                        return {"result": "matches", "best": 0.0}
    finally:
        verify._prefix, fillets.candidates = orig_prefix, orig_cand
    last = order[deepest["step"] + 1].name if deepest["step"] + 1 < len(order) else None
    return {"result": "complete, no match" if best is not None else "stops",
            "best": best, "deepest": deepest["name"], "next": last,
            "why": stops.get(last) if last else None, "of": len(order)}


def _triage_one(args):
    path, cli, budget = args
    try:
        return path, triage(path, cli, budget)
    except Exception as e:  # noqa: BLE001
        return path, {"result": f"error {type(e).__name__}: {e}"}


def run_triages(paths, cli, budget, jobs=8):
    paths = list(paths)
    if not paths:
        return []
    workers = max(1, min(int(jobs), len(paths)))
    if workers == 1:
        return [_triage_one((p, cli, budget)) for p in paths]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(_triage_one, [(p, cli, budget) for p in paths]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folders", nargs="+")
    ap.add_argument("--names", default="")
    ap.add_argument("--budget", type=float, default=90)
    ap.add_argument("--out", default="")
    ap.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args()
    want = {n.strip() for n in a.names.split(",") if n.strip()}
    cli = verify.find_cli()
    status = verify.kernel_status(cli)   # a rebuild on a stale kernel says nothing about the checkout
    kernel = verify.kernel_line(status)
    print(kernel, flush=True)
    if status["stale"]:
        print("WARNING: " + kernel, file=sys.stderr)
    seen = set()
    paths = []
    for p in parts(a.folders):
        n = os.path.splitext(os.path.basename(p))[0]
        if (want and n not in want) or n in seen:
            continue
        seen.add(n)
        paths.append(p)
    lines = [f"kernel | {kernel}"]
    for p, r in run_triages(paths, cli, a.budget, a.jobs):
        if r["result"] == "not fully decoded" and not want:
            continue
        n = os.path.splitext(os.path.basename(p))[0]
        line = f"{n} | {r}"
        print(line, flush=True)
        lines.append(line)
    if a.out:
        open(a.out, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
