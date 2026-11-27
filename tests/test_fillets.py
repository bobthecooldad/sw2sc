import glob
import os
import unittest

from sw2sc import features, fillets


def box_edges():
    """A 4-sided extrude (feature 2, sketch curves l1..l4, l1 meeting l2, l2 l3, l3 l4, l4 l1):
    its edges as SolidCraft names them."""
    names = []
    for a, b in (("l1", "l2"), ("l2", "l3"), ("l3", "l4"), ("l4", "l1")):
        names.append(f"F2:side:{a}|F2:side:{b}")
    for c in ("l1", "l2", "l3", "l4"):
        names += [f"F2:side:{c}|F2:top", f"F2:side:{c}|F2:start"]
    return [(fillets._faces(n), [0.0, 0.0, 0.0], n) for n in names]


class SolverTests(unittest.TestCase):
    def test_names_parse(self):
        self.assertEqual(fillets._faces("F2:side:l8#[F2:side:l25,F2:side:l7]|F2:start"),
                         (("side", 2, "l8"), ("end", 2, "start")))
        self.assertEqual(fillets._faces("F2:top|F3:blend(F2:side:l1|F2:side:l4)"),
                         (("end", 2, "top"), ("blend", 3, "F2:side:l1|F2:side:l4")))

    def test_corner_and_its_top_edge_share_an_entity(self):
        # SolidWorks: the corner between entities 7 and 8, and the top edge along entity 8
        sw = [(("side", 50, 7), ("side", 50, 8)), (("end", 50, 1), ("side", 50, 8))]
        sols = fillets.solve(sw, box_edges(), {50: 2}, {2: ["l1", "l2", "l3", "l4"]})
        self.assertTrue(sols)
        for edges, amaps in sols:
            corner, top = edges[0][1], edges[1][1]
            side = top.split("|")[0]                 # the top edge's side is one of the corner's
            self.assertIn(side, corner)

    def test_swapped_entities_both_kept(self):
        # one corner: entities 7/8 can be l1/l2 or l2/l1; a later fillet may need either
        sw = [(("side", 50, 7), ("side", 50, 8))]
        sols = fillets.solve(sw, box_edges(), {50: 2}, {2: ["l1", "l2", "l3", "l4"]})
        corner = [s for s in sols if s[0][0][1] == "F2:side:l1|F2:side:l2"][0]
        self.assertEqual(len(corner[1]), 2)

    def test_impossible_selection_finds_nothing(self):
        # three side faces can't all meet the same entity's face on a 4-sided box... twice over
        sw = [(("side", 50, 7), ("side", 50, 8)), (("side", 50, 8), ("side", 50, 9)),
              (("side", 50, 9), ("side", 50, 7))]
        self.assertEqual(fillets.solve(sw, box_edges(), {50: 2}, {2: ["l1", "l2", "l3", "l4"]}), [])

    def test_edge_group_allows_wide_reference_spacing(self):
        b = bytearray(300)
        b[10:18] = features._GROUP_HEAD
        raw = [(1, 2, 3, 4, o) for o in (40, 84, 128, 178)]
        self.assertEqual(features._edge_groups(b, raw, 0, len(b)), raw)

    def test_edge_group_skips_a_header_shaped_reference_prefix(self):
        b = bytearray(300)
        b[10:18] = features._GROUP_HEAD
        b[100:108] = features._GROUP_HEAD
        raw = [(1, 2, 3, 4, o) for o in (130, 174, 218, 262)]
        self.assertEqual(features._edge_groups(b, [(9, 9, 9, 9, 12)] + raw, 0, len(b)), raw)


class FilletWriterTests(unittest.TestCase):
    def test_only_the_file_selected_edges_are_blended(self):
        feats = [features.Feature("fillet", "Fillet1", 0, features.FILLET, radius_mm=0.15)]
        picked = {"Fillet1": [([0, 0, 0], "edge")]}
        design = features.design("Part", feats, {}, None, True, picked)
        self.assertIs(design["features"][-1]["tangent_chain"], False)


class ReadTests(unittest.TestCase):
    def part(self, name):
        hits = [h for r in (r"C:\Solidworks to Solidcraft\samples", r"C:\Solidworks to Solidcraft\out\vault-grabcad")
                for h in glob.glob(os.path.join(r, "**", name + ".SLDPRT"), recursive=True)]
        if not hits:
            self.skipTest("sample part not on this PC")
        from sw2sc.swfile import SwFile
        return features.read(SwFile(hits[0]))

    def test_fillets_and_the_one_the_numbering_missed(self):
        fs = self.part("PartT8")
        fl = [f for f in fs if f.kind == "fillet"]
        self.assertEqual([(f.name, len(f.edges), f.radius_mm) for f in fl],
                         [("Fillet1", 60, 0.15), ("Fillet2", 12, 0.15)])
        # Fillet2 is found by its name (KeyWords): the record numbering had drifted there. It
        # rounds the cut-out's top and bottom edges (entities 1-4) and the two holes' (29, 30)
        self.assertEqual({r[2] for e in fl[1].edges for r in e if r[0] == "side"}, {1, 2, 3, 4, 29, 30})

    def test_chamfer_distance_angle_and_edges(self):
        fs = self.part("Top_beltSupportRim_v1")
        ch = [f for f in fs if f.kind == "chamfer"]
        self.assertEqual([(f.name, f.radius_mm, round(f.chamfer_deg, 6), len(f.edges)) for f in ch],
                         [("Chamfer1", 0.75, 70.0, 8)])

    def test_handle_class_brought_in_inline_under_a_drifted_tag(self):
        # Sketch6: four circles on a centre rectangle's corners; the circles' handle class is
        # brought in inline, then used by a tag the record numbering doesn't give it
        fs = self.part("Top_beltSupportRim_v1")
        s = next(f for f in fs if f.name == "Sketch6").sketch
        self.assertEqual(sorted(round(r * 1000, 6) for _c, r in s.circles), [1.1] * 4)

    def test_hole_wizard_countersink(self):
        fs = self.part("Top_modular_aperture_v2")
        h = next(f for f in fs if f.kind == "hole")
        self.assertEqual(h.hole, {"diameter": 3.2, "depth": 3.0, "cs_diameter": 6.3, "cs_angle": 90.0})
        place = next(f for f in fs if f.name == h.profile).sketch
        self.assertEqual(len(place.points), 4)                       # four holes
        self.assertLess([f.name for f in fs].index(h.profile), [f.name for f in fs].index(h.name))
        # the circles in Sketch6 use a handle tag of no known class: one point each, so circles
        s6 = next(f for f in fs if f.name == "Sketch6").sketch
        self.assertEqual(len(s6.circles), 4)

    def test_selection_ends_where_the_result_starts(self):
        fs = self.part("idler_differential_arm_short_v1")
        self.assertEqual([len(f.edges) for f in fs if f.kind == "fillet"], [3, 30])


if __name__ == "__main__":
    unittest.main()
