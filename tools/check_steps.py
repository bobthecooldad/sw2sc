"""Open every STEP file in a folder with SolidCraft's CLI and summarise how it reads them.

usage: python tools/check_steps.py <solidcraft-cli.exe> <folder> [report.json]
"""
import concurrent.futures as cf
import json
import os
import subprocess
import sys


def check(cli, path):
    try:
        p = subprocess.run([cli, "eval", path], capture_output=True, timeout=600)
        out = p.stdout.decode("utf-8", "replace")
        start = out.find("{")
        data = json.loads(out[start:]) if start >= 0 else None
    except subprocess.TimeoutExpired:
        return path, {"error": "timeout"}
    except Exception as e:
        return path, {"error": f"{type(e).__name__}: {e}", "stderr": p.stderr.decode("utf-8", "replace")[-400:]}
    if data is None:
        return path, {"error": "no output", "stderr": p.stderr.decode("utf-8", "replace")[-400:]}
    bodies = data.get("bodies", [])
    tl = data.get("timeline", [{}])
    return path, {
        "bodies": len(bodies),
        "closed": sum(1 for b in bodies if b.get("closed")),
        "negative_volume": sum(1 for b in bodies if (b.get("volume_mm3") or 0) < 0),
        "volume_mm3": sum(b.get("volume_mm3") or 0 for b in bodies),
        "faces": sum(b.get("faces", 0) for b in bodies),
        "error": tl[0].get("error") if tl else None,
        "warning": tl[0].get("warning") if tl else None,
        "open_bodies_skipped": data.get("total", {}).get("open_bodies_skipped"),
    }


def main():
    cli, folder = sys.argv[1], sys.argv[2]
    files = sorted(os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(".step"))
    res = {}
    with cf.ThreadPoolExecutor(max_workers=min(16, os.cpu_count() or 4)) as ex:
        for path, r in ex.map(lambda f: check(cli, f), files):
            res[os.path.basename(path)] = r
    if len(sys.argv) > 3:
        with open(sys.argv[3], "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=1)
    n = len(res)
    errs = {k: v for k, v in res.items() if v.get("error")}
    allclosed = sum(1 for v in res.values() if not v.get("error") and v.get("bodies") and v["closed"] == v["bodies"])
    print(f"files {n}: all bodies closed {allclosed}, with errors {len(errs)}, "
          f"bodies {sum(v.get('bodies', 0) for v in res.values())}, closed {sum(v.get('closed', 0) for v in res.values())}, "
          f"negative volume {sum(v.get('negative_volume', 0) for v in res.values())}")
    for k, v in list(errs.items())[:15]:
        print(" ERR", k, str(v.get("error"))[:200])


if __name__ == "__main__":
    main()
