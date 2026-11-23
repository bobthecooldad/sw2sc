"""Check the object numbering (sw2sc.archive) on every part in some folders.

    python tools/archive_check.py FOLDER [FOLDER...]

A named object is a class tag followed by a text string (`FF FE FF`). When the numbering is
right, each such tag is `0x8000 |` the number of a class the stream brought in, or one numbered
before the stream starts. Prints, per SolidWorks version, how many parts check out fully.
"""
from __future__ import annotations

import collections
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sw2sc import archive  # noqa: E402
from sw2sc.swfile import SwFile  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from feature_survey import parts  # noqa: E402


def check(b: bytes) -> tuple[int, int, int | None]:
    start = archive.start_number(b)
    recs = archive.records(b, start)
    defined = set(archive.class_numbers(recs).values())
    good = bad = 0
    for m in re.finditer(rb"(?=..\xff\xfe\xff)", b, re.S):
        i = m.start()
        tag = struct.unpack_from("<H", b, i)[0]
        if not tag & 0x8000 or tag == 0xFFFF:
            continue
        k = tag & 0x7FFF
        if k in defined or (start and k < start):
            good += 1
        else:
            bad += 1
    return good, bad, start


def main(argv=None) -> int:
    by_ver = collections.defaultdict(lambda: [0, 0, 0])
    for p in parts(sys.argv[1:] if argv is None else argv):
        try:
            sw = SwFile(p)
        except Exception:  # noqa: BLE001
            continue
        b = sw.streams.get("Contents/Config-0-ResolvedFeatures")
        if not b:
            continue
        ver = re.search(r'swVersion="(\d+)"', sw.xml("swXmlContents/Features") or "")
        ver = ver.group(1) if ver else "?"
        good, bad, start = check(b)
        v = by_ver[(ver, "header" if start else "no header")]
        v[0] += 1
        v[1] += bad == 0
        v[2] += bad
    for (ver, kind), (n, ok, bad) in sorted(by_ver.items()):
        print(f"version {ver:>6} {kind:9}: {ok}/{n} parts all named objects check out ({bad} tags off)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
