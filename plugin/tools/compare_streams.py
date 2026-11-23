"""Compare the Rust port's streams with the Python reader's on every sample part."""
import glob, json, os, subprocess, sys, zlib
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from sw2sc.swfile import SwFile  # noqa: E402

EXE = os.path.join(os.path.dirname(HERE), "target", "debug", "examples", "dump_streams.exe")
roots = sys.argv[1:]
files = sorted({p for r in roots for ext in ("SLDPRT", "sldprt", "SLDASM", "sldasm")
                for p in glob.glob(os.path.join(r, "**", "*." + ext), recursive=True)})
rust = {}
for i in range(0, len(files), 50):
    out = subprocess.run([EXE] + files[i:i + 50], capture_output=True, text=True, encoding="utf-8").stdout
    for line in out.splitlines():
        d = json.loads(line)
        rust[d["file"]] = d
bad = 0
for p in files:
    try:
        f = SwFile(p)
        py = {"container": f.container, "streams": {k: [len(v), zlib.crc32(v)] for k, v in f.streams.items()}}
    except Exception as e:  # noqa: BLE001
        py = {"error": str(e)}
    r = rust.get(p, {"error": "no output"})
    same = ("error" in py) == ("error" in r) and ("error" in py or (py["container"] == r["container"] and py["streams"] == r["streams"]))
    if not same:
        bad += 1
        if bad <= 8:
            ks = sorted(set(py.get("streams", {})) ^ set(r.get("streams", {})))
            diff = [k for k in py.get("streams", {}) if k in r.get("streams", {}) and py["streams"][k] != r["streams"][k]]
            print("DIFF", os.path.basename(p), py.get("error"), r.get("error"), ks[:5], diff[:5])
print("files", len(files), "differ", bad)
