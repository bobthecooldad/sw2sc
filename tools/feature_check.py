"""Rebuild each part's decoded feature tree in SolidCraft and compare it with the solid SolidWorks
saved (F-006).

    python tools/feature_check.py FOLDER [FOLDER...] [--out logs/feature-check.md] [--keep DIR]

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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folders", nargs="+")
    ap.add_argument("--out", default=os.path.join("logs", "feature-check.md"))
    ap.add_argument("--keep", help="keep the rebuilt designs here")
    ap.add_argument("--limit", type=int, default=0)
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
    for p in parts(a.folders):
        try:
            sw = SwFile(p)
            feats = features.read(sw)
        except Exception as e:  # noqa: BLE001
            counts["unreadable"] += 1
            rows.append((p, "unreadable", str(e)))
            continue
        if feats is None:
            counts["feature stream not numbered (pre-2015)"] += 1
            rows.append((p, "pre-2015", ""))
            continue
        if feats and all(f.kind == "import" for f in feats if f.kind != "sketch") and any(f.kind == "import" for f in feats):
            counts["imported body (no tree in SolidWorks either): converts as import"] += 1
            rows.append((p, "imported body", ""))
            continue
        why = [f"{f.name}: {f.reason}" for f in feats if f.kind == "tbd" or (f.reason and f.kind != "absorbed")]
        why += [f"{f.name}: imported body among features" for f in feats if f.kind == "import"]
        why += [f"{f.name}: {f.sketch.plane_how}" for f in feats if f.kind == "sketch" and f.sketch.plane is None]
        why += [f"{f.name}: {pr}" for f in feats if f.kind == "sketch" for pr in f.sketch.problems]
        if not verify.fully_decoded(feats) and not why:
            why.append("no solid feature")
        if why:
            counts["not fully decoded"] += 1
            rows.append((p, "not fully decoded", "; ".join(why[:4])))
            continue
        n += 1
        if a.limit and n > a.limit:
            break
        try:
            ref_design, _ = solidcraft.convert(p, feature_tree=False)
        except Exception as e:  # noqa: BLE001
            counts["reference not converted"] += 1
            rows.append((p, "no reference", str(e)))
            continue
        ref_design_eval = None   # the reference's numbers, for a mismatch's signature
        with tempfile.NamedTemporaryFile("w", suffix=".solidcraft", delete=False, encoding="utf-8") as fh:
            json.dump(ref_design, fh)
            ref_path = fh.name
        ref_design_eval = verify.evaluate(CLI, ref_path) if CLI else None
        os.unlink(ref_path)
        name = os.path.splitext(os.path.basename(p))[0]
        built = verify.rebuild(feats, ref_design, name, CLI)   # the CLI this check reports
        if built:
            if a.keep:
                with open(os.path.join(tmp, f"{n:03d}.feat.solidcraft"), "w", encoding="utf-8") as fh:
                    json.dump(built, fh)
            counts["rebuilt, matches the solid"] += 1
            used = [f"{f['name']} {f.get('extent', {}).get('direction') or f.get('angle', '')}"
                    for f in built["features"] if f["type"] in ("extrude", "revolve")]
            rows.append((p, "rebuilt", ", ".join(used)))
        else:
            counts["rebuilt, does not match"] += 1
            rows.append((p, "mismatch", verify.mismatch_signature(verify.LAST.get("eval"), ref_design_eval)))
        print(f"{name}: {rows[-1][1]}", flush=True)   # progress: the report is written at the end
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("# Feature check\n\n" + f"- kernel: {kernel}\n" +
                 "\n".join(f"- {k}: {v}" for k, v in counts.most_common()) + "\n\n")
        fh.write("| Part | Result | Notes |\n|---|---|---|\n")
        for p, r, note in rows:
            fh.write(f"| {os.path.basename(p)} | {r} | {note.replace('|', '/')} |\n")
    print(dict(counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
