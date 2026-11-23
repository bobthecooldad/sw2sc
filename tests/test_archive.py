import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sw2sc import archive  # noqa: E402

DOCS = os.path.expanduser(r"~\Documents")
# (part, how far before the "Top Plane" name its class tag is): a sample of the user's own
# 2015+ files; skipped where they aren't on this PC.
PARTS = ["Part B.SLDPRT", "Part N.SLDPRT", "Part L.SLDPRT"]


class ArchiveTests(unittest.TestCase):
    def test_new_class_and_old_class_numbers(self):
        cls = b"\xff\xff\x01\x00\x05\x00Foo_c"
        s = struct.pack("<IH", 10, 1) + cls + b"\x00\x00" + struct.pack("<H", 0x8000 | 10) + struct.pack("<H", 0x8003)
        recs = archive.records(s)
        self.assertEqual([(r.cls, r.number, r.new_class) for r in recs],
                         [("Foo_c", 11, True), ("Foo_c", 12, False), ("pre3", 13, False)])

    def test_plane_objects_carry_their_class_number(self):
        from sw2sc.swfile import SwFile
        found = 0
        for name in PARTS:
            path = os.path.join(DOCS, name)
            if not os.path.isfile(path):
                continue
            b = SwFile(path).streams["Contents/Config-0-ResolvedFeatures"]
            number = archive.class_numbers(archive.records(b))["moRefPlane_c"]
            for plane in ("Top Plane", "Right Plane"):  # named in English in these files
                i = b.find(plane.encode("utf-16le"))
                tag = struct.unpack_from("<H", b, i - 8)[0]
                self.assertEqual(tag, 0x8000 | number, (name, plane))
            found += 1
        if not found:
            self.skipTest("the 2015+ sample parts aren't on this PC")


if __name__ == "__main__":
    unittest.main()
