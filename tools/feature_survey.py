"""Survey the feature streams of SolidWorks parts (F-006).

    python tools/feature_survey.py FOLDER [FOLDER...] [--out logs/feature-survey.md]

For every part: the SolidWorks version that saved it, whether it has a
`Config-0-ResolvedFeatures` stream, and the feature types its KeyWords list. Then, over all
parts, which object classes the streams use and in how many files. Read only; nothing is
written next to the parts.
"""
from __future__ import annotations

import argparse
import collections
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sw2sc.swfile import SwFile  # noqa: E402

SKIP_DIRS = {".git", "Euro Truck Simulator 2", "My Games", "bookworm-android", "Visual Studio 2019", "MATLAB"}
NOT_FEATURES = {"Annotations", "Surface Bodies", "SolidWorks Materials", "SOLIDWORKS Materials", "Ambient",
                "Directional", "Equations", "Exploded Views", "Sensors", "Plane", "Favorites", "History",
                "Lights, Cameras and Scene", "Design Binder", "Comments", "Solid Bodies", "Notes", "Markups",
                "Selection Sets", "Origin", "ConfigurationManager", "Point", "Spot", "Live Section Planes"}


def classes(stream: bytes) -> list[str]:
    """Class names of the new-class records in an MFC-style object stream, in order."""
    out = []
    for m in re.finditer(rb"\xff\xff[\x00-\x7f]\x00", stream):
        i = m.start()
        n = struct.unpack_from("<H", stream, i + 4)[0] if i + 6 <= len(stream) else 0
        name = stream[i + 6:i + 6 + n]
        if 3 <= n <= 64 and re.fullmatch(rb"[A-Za-z_][A-Za-z0-9_]*", name):
            out.append(name.decode())
    return out


def parts(folders):
    for root in folders:
        for d, dirs, files in os.walk(root):
            dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
            for f in sorted(files):
                if f.lower().endswith(".sldprt") and not f.startswith(("~$", ".~")):
                    yield os.path.join(d, f)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folders", nargs="+")
    ap.add_argument("--out", default=os.path.join("logs", "feature-survey.md"))
    a = ap.parse_args(argv)
    rows, used, feat_types, versions = [], collections.Counter(), collections.Counter(), collections.Counter()
    for p in parts(a.folders):
        try:
            sw = SwFile(p)
        except Exception as e:  # noqa: BLE001 - a survey reports and goes on
            rows.append((p, "?", False, f"unreadable: {e}"))
            continue
        ver = re.search(r'swVersion="(\d+)"', sw.xml("swXmlContents/Features") or "")
        ver = ver.group(1) if ver else "?"
        versions[ver] += 1
        kw = sw.xml("swXmlContents/KeyWords") or ""
        types = [t for t in re.findall(r'<\w+ id="\d+" Name="[^"]*" Type="([^"]+)"', kw) if t not in NOT_FEATURES]
        for t in set(types):
            feat_types[t] += 1
        rf = sw.streams.get("Contents/Config-0-ResolvedFeatures")
        if rf:
            for c in set(re.sub(r"_c.?$", "_c", c) for c in classes(rf)):
                used[c] += 1
        rows.append((p, ver, bool(rf), ", ".join(dict.fromkeys(types))))
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("# Feature survey\n\n")
        fh.write(f"{len(rows)} parts. Versions: " + ", ".join(f"{v} ({n})" for v, n in sorted(versions.items())) + ".\n")
        fh.write(f"With a feature stream: {sum(1 for r in rows if r[2])}.\n\n")
        fh.write("## Feature types (parts using each)\n\n")
        for t, n in feat_types.most_common():
            fh.write(f"- {t}: {n}\n")
        fh.write("\n## Object classes in the feature streams (parts using each)\n\n")
        for c, n in used.most_common():
            fh.write(f"- `{c}`: {n}\n")
        fh.write("\n## Parts\n\n| Version | Stream | Part | Features |\n|---|---|---|---|\n")
        for p, ver, rf, types in rows:
            fh.write(f"| {ver} | {'yes' if rf else 'no'} | {os.path.basename(p)} | {types} |\n")
    print(f"{len(rows)} parts, {sum(1 for r in rows if r[2])} with a feature stream; "
          f"{len(feat_types)} feature types, {len(used)} classes; written to {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
