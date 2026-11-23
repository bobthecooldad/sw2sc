"""Compare the Rust port's STEP text with the Python's on every sample part."""
import glob, json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from sw2sc import geometry  # noqa: E402
from sw2sc.swfile import SwFile  # noqa: E402

EXE = os.path.join(os.path.dirname(HERE), "target", os.environ.get("PROFILE", "release"), "examples", "dump_step.exe")
files = sorted({p for r in sys.argv[1:] for ext in ("SLDPRT", "sldprt") for p in glob.glob(os.path.join(r, "**", "*." + ext), recursive=True)})
tmp = tempfile.mkdtemp()
rust = {}
for i in range(0, len(files), 25):
    sub = os.path.join(tmp, str(i)); os.makedirs(sub, exist_ok=True)   # (each batch numbers its files from 0)
    out = subprocess.run([EXE, sub] + files[i:i + 25], capture_output=True, text=True, encoding="utf-8")
    for line in out.stdout.splitlines():
        d = json.loads(line); rust[d["file"]] = d
    if out.returncode:
        print("rust failed in a batch:", out.stderr[-1500:])
same = diff = 0
for p in files:
    name = os.path.splitext(os.path.basename(p))[0]
    try:
        text, _w, _st = geometry.part_to_step(SwFile(p), name)
    except Exception as e:  # noqa: BLE001
        text = None
    r = rust.get(p, {})
    rt = open(r["step"], encoding="utf-8").read() if r.get("step") else None
    if text == rt:
        same += 1
        continue
    diff += 1
    if diff <= 8:
        if text is None or rt is None:
            print("DIFF", os.path.basename(p), "python", text is not None, "rust", rt is not None, r.get("error"))
        else:
            a, b = text.splitlines(), rt.splitlines()
            k = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
            print("DIFF", os.path.basename(p), f"lines {len(a)}/{len(b)} first at {k}:", (a[k] if k < len(a) else "")[:160], "|", (b[k] if k < len(b) else "")[:160])
print("files", len(files), "same", same, "differ", diff)
