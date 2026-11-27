import math
import os
import unittest

from sw2sc import features

DOCS = os.path.expanduser(r"~\Documents")
SLIPPAD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "..", "..", "samples",
                       "slippad-solidworks")
if not os.path.isdir(SLIPPAD):
    SLIPPAD = r"C:\Solidworks to Solidcraft\samples\slippad-solidworks"


def sketch(points, lines=(), arcs=(), circles=()):
    s = features.Sketch("S", 0)
    s.points = {k: (x / 1000, y / 1000) for k, (x, y) in points.items()}
    s.lines, s.arcs, s.circles = list(lines), list(arcs), list(circles)
    s.add_plane((features.FRONT, (0.0, 0.0, 0.0)), "test")
    return s


class RegionTests(unittest.TestCase):
    TAGS = {100: "sgLineHandle", 102: "sgArcHandle"}

    def region(self, *entries):
        import struct
        body = b""
        for tag, cid in entries:
            body += struct.pack("<4H", tag, cid, 0xFFFF, 0xFFFF) + bytes(4)
        return b"\x00moSketchRegion_c" + body + b"\x00moSketchChain_c" + bytes(8)

    def test_the_region_names_its_curves_and_their_kind(self):
        b = self.region((100, 4), (102, 2))
        self.assertEqual(features._region_curves(b, 0, len(b), self.TAGS), [("line", 4), ("arc", 2)])

    def test_a_tag_that_is_not_a_handle_is_not_a_curve(self):
        b = self.region((555, 4))
        self.assertEqual(features._region_curves(b, 0, len(b), self.TAGS), [])

    def test_a_sketch_without_a_region_has_none(self):
        self.assertEqual(features._region_curves(b"nothing here", 0, 12, self.TAGS), [])


class ChainTests(unittest.TestCase):
    def chain(self, ids, n=None):
        import struct
        head = struct.pack("<H", len(ids) if n is None else n)
        body = b"".join(struct.pack("<I", i) for i in ids)
        return b"\x00moSketchChain_c" + head + body + struct.pack("<3H", 1, 0, 6)

    def test_the_chain_names_its_points_in_order(self):
        b = self.chain([8, 7, 6, 4, 5, 11])
        self.assertEqual(features._chain_points(b, 0, len(b)), [8, 7, 6, 4, 5, 11])

    def test_a_count_that_runs_past_the_ids_is_not_trusted(self):
        self.assertEqual(features._chain_points(self.chain([8, 7], n=99), 0, 64), [])

    def test_a_sentinel_stops_the_list(self):
        self.assertEqual(features._chain_points(self.chain([8, 0xFFFFFFFF, 7]), 0, 64), [8])

    def test_no_chain_record(self):
        self.assertEqual(features._chain_points(b"nothing here", 0, 12), [])


class ProfileTests(unittest.TestCase):
    def test_nested_loops_are_holes_and_touching_loops_are_not(self):
        # a 30 x 20 outline, a 10 x 6 tab sharing part of its top edge, a hole inside
        pts = {1: (0, 0), 2: (30, 0), 3: (30, 20), 4: (0, 20),
               5: (5, 20), 6: (15, 20), 7: (15, 26), 8: (5, 26),
               9: (10, 5), 10: (20, 5), 11: (20, 15), 12: (10, 15)}
        s = sketch(pts, lines=[(1, 2), (2, 3), (3, 4), (4, 1), (5, 6), (6, 7), (7, 8), (8, 5),
                               (9, 10), (10, 11), (11, 12), (12, 9)])
        loops = features.profile_loops(s)
        self.assertEqual(len(loops), 2)  # outline and tab; the inner loop is a hole
        self.assertNotIn(["l9", "l10", "l11", "l12"], loops)

    def test_arc_runs_on_with_the_line_it_meets(self):
        # a slot end: line along +x into (10, 0), half circle about (10, 5) to (10, 10)
        s = sketch({1: (0, 0), 2: (10, 0), 3: (10, 10), 4: (10, 5)}, lines=[(1, 2)], arcs=[(3, 2, 4)])
        a, c = features._arc_ends(s, 3, 2, 4)
        self.assertEqual((a, c), (2, 3))  # anticlockwise from (10, 0) carries the line on

    def test_short_way_without_a_line(self):
        s = sketch({1: (5, 0), 2: (0, 5), 3: (0, 0)}, arcs=[(2, 1, 3)])
        self.assertEqual(features._arc_ends(s, 2, 1, 3), (1, 2))


class RevolveTests(unittest.TestCase):
    def test_sequential_builds_revolve_and_revolved_cut(self):
        from unittest import mock
        from sw2sc import verify
        sk = sketch({1: (10, 0), 2: (20, 0), 3: (20, 10), 4: (10, 10)}, lines=[(1, 2), (2, 3), (3, 4), (4, 1)])
        sk.name = "Sketch1"
        feats = [features.Feature("sketch", "Sketch1", 0, features.SKETCH, sketch=sk),
                 features.Feature("revolve", "Revolve1", 1, features.REVOLVE, profile="Sketch1", angle_deg=90.0),
                 features.Feature("revcut", "Cut-Revolve1", 2, features.REVCUT, profile="Sketch1", angle_deg=270.0)]
        choices = {"Revolve1": (0, 1), "Cut-Revolve1": (1, -1)}

        def evaluated(*args):
            volume = 100.0 if args[6] == "Revolve1" else 80.0
            return {}, {"volume": volume, "area": volume, "errors": [], "lo": [0, 0, 0], "hi": [1, 1, 1]}

        with mock.patch("sw2sc.verify._prefix", side_effect=evaluated):
            built = list(verify._sequential("Part", feats, choices, {"Sketch1": 0}, True, "unused", "tmp"))
        self.assertEqual(len(built), 1)
        revolves = [f for f in built[0]["features"] if f["type"] == "revolve"]
        self.assertEqual([(f["operation"], f["angle"]) for f in revolves], [("new_body", "90.0"), ("cut", "-270.0")])
        self.assertEqual([f["axis"] for f in revolves],
                         [{"type": "sketch_axis", "axis": "x"}, {"type": "sketch_axis", "axis": "y"}])


class BodyMoveTests(unittest.TestCase):
    def test_rotation_and_translation_become_a_rigid_matrix(self):
        sk = sketch({1: (0, 0), 2: (10, 0), 3: (10, 10), 4: (0, 10)}, lines=[(1, 2), (2, 3), (3, 4), (4, 1)])
        sk.name = "Sketch1"
        feats = [features.Feature("sketch", "Sketch1", 0, features.SKETCH, sketch=sk),
                 features.Feature("boss", "Boss-Extrude1", 1, features.BOSS, profile="Sketch1", depth_mm=5),
                 features.Feature("move", "Body-Move/Copy1", 2, "moMoveCopyBody_c",
                                  rotation=((0, -1, 0), (1, 0, 0), (0, 0, 1)), translate=(10, 20, 30))]
        move = features.design("Part", feats, {}, None, True, {})["features"][-1]
        self.assertEqual(move["matrix"], [[0.0, -1.0, 0.0, 10.0], [1.0, 0.0, 0.0, 20.0],
                                          [0.0, 0.0, 1.0, 30.0], [0.0, 0.0, 0.0, 1.0]])
        self.assertNotIn("translate", move)

    def test_identity_move_keeps_translate(self):
        sk = sketch({1: (0, 0), 2: (10, 0), 3: (10, 10), 4: (0, 10)}, lines=[(1, 2), (2, 3), (3, 4), (4, 1)])
        sk.name = "Sketch1"
        feats = [features.Feature("sketch", "Sketch1", 0, features.SKETCH, sketch=sk),
                 features.Feature("boss", "Boss-Extrude1", 1, features.BOSS, profile="Sketch1", depth_mm=5),
                 features.Feature("move", "Body-Move/Copy1", 2, "moMoveCopyBody_c",
                                  rotation=((1, 0, 0), (0, 1, 0), (0, 0, 1)), translate=(10, 20, 30))]
        move = features.design("Part", feats, {}, None, True, {})["features"][-1]
        self.assertEqual(move["translate"], ["10", "20", "30"])
        self.assertNotIn("matrix", move)


class ScaleTests(unittest.TestCase):
    def test_factors_are_the_first_three_sizes_after_the_name(self):
        import struct
        name = "Scale1".encode("utf-16le")
        rec = b"\x04\x80\xff\xfe\xff\x06" + name + bytes(8) + struct.pack("<d", 0.062) + bytes(20) + \
            struct.pack("<3d", 1.06, 1.06, 1.06) + bytes(8)
        self.assertEqual(features._scale_factors(rec, 0, len(rec)), (1.06, 1.06, 1.06))

    def test_the_rebuild_finds_what_it_scales_about(self):
        import json
        import tempfile
        from sw2sc import verify
        cli = verify.find_cli()
        if not cli:
            self.skipTest("solidcraft-cli not found")
        # an L-shaped plate, 10 mm thick, scaled 1.06 about its centre of mass (the origin, the
        # centre of mass and the middle of its box all differ)
        s = sketch({1: (0, 0), 2: (40, 0), 3: (40, 10), 4: (10, 10), 5: (10, 30), 6: (0, 30)},
                   lines=[(1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 1)])
        s.name = "Sketch1"
        boss = features.Feature("boss", "Boss-Extrude1", 1, "moExtrusion_c", depth_mm=10.0, profile="Sketch1")
        sc = features.Feature("scale", "Scale1", 2, "moScale_c")
        sc.scale = (1.06, 1.06, 1.06)
        feats = [features.Feature("sketch", "Sketch1", 0, "moProfileFeature_c", sketch=s), boss, sc]
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "pre.solidcraft")
            json.dump(features.design("t", feats, {}, None, True, {}, upto="Boss-Extrude1"), open(p, "w"))
            com = verify.evaluate(cli, p)["com"]
        ref = features.design("t", feats, {}, None, True, {"scale:Scale1": com})
        ref.pop("pending", None)
        built = verify.rebuild(feats, ref, "t", cli)
        self.assertIsNotNone(built)
        g = next(x for x in built["features"] if x["type"] == "scale")
        self.assertEqual((g["factor"], [round(c, 6) for c in g["origin"]]), ("1.06", [round(c, 6) for c in com]))


class EndConditionTests(unittest.TestCase):
    def test_mid_plane_has_no_one_sided_search_branches(self):
        from unittest import mock
        from sw2sc import verify
        sk = sketch({1: (0, 0), 2: (10, 0), 3: (10, 10), 4: (0, 10)},
                    lines=[(1, 2), (2, 3), (3, 4), (4, 1)])
        sk.name = "Sketch1"
        boss = features.Feature("boss", "Boss-Extrude1", 1, features.BOSS,
                                profile="Sketch1", depth_mm=55.0)
        boss.mid_plane = True
        feats = [features.Feature("sketch", "Sketch1", 0, features.SKETCH, sketch=sk), boss]
        result = {"volume": 100.0, "area": 100.0, "errors": [], "lo": None, "hi": None}
        with mock.patch("sw2sc.verify._prefix", return_value=({}, result)) as prefix:
            list(verify._sequential("Part", feats, {}, {"Sketch1": 0}, True, "unused", "tmp"))
        directions = [call.args[2][boss.name][0] for call in prefix.call_args_list]
        self.assertEqual(directions, ["symmetric"])


class PatternDimensionTests(unittest.TestCase):
    def test_fixed_dimensions_supply_spacing_then_count(self):
        dims = {"FIX_27": "2", "FIX_26": "20"}
        self.assertEqual(features._fixed_pattern_dims(dims), {"D1": "2", "D3": "20"})

    def test_fixed_dimensions_require_one_consecutive_pair(self):
        self.assertEqual(features._fixed_pattern_dims({"FIX_26": "20", "FIX_28": "2"}), {})
        self.assertEqual(features._fixed_pattern_dims({"FIX_26": "20", "FIX_27": "2", "FIX_28": "3"}), {})
        self.assertEqual(features._fixed_pattern_dims({"FIX_26": "20", "FIX_27": "2.5"}), {})


class RealPartTests(unittest.TestCase):
    def read(self, path):
        if not os.path.isfile(path):
            self.skipTest("sample part not on this PC")
        from sw2sc.swfile import SwFile
        return features.read(SwFile(path))

    def test_mid_plane_end_spec_is_read_and_written_symmetrically(self):
        f = self.read(os.path.join(SLIPPAD, "shaft_3x55mm.SLDPRT"))
        boss = next(x for x in f if x.kind == "boss")
        self.assertTrue(getattr(boss, "mid_plane", False))
        d = features.design("t", f, {boss.name: ("positive", None)})
        extent = next(x for x in d["features"] if x["type"] == "extrude")["extent"]
        self.assertEqual(extent["direction"], "symmetric")
        self.assertEqual(extent["distance"], "Boss_Extrude1_D1")

    def test_2015_part_with_arcs(self):
        f = self.read(os.path.join(DOCS, "Part K.SLDPRT"))
        sk, ex = f[0].sketch, f[1]
        self.assertEqual((len(sk.lines) - len(sk.construction), len(sk.arcs)), (8, 8))
        self.assertEqual(len(sk.construction), 2)   # the centre rectangle's diagonals
        self.assertEqual(ex.kind, "boss")
        self.assertAlmostEqual(ex.depth_mm, 20.0)
        self.assertEqual(len(features.profile_loops(sk)), 1)  # the ring: outline with a hole

    def test_pre_2015_part_on_the_top_plane(self):
        f = self.read(os.path.join(SLIPPAD, "PCB_v1.SLDPRT"))
        sk = f[0].sketch
        self.assertEqual(len(sk.lines) - len(sk.construction), 4)
        normals = [p[0][2] for p in sk.planes]
        self.assertIn((0.0, -1.0, 0.0), [tuple(round(c, 9) + 0.0 for c in n) for n in normals])
        self.assertAlmostEqual(f[1].depth_mm, 1.0)

    def test_sketch_dimensions_and_relations(self):
        f = self.read(os.path.join(DOCS, "Part K.SLDPRT"))
        d = features.design("t", f, {})
        cons = d["features"][0]["sketch"]["constraints"]
        kinds = [c["type"] for c in cons]
        for k in ("radius", "horizontal", "vertical", "tangent", "equal", "point_on_curve"):
            self.assertIn(k, kinds)
        self.assertEqual(kinds.count("tangent"), 16)         # every corner arc meets its lines, both loops
        # the rectangle is centred: the origin (point 0) on both construction diagonals
        on = [c for c in cons if c["type"] == "point_on_curve" and c["p"] == 0]
        self.assertEqual(len(on), 2)
        # the outer loop is the inner one offset by D4, all the way round
        off = [c for c in cons if c.get("param") == "Sketch2_D4"]
        self.assertEqual(len(off), 4)
        self.assertEqual(kinds.count("concentric"), 4)
        names = {p["name"]: float(p["expr"]) for p in d["params"]}
        self.assertEqual(names["Sketch2_D3"], 3.0)
        self.assertEqual(names["Sketch2_D1"], 50.0)
        self.assertEqual(names["Sketch2_D2"], 150.0)
        self.assertEqual(names["Boss_Extrude1_D1"], 20.0)
        self.assertEqual(names["Sketch2_D4"], 3.0)

    def test_offset_becomes_a_solidcraft_offset(self):
        path = os.path.join(DOCS, "Part K.SLDPRT")
        if not os.path.isfile(path):
            self.skipTest("sample part not on this PC")
        from sw2sc import solidcraft, verify
        if not verify.find_cli():
            self.skipTest("solidcraft-cli not found")
        d, _rep = solidcraft.convert(path)
        sk = next(f for f in d["features"] if f["type"] == "sketch")["sketch"]
        self.assertEqual(len(sk.get("offsets", [])), 1)            # one offset, as in SolidWorks
        dims = [c for c in sk["constraints"] if c["type"] == "offset_distance"]
        self.assertEqual([c["param"] for c in dims], ["Sketch2_D4"])
        loop = next(f for f in d["features"] if f["type"] == "extrude")["profiles"]["loops"][0]
        self.assertTrue(set(loop) <= set(sk["offsets"][0]["outputs"]))

    def test_unconverted_features_keep_their_place(self):
        f = self.read(os.path.join(DOCS, "Part B.SLDPRT"))
        self.assertEqual([x.kind for x in f][:3], ["sketch", "boss", "tbd"])
        self.assertEqual(f[2].name, "Cavity1")


if __name__ == "__main__":
    unittest.main()


def test_face_moves_draft_and_offset():
    """A draft's faces, neutral plane and pull, and a move face's faces and side, found from where
    the faces end up in the part's own solid."""
    import math
    from sw2sc import verify
    from sw2sc.features import Feature
    t = math.radians(5)
    # a 20 x 20 x 10 box; its +x face drafted 5° about z = 0, pull +z
    faces = [{"plane_normal": [1.0, 0.0, 0.0], "point": [20.0, 10.0, 5.0]},
             {"plane_normal": [0.0, -1.0, 0.0], "point": [10.0, 0.0, 5.0]},
             {"plane_normal": [0.0, 0.0, 1.0], "point": [10.0, 10.0, 10.0]}]
    f = Feature("draft", "Draft1", 0, "moDraft_c", draft_deg=5.0)
    f.final_planes = [((math.cos(t), 0.0, math.sin(t)), (20.0, 10.0, 0.0)), ((0.0, -1.0, 0.0), (0.0, 0.0, 0.0))]
    got = verify.face_moves(f, faces, [0, 0, 0], [20, 20, 10])
    assert got[0] == ([[20.0, 10.0, 5.0]], [0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
    # the -y face moved 2 out
    g = Feature("moveface", "Move Face1", 0, "moMoveFace_c", move_mm=2.0)
    g.final_planes = [((0.0, -1.0, 0.0), (0.0, -2.0, 0.0)), ((1.0, 0.0, 0.0), (20.0, 0.0, 0.0))]
    got = verify.face_moves(g, faces, [0, 0, 0], [20, 20, 10])
    assert got[0] == ([[10.0, 0.0, 5.0]], 1)


def test_plane_record_flag_then_bare_minus_one():
    """A face plane reference with a 01 flag in its zero run and the id -1 straight after it
    (no FF block): read as a plane on a face."""
    from sw2sc.features import _plane_record
    b = b"\x16\x81" + b"\x83\x80\x02\x00" + bytes(29) + b"\x01" + bytes(11) + b"\xff" * 4 + b"\x00\x8d"
    assert _plane_record(b, 0, False) == (0xFFFFFFFF, len(b) - 2)
