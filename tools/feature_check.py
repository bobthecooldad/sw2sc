"""Rebuild each part's decoded feature tree in SolidCraft and compare it with the solid SolidWorks
saved (F-006).

    python tools/feature_check.py FOLDER [FOLDER...] [--out logs/feature-check.md] [--keep DIR] [--jobs 8]

For every part whose features are all decoded (sketches, extrudes): write the features as a
SolidCraft design, try each extrude's direction (positive, negative, symmetric) and operation
where the file doesn't settle it, evaluate with solidcraft-cli, and compare volume, surface area
and bounding box with the part converted as an imported solid. A part counts as rebuilt when
all three match within 0.1 %. Read only on the source folders; designs go to a temp folder.
"""
from __future__ import annotations

import argparse
import collections
import itertools
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sw2sc import features, solidcraft, verify  # noqa: E402
from sw2sc.swfile import SwFile  # noqa: E402
from feature_survey import parts  # noqa: E402

CLI = verify.find_cli()      # the newest one: SOLIDCRAFT_CLI, the app on the PATH, or the build in C:\dev\solidcraft
REL = 1e-3


def evaluate(path: str) -> dict | None:
    try:
        r = subprocess.run([CLI, "eval", path], capture_output=True, timeout=180)
    except subprocess.TimeoutExpired:
        return None
    try:
        d = json.loads(r.stdout.decode("utf-8", "replace"))
    except ValueError:
        return None
    t = d.get("total") or {}
    boxes = [bd.get("bbox") for bd in d.get("bodies", []) if bd.get("bbox")]
    if boxes:
        lo = [min(bx["min"][k] for bx in boxes) for k in range(3)]
        hi = [max(bx["max"][k] for bx in boxes) for k in range(3)]
    else:
        lo = hi = None
    errors = [s.get("error") for s in d.get("timeline", []) if s.get("error")]
    return {"volume": t.get("volume_mm3"), "area": t.get("area_mm2"), "lo": lo, "hi": hi, "errors": errors}


def same(a: dict, b: dict) -> bool:
    if not a or not b or not a["volume"] or not b["volume"]:
        return False
    close = lambda x, y: abs(x - y) <= REL * max(abs(x), abs(y), 1.0)
    if not (close(a["volume"], b["volume"]) and close(a["area"], b["area"])):
        return False
    if a["lo"] and b["lo"]:
        size = max(max(h - l for l, h in zip(b["lo"], b["hi"])), 1.0)
        return all(abs(x - y) <= REL * size for x, y in zip(a["lo"] + a["hi"], b["lo"] + b["hi"]))
    return True


def _check_one(args) -> dict:
    path, cli = args
    row = {"path": path, "status": "unreadable", "note": "", "design": None}
    try:
        sw = SwFile(path)
        feats = features.read(sw)
    except Exception as e:  # noqa: BLE001
        row["note"] = str(e)
        return row
    if feats is None:
        row["status"] = "pre-2015"
        return row
    if feats and all(f.kind == "import" for f in feats if f.kind != "sketch") and any(f.kind == "import" for f in feats):
        row["status"] = "imported body"
        return row
    why = [f"{f.name}: {f.reason}" for f in feats if f.kind == "tbd" or (f.reason and f.kind != "absorbed")]
    why += [f"{f.name}: imported body among features" for f in feats if f.kind == "import"]
    why += [f"{f.name}: {f.sketch.plane_how}" for f in feats if f.kind == "sketch" and f.sketch.plane is None]
    why += [f"{f.name}: {pr}" for f in feats if f.kind == "sketch" for pr in f.sketch.problems]
    if not verify.fully_decoded(feats) and not why:
        why.append("no solid feature")
    if why:
        row.update(status="not fully decoded", note="; ".join(why[:4]))
        return row
    try:
        ref_design, _ = solidcraft.convert(path, feature_tree=False)
    except Exception as e:  # noqa: BLE001
        row.update(status="no reference", note=str(e))
        return row
    with tempfile.NamedTemporaryFile("w", suffix=".solidcraft", delete=False, encoding="utf-8") as fh:
        json.dump(ref_design, fh)
        ref_path = fh.name
    try:
        ref_design_eval = verify.evaluate(cli, ref_path) if cli else None
    finally:
        os.unlink(ref_path)
    name = os.path.splitext(os.path.basename(path))[0]
    built = verify.rebuild(feats, ref_design, name, cli)   # the CLI this check reports
    if built:
        used = [f"{f['name']} {f.get('extent', {}).get('direction') or f.get('angle', '')}"
                for f in built["features"] if f["type"] in ("extrude", "revolve")]
        row.update(status="rebuilt", note=", ".join(used), design=built)
    else:
        row.update(status="mismatch", note=verify.mismatch_signature(verify.LAST.get("eval"), ref_design_eval))
    return row


def run_checks(paths, cli, jobs=8) -> list[dict]:
    paths = list(paths)
    if not paths:
        return []
    workers = max(1, min(int(jobs), len(paths)))
    if workers == 1:
        return [_check_one((p, cli)) for p in paths]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(_check_one, [(p, cli) for p in paths]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folders", nargs="+")
    ap.add_argument("--out", default=os.path.join("logs", "feature-check.md"))
    ap.add_argument("--keep", help="keep the rebuilt designs here")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args(argv)
    status = verify.kernel_status(CLI)   # a rebuild on a stale kernel says nothing about the checkout
    kernel = verify.kernel_line(status)
    print(kernel)
    if status["stale"]:
        print("WARNING: " + kernel, file=sys.stderr)
    tmp = a.keep or tempfile.mkdtemp(prefix="sw2sc-fc-")
    os.makedirs(tmp, exist_ok=True)
    counts = collections.Counter()
    rows = []
    n = 0
    labels = {
        "pre-2015": "feature stream not numbered (pre-2015)",
        "imported body": "imported body (no tree in SolidWorks either): converts as import",
        "not fully decoded": "not fully decoded",
        "no reference": "reference not converted",
        "rebuilt": "rebuilt, matches the solid",
        "mismatch": "rebuilt, does not match",
        "unreadable": "unreadable",
    }
    remaining = iter(parts(a.folders))
    stopped = False
    while not stopped:
        batch = list(itertools.islice(remaining, max(1, a.jobs))) if a.limit else list(remaining)
        if not batch:
            break
        for row in run_checks(batch, CLI, a.jobs):
            attempted = row["status"] in ("no reference", "rebuilt", "mismatch")
            if attempted:
                n += 1
                if a.limit and n > a.limit:
                    stopped = True
                    break
            counts[labels[row["status"]]] += 1
            rows.append(row)
            if a.keep and row["design"]:
                with open(os.path.join(tmp, f"{n:03d}.feat.solidcraft"), "w", encoding="utf-8") as fh:
                    json.dump(row["design"], fh)
            if row["status"] in ("rebuilt", "mismatch"):
                print(f"{os.path.splitext(os.path.basename(row['path']))[0]}: {row['status']}", flush=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("# Feature check\n\n" + f"- kernel: {kernel}\n" +
                 "\n".join(f"- {k}: {v}" for k, v in counts.most_common()) + "\n\n")
        fh.write("| Part | Result | Notes |\n|---|---|---|\n")
        for row in rows:
            fh.write(f"| {os.path.basename(row['path'])} | {row['status']} | {row['note'].replace('|', '/')} |\n")
    print(dict(counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
