"""Rebuild parts with the Rust port and the Python, against the same reference solid, and
compare: matched or not, and the design found."""
import glob, json, os, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
from sw2sc import features, solidcraft, verify  # noqa: E402
from sw2sc.swfile import SwFile  # noqa: E402
from compare_features import diff  # noqa: E402

EXE = os.path.join(os.path.dirname(HERE), "target", "release", "examples", "rebuild_one.exe")
tmp = tempfile.mkdtemp()
files = sorted(p for a in sys.argv[1:] for p in (glob.glob(os.path.join(a, "*.SLDPRT")) if os.path.isdir(a) else [a]))
for p in files:
    feats = features.read(SwFile(p))
    if not feats or not verify.fully_decoded(feats):
        print("skip", os.path.basename(p)); continue
    ref, _ = solidcraft.convert(p, feature_tree=False)
    rp = os.path.join(tmp, "ref.json"); json.dump(ref, open(rp, "w"))
    t = time.time(); py = verify.rebuild(feats, ref, os.path.splitext(os.path.basename(p))[0]); tp = time.time() - t
    out = subprocess.run([EXE, p, rp], capture_output=True, text=True, encoding="utf-8")
    try:
        rs = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        print("RUST FAILED", os.path.basename(p), out.stderr[-800:]); continue
    same_design = diff(json.loads(json.dumps(py)) if py else None, rs["design"], "") is None
    print(f"{os.path.basename(p):40s} python {'match' if py else 'no':5s} {tp:6.1f}s   rust {'match' if rs['matched'] else 'no':5s} {rs['seconds']:6.1f}s  tries {rs['tries']:3d}  same design: {same_design}", flush=True)
