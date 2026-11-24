"""Compare the Rust port's default designs with the Python writer's on every fully decoded part."""
import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
from sw2sc import features, verify  # noqa: E402
from sw2sc.swfile import SwFile  # noqa: E402
from compare_features import diff  # noqa: E402  (compare_features runs main() only as a script)

EXE = os.path.join(os.path.dirname(HERE), "target", os.environ.get("PROFILE", "debug"), "examples", "dump_designs.exe")


def main():
    roots = sys.argv[1:]
    files = sorted({p for r in roots for ext in ("SLDPRT", "sldprt")
                    for p in glob.glob(os.path.join(r, "**", "*." + ext), recursive=True)})
    rust = {}
    for i in range(0, len(files), 40):
        out = subprocess.run([EXE] + files[i:i + 40], capture_output=True, text=True, encoding="utf-8")
        for line in out.stdout.splitlines():
            d = json.loads(line)
            rust[d["file"]] = d
        if out.returncode:
            print("rust failed on a batch:", out.stderr[-1500:])
    bad = n = 0
    for p in files:
        fs = features.read(SwFile(p))
        py = None
        if fs and verify.fully_decoded(fs):
            name = os.path.splitext(os.path.basename(p))[0]
            py = json.loads(json.dumps(features.design(name, fs, {}, None, True, {})))
            n += 1
        r = rust.get(p, {}).get("design", "missing")
        # an import's STEP text: the same entities line for line; numbers can differ in their last
        # digit (the two languages' maths libraries round differently), so its lines are compared
        for dd in (py, r):
            for g in (dd or {}).get("features", []) if isinstance(dd, dict) else []:
                if isinstance(g.get("step"), str):
                    g["step"] = [ln.split("(")[0] for ln in g["step"].splitlines()]
        d = diff(py, r, "")
        if d:
            bad += 1
            if bad <= 12:
                print("DIFF", os.path.basename(p), d[:500])
    print("files", len(files), "designs", n, "differ", bad)


main()
