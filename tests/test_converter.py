"""Run with:  python -m unittest discover -s tests
Sample-based tests skip when the (git-ignored) sample folders are absent."""
import glob
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sw2sc import geometry, model, nurbs, parasolid, roles, solidcraft, step, validate, vault, workflow, xtgeom  # noqa: E402
from sw2sc.swfile import SwFile  # noqa: E402


def import_tree(*args, **kwargs):
    """vault.import_tree as if SolidCraft weren't installed: each part keeps its imported solid
    and its feature tree isn't rebuilt. Every vault test imports through here: they test the
    vault (structure, links, roles, release), which the rebuild doesn't change; with it each part
    could take up to its 240 s search budget (the vault tests took hours), and a time-limited
    search can come out differently on a reimport. The rebuild has its own tests."""
    from unittest import mock
    with mock.patch("sw2sc.verify.find_cli", return_value=None):
        return vault.import_tree(*args, **kwargs)

SLIPPAD = os.path.join(ROOT, "samples", "slippad-solidworks")
GRABCAD = os.path.join(ROOT, "Solidworks Example Grabcad")


class TransformTests(unittest.TestCase):
    def test_metres_to_mm_and_layout(self):
        # SolidWorks: images of X, Y, Z then translation (metres).
        t = [0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1, 0, 0.01, 0.02, 0.03, 1]
        m = solidcraft._matrix(t)
        self.assertEqual(m[0][:3], [0, 1, 0])
        self.assertEqual(m[3], [10.0, 20.0, 30.0, 1.0])
        self.assertTrue(validate.is_placement(m))

    def test_mirror_rejected(self):
        m = [[-1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
        self.assertFalse(validate.is_placement(m))


class NurbsTests(unittest.TestCase):
    def test_sub_curve_matches_original(self):
        import math
        pts = [(math.cos(t / 10 * math.pi), math.sin(t / 10 * math.pi), t * 0.1) for t in range(11)]
        c = nurbs.interpolate(pts)
        s = c.sub(0.2, 0.7)
        lo, hi = s.domain
        for i in range(21):
            self.assertLess(math.dist(s(lo + (hi - lo) * i / 20), c(0.2 + 0.5 * i / 20)), 1e-12)

    def test_rational_sub_curve_stays_on_circle(self):
        import math
        w = math.sqrt(0.5)
        r = nurbs.Curve(2, [0, 0, 0, 1, 1, 1], [(1, 0, 0), (1, 1, 0), (0, 1, 0)], [1, w, 1])
        s = r.sub(0.25, 0.8)
        lo, hi = s.domain
        for i in range(11):
            self.assertAlmostEqual(math.hypot(*s(lo + (hi - lo) * i / 10)[:2]), 1.0, places=12)


class ColourTests(unittest.TestCase):
    def test_body_and_face_attributes(self):
        nodes = {
            1: parasolid.Node(79, "ATT_DEF_ID", 1, {"string": list("SDL/TYSA_COLOUR")}),
            2: parasolid.Node(80, "ATTRIB_DEF", 2, {"identifier": 1}),
            3: parasolid.Node(81, "ATTRIBUTE", 3, {"definition": 2, "fields": [4], "next": 5}),
            4: parasolid.Node(83, "REAL_VALUES", 4, {"values": [1.0, 0.0, 0.0]}),
            5: parasolid.Node(81, "ATTRIBUTE", 5, {"definition": 6, "fields": [7], "next": 0}),
            6: parasolid.Node(80, "ATTRIB_DEF", 6, {"identifier": 8}),
            7: parasolid.Node(83, "REAL_VALUES", 7, {"values": [0.0, 0.5, 1.0]}),
            8: parasolid.Node(79, "ATT_DEF_ID", 8, {"string": list("SDL/TYSA_COLOUR_2")}),
        }
        part = parasolid.Partition("test", "test", nodes, [])
        body = parasolid.Node(12, "BODY", 9, {"attributes_groups": 3})
        face = parasolid.Node(14, "FACE", 10, {"attributes_groups": 3})
        self.assertEqual(xtgeom._colour(part, body), (0.0, 0.5, 1.0))
        nodes[5] = parasolid.Node(81, "ATTRIBUTE", 5, {"definition": 0, "fields": [], "next": 0})
        self.assertEqual(xtgeom._colour(part, face), (1.0, 0.0, 0.0))

    def test_step_styles_body_and_face(self):
        face = xtgeom.Face(("plane", (0, 0, 0), (0, 0, 1), (1, 0, 0)), True, [],
                           colour=(0.0, 0.5, 1.0))
        body = xtgeom.Body("solid", [xtgeom.Shell([face], True)], colour=(1.0, 0.25, 0.0))
        text = step.write([body], "part")
        self.assertEqual(text.count("STYLED_ITEM("), 2)
        self.assertEqual(text.count("PRESENTATION_STYLE_ASSIGNMENT("), 2)
        self.assertIn("COLOUR_RGB('',1.0,0.25,0.0)", text)
        self.assertIn("COLOUR_RGB('',0.0,0.5,1.0)", text)


class ValidatorTests(unittest.TestCase):
    def test_bad_hidden_path(self):
        d = {"format": "solidcraft/28", "features": [], "next_id": 3,
             "components": [{"id": 1, "name": "A", "parent": 0}],
             "occurrences": [{"id": 2, "component": 1, "parent": 0, "name": "A:1",
                              "transform": solidcraft._matrix([])}],
             "visibility": {"hidden_occurrences": [[99]]}}
        self.assertTrue(any("hidden path" in p for p in validate.validate(d)))


@unittest.skipUnless(os.path.isdir(SLIPPAD), "Slip-Pad samples not downloaded")
class SlipPadTests(unittest.TestCase):
    def test_nested_assembly(self):
        design, rep = solidcraft.convert(os.path.join(SLIPPAD, "Assem4.SLDASM"))
        self.assertEqual(validate.validate(design), [])
        self.assertEqual(rep.stats["components"], 39)
        self.assertEqual(rep.stats["occurrences"], 82)
        # A subassembly's parts sit inside the subassembly's component.
        comps = {c["id"]: c["name"] for c in design["components"]}
        bobbin = [k for k, v in comps.items() if v == "Bobbin_assem_v2"][0]
        inside = {comps[o["component"]] for o in design["occurrences"] if o["parent"] == bobbin}
        self.assertIn("bearing_3x6x2", inside)

    def test_placements_match_solidworks_bounds(self):
        d = model.load(os.path.join(SLIPPAD, "idler_assem_v2.SLDASM"))
        t = d.tree
        pts = []
        for r in t.models[t.root].refs:
            b = t.models[r.model_ref].bbox
            for x in (b[0], b[3]):
                for y in (b[1], b[4]):
                    for z in (b[2], b[5]):
                        tr = r.transform
                        pts.append([tr[i] * x + tr[4 + i] * y + tr[8 + i] * z + tr[12 + i] for i in range(3)])
        lo = [min(p[i] for p in pts) for i in range(3)]
        hi = [max(p[i] for p in pts) for i in range(3)]
        for a, b in zip(lo + hi, t.models[t.root].bbox):
            self.assertAlmostEqual(a, b, places=9)

    def test_bearing_geometry(self):
        sw = SwFile(os.path.join(SLIPPAD, "bearing_3x6x2.SLDPRT"))
        part = parasolid.read(geometry.parasolid_sources(sw)[0][1])
        self.assertEqual(len(part.of_type("FACE")), 4)
        text, warnings, stats = geometry.part_to_step(sw, "bearing")
        self.assertEqual(stats, {"bodies": 1, "faces": 4, "approx_faces": 0, "faces_left_out": 0})
        self.assertEqual(text.count("MANIFOLD_SOLID_BREP"), 1)
        self.assertEqual(text.count("CYLINDRICAL_SURFACE"), 2)
        self.assertIn(",1.5)", text)  # 3 mm bore, in millimetres
        self.assertEqual(text.count("STYLED_ITEM("), 4)
        self.assertEqual(text.count("COLOUR_RGB(''"), 1)
        self.assertIn("COLOUR_RGB('',0.792156862745098,0.8196078431372549,0.9333333333333333)", text)

    def test_design_carries_import_features(self):
        design, rep = solidcraft.convert(os.path.join(SLIPPAD, "idler_assem_v2.SLDASM"))
        imports = [f for f in design["features"] if f["type"] == "import"]
        self.assertEqual(len(imports), 4)  # four distinct parts, five placements
        self.assertTrue(all(f["step"].startswith("ISO-10303-21;") for f in imports))
        self.assertEqual(validate.validate(design), [])

    def test_part_feature_tree_and_material(self):
        d = model.load(os.path.join(SLIPPAD, "Base_loadCell_v1.SLDPRT"))
        self.assertEqual(d.material, "Acrylic (Medium-high impact)")
        self.assertEqual([f.name for f in d.features][:3], ["Sketch1", "Boss-Extrude1", "Fillet1"])


@unittest.skipUnless(os.path.isdir(SLIPPAD), "Slip-Pad samples not downloaded")
class VaultTests(unittest.TestCase):
    """Imports a small copy of the Slip-Pad tree (one assembly and its parts)."""

    def setUp(self):
        import shutil
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "src")
        os.makedirs(os.path.join(self.src, "parts"))
        for f in ("arm_idler_v2", "idler_single_v1", "shaft_3x22mm", "shaft_3x55mm"):
            shutil.copy(os.path.join(SLIPPAD, f + ".SLDPRT"), os.path.join(self.src, "parts"))
        shutil.copy(os.path.join(SLIPPAD, "idler_assem_v2.SLDASM"), self.src)
        with open(os.path.join(self.src, "notes.txt"), "w") as fh:
            fh.write("kept as is")
        self.vault = os.path.join(self.tmp, "vault")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_import(self):
        return import_tree(self.src, self.vault, log=lambda *_: None)

    def test_assembly_links_to_part_designs_in_subfolder(self):
        import json
        r = self.run_import()
        self.assertEqual((r.converted, len(r.failed), r.copied), (5, 0, 1))
        with open(os.path.join(self.vault, "idler_assem_v2.sldasm.solidcraft"), encoding="utf-8") as fh:
            d = json.load(fh)
        paths = sorted(link["path"] for link in d["links"].values())
        self.assertEqual(paths, ["parts/arm_idler_v2.sldprt.solidcraft", "parts/idler_single_v1.sldprt.solidcraft",
                                 "parts/shaft_3x22mm.sldprt.solidcraft", "parts/shaft_3x55mm.sldprt.solidcraft"])
        for link in d["links"].values():
            self.assertEqual(link["file_sha256"], vault.sha256_file(os.path.join(self.vault, link["path"])))
        self.assertEqual(validate.validate(d), [])
        self.assertTrue(os.path.isfile(os.path.join(self.vault, "notes.txt")))

    def test_where_used_and_bom(self):
        self.run_import()
        used = vault.where_used(self.vault, "idler_single_v1")
        self.assertEqual(used, [(1, "idler_assem_v2.sldasm.solidcraft", 2)])
        rows = {item: qty for _, item, qty, _ in vault.bom(self.vault, "idler_assem_v2")}
        self.assertEqual(rows["parts/idler_single_v1.sldprt.solidcraft"], 2)
        self.assertEqual(len(rows), 4)

    def test_reimport_converts_only_what_changed(self):
        import shutil
        import subprocess
        self.run_import()
        r = self.run_import()
        self.assertEqual((r.converted, r.unchanged, r.commit), (0, 5, None))
        shutil.copy(os.path.join(SLIPPAD, "shaft_3x55mm.SLDPRT"), os.path.join(self.src, "parts", "shaft_3x22mm.SLDPRT"))
        r = self.run_import()
        self.assertEqual((r.converted, r.unchanged), (2, 3))  # the part and the assembly using it
        if r.commit:
            log = subprocess.run(["git", "-C", self.vault, "log", "--oneline"], capture_output=True, text=True).stdout
            self.assertEqual(len(log.strip().splitlines()), 2)


class RevisionLabelTests(unittest.TestCase):
    def test_next_revision(self):
        for a, b in (("A", "B"), ("Z", "AA"), ("AZ", "BA"), ("3", "4"), ("09", "10"), ("1.2", "1.3"), ("", "A"), ("x", "x.1")):
            self.assertEqual(workflow.next_revision(a), b)


@unittest.skipUnless(os.path.isdir(SLIPPAD), "Slip-Pad samples not downloaded")
class WorkflowTests(unittest.TestCase):
    """The idler assembly and its four parts, released and then changed."""

    PARTS = ("arm_idler_v2", "idler_single_v1", "shaft_3x22mm", "shaft_3x55mm")

    def setUp(self):
        import shutil
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "src")
        os.makedirs(self.src)
        for f in self.PARTS:
            shutil.copy(os.path.join(SLIPPAD, f + ".SLDPRT"), self.src)
        shutil.copy(os.path.join(SLIPPAD, "idler_assem_v2.SLDASM"), self.src)
        self.vault = os.path.join(self.tmp, "vault")
        import_tree(self.src, self.vault, log=lambda *_: None)
        self.asm = "idler_assem_v2.sldasm.solidcraft"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def release(self, item):
        workflow.change(self.vault, item, "submit", "tester")
        return workflow.change(self.vault, item, "release", "tester", "ok")

    def state(self, item):
        w = workflow.status(self.vault)[item]
        return w["state"], w["revision"]

    def test_new_items_start_in_work(self):
        self.assertEqual(self.state(self.asm), (workflow.IN_WORK, "A"))

    def test_assembly_needs_its_parts_released(self):
        workflow.change(self.vault, self.asm, "submit", "tester")
        with self.assertRaises(workflow.WorkflowError) as e:
            workflow.change(self.vault, self.asm, "release", "tester")
        self.assertIn("shaft_3x22mm.sldprt.solidcraft", str(e.exception))
        for p in self.PARTS:
            self.release(p + ".sldprt.solidcraft")
        workflow.change(self.vault, self.asm, "release", "tester", "ok")
        self.assertEqual(self.state(self.asm), (workflow.RELEASED, "A"))

    def test_wrong_moves_are_refused(self):
        with self.assertRaises(workflow.WorkflowError):
            workflow.change(self.vault, self.asm, "release", "tester")  # not In Review
        workflow.change(self.vault, self.asm, "submit", "tester")
        with self.assertRaises(workflow.WorkflowError):
            workflow.change(self.vault, self.asm, "reject", "tester")  # needs a reason
        workflow.change(self.vault, self.asm, "reject", "tester", "hole in the wrong place")
        self.assertEqual(self.state(self.asm), (workflow.IN_WORK, "A"))

    def test_change_after_release_starts_next_revision_and_release_comes_back(self):
        import hashlib
        import shutil
        for p in self.PARTS:
            self.release(p + ".sldprt.solidcraft")
        workflow.change(self.vault, self.asm, "submit", "tester")
        workflow.change(self.vault, self.asm, "release", "tester", "first")
        shaft = "shaft_3x22mm.sldprt.solidcraft"
        released = workflow.status(self.vault)[shaft]["releases"][0]["design_sha256"]
        shutil.copy(os.path.join(SLIPPAD, "shaft_3x55mm.SLDPRT"), os.path.join(self.src, "shaft_3x22mm.SLDPRT"))
        import_tree(self.src, self.vault, log=lambda *_: None)
        self.assertEqual(self.state(shaft), (workflow.IN_WORK, "B"))
        self.assertEqual(self.state(self.asm), (workflow.IN_WORK, "B"))  # it contains the changed shaft
        self.assertEqual(self.state("arm_idler_v2.sldprt.solidcraft"), (workflow.RELEASED, "A"))
        if workflow.status(self.vault)[self.asm]["releases"][0].get("tag"):
            out = os.path.join(self.tmp, "rev-a")
            files = workflow.get_release(self.vault, self.asm, "A", out)
            self.assertEqual(len(files), 5)
            with open(os.path.join(out, shaft), "rb") as fh:
                self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), released)


@unittest.skipUnless(os.path.isdir(SLIPPAD), "Slip-Pad samples not downloaded")
class TreeReleaseTests(unittest.TestCase):
    """Releasing an assembly with everything it contains (the Slip-Pad tree under Assem4)."""

    def setUp(self):
        import shutil
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "src")
        shutil.copytree(SLIPPAD, self.src, ignore=shutil.ignore_patterns(".git"))
        self.vault = os.path.join(self.tmp, "vault")
        import_tree(self.src, self.vault, keep_originals=False, log=lambda *_: None)
        self.top = "Assem4.sldasm.solidcraft"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, *args):
        import subprocess
        return subprocess.run(["git", "-C", self.vault, *args], capture_output=True, text=True).stdout

    def test_parts_come_before_the_assemblies_that_use_them(self):
        plan = workflow.plan_tree(self.vault, self.top, "release")
        order = [s["item"] for s in plan["steps"]]
        self.assertEqual(len(order), 40)
        self.assertEqual(order[-1], self.top)
        index = vault._load_index(self.vault)["items"]
        for k in order:
            for u in index[k].get("uses", []):
                self.assertLess(order.index(u["item"]), order.index(k), f"{u['item']} after {k}")

    def test_release_all_in_one_commit_then_only_what_changed(self):
        import shutil
        commits = len(self.git("log", "--oneline").splitlines())
        workflow.change_tree(self.vault, self.top, "release", "tester", "rev A")
        self.assertTrue(all(w["state"] == workflow.RELEASED for w in workflow.status(self.vault).values()))
        if commits:
            self.assertEqual(len(self.git("log", "--oneline").splitlines()), commits + 1)
            self.assertEqual(len(self.git("tag").splitlines()), 40)
        with self.assertRaises(workflow.WorkflowError):
            workflow.change_tree(self.vault, self.top, "release", "tester")  # nothing left to do
        shutil.copy(os.path.join(SLIPPAD, "shaft_3x55mm.SLDPRT"), os.path.join(self.src, "shaft_3x22mm.SLDPRT"))
        import_tree(self.src, self.vault, keep_originals=False, log=lambda *_: None)
        plan = workflow.change_tree(self.vault, self.top, "release", "tester", "rev B")
        self.assertEqual({s["item"] for s in plan["steps"]},
                         {"shaft_3x22mm.sldprt.solidcraft", "idler_assem_v2.sldasm.solidcraft",
                          "Bobbin_independent_assem_v2.sldasm.solidcraft", self.top})
        self.assertEqual(len(plan["skip"]), 36)
        self.assertEqual(workflow.status(self.vault)[self.top]["revision"], "B")

    def test_one_blocker_changes_nothing(self):
        data = workflow.load(self.vault)
        data["items"]["bearing_3x6x2.sldprt.solidcraft"]["state"] = workflow.OBSOLETE
        workflow.save(self.vault, data)
        before = workflow.status(self.vault)
        with self.assertRaises(workflow.WorkflowError) as e:
            workflow.change_tree(self.vault, self.top, "release", "tester")
        self.assertIn("bearing_3x6x2", str(e.exception))
        self.assertEqual(workflow.status(self.vault), before)

    def test_submit_all_then_release_all(self):
        workflow.change_tree(self.vault, "idler_assem_v2.sldasm.solidcraft", "submit", "tester")
        states = {k: w["state"] for k, w in workflow.status(self.vault).items()}
        self.assertEqual(states["idler_assem_v2.sldasm.solidcraft"], workflow.IN_REVIEW)
        self.assertEqual(states["shaft_3x22mm.sldprt.solidcraft"], workflow.IN_REVIEW)
        self.assertEqual(states["bearing_3x6x2.sldprt.solidcraft"], workflow.IN_WORK)  # not in the idler
        plan = workflow.plan_tree(self.vault, "idler_assem_v2.sldasm.solidcraft", "release")
        self.assertEqual({s["do"] for s in plan["steps"]}, {"release"})


@unittest.skipUnless(os.path.isdir(SLIPPAD), "Slip-Pad samples not downloaded")
class RolesTests(unittest.TestCase):
    """Who may release: the idler assembly and its parts, with three people."""

    BOB, JANE, MAL = "pc\\bob", "pc\\jane", "pc\\mallory"

    def setUp(self):
        import shutil
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "src")
        os.makedirs(self.src)
        for f in ("arm_idler_v2", "idler_single_v1", "shaft_3x22mm", "shaft_3x55mm"):
            shutil.copy(os.path.join(SLIPPAD, f + ".SLDPRT"), self.src)
        shutil.copy(os.path.join(SLIPPAD, "idler_assem_v2.SLDASM"), self.src)
        self.vault = os.path.join(self.tmp, "vault")
        import_tree(self.src, self.vault, keep_originals=False, log=lambda *_: None)
        self.shaft = "shaft_3x22mm.sldprt.solidcraft"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_open_vault_lets_anyone_release(self):
        self.assertIsNone(roles.load(self.vault))
        workflow.change(self.vault, self.shaft, "submit", self.MAL)
        workflow.change(self.vault, self.shaft, "release", self.MAL)
        self.assertEqual(workflow.status(self.vault)[self.shaft]["state"], workflow.RELEASED)

    def test_first_edit_makes_an_admin_and_only_approvers_release(self):
        r = roles.edit(self.vault, self.BOB, "add-approver", self.JANE)
        self.assertEqual((r["admins"], r["approvers"]), ([self.BOB], [self.JANE]))
        workflow.change(self.vault, self.shaft, "submit", self.BOB)  # anyone may submit
        with self.assertRaises(workflow.WorkflowError):
            workflow.change(self.vault, self.shaft, "release", self.BOB)  # admin, but not approver
        with self.assertRaises(workflow.WorkflowError):
            workflow.change(self.vault, self.shaft, "reject", self.MAL, "no")
        workflow.change(self.vault, self.shaft, "release", "PC\\Jane")  # accounts compare without case
        w = workflow.status(self.vault)[self.shaft]
        self.assertEqual((w["state"], w["history"][-1]["by"]), (workflow.RELEASED, self.JANE))

    def test_only_admins_change_roles_and_one_admin_stays(self):
        roles.edit(self.vault, self.BOB, "add-approver", self.JANE)
        with self.assertRaises(roles.RolesError):
            roles.edit(self.vault, self.MAL, "add-approver", self.MAL)
        with self.assertRaises(roles.RolesError):
            roles.edit(self.vault, self.BOB, "remove-admin", self.BOB)
        roles.edit(self.vault, self.BOB, "add-admin", self.JANE)
        roles.edit(self.vault, self.JANE, "remove-admin", self.BOB)
        self.assertEqual(roles.load(self.vault)["admins"], [self.JANE])

    def test_four_eyes(self):
        roles.edit(self.vault, self.BOB, "add-approver", self.BOB)
        roles.edit(self.vault, self.BOB, "add-approver", self.JANE)
        roles.edit(self.vault, self.BOB, "four-eyes", "", True)
        workflow.change(self.vault, self.shaft, "submit", self.BOB)
        with self.assertRaises(workflow.WorkflowError):
            workflow.change(self.vault, self.shaft, "release", self.BOB)
        workflow.change(self.vault, self.shaft, "release", self.JANE)
        # a whole-assembly release can't submit and release in one go under four-eyes
        plan = workflow.plan_tree(self.vault, "idler_assem_v2.sldasm.solidcraft", "release", self.JANE)
        self.assertTrue(any("four-eyes" in b for b in plan["blockers"]))
        workflow.change_tree(self.vault, "idler_assem_v2.sldasm.solidcraft", "submit", self.BOB)
        with self.assertRaises(workflow.WorkflowError):
            workflow.change_tree(self.vault, "idler_assem_v2.sldasm.solidcraft", "release", self.BOB)
        workflow.change_tree(self.vault, "idler_assem_v2.sldasm.solidcraft", "release", self.JANE)
        self.assertEqual(workflow.status(self.vault)["idler_assem_v2.sldasm.solidcraft"]["state"], workflow.RELEASED)

    def test_damaged_roles_file_blocks_release(self):
        with open(os.path.join(self.vault, roles.ROLES), "w") as fh:
            fh.write("{ not json")
        workflow.change(self.vault, self.shaft, "submit", self.BOB)
        with self.assertRaises(workflow.WorkflowError):
            workflow.change(self.vault, self.shaft, "release", self.BOB)


class GuiServerTests(unittest.TestCase):
    """The vault window's server: only this PC, only with the run's token."""

    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import ThreadingHTTPServer
        from sw2sc import gui
        cls.token = "test-token"
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), gui.make_handler(cls.token, gui.Job()))
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def get(self, path, token=None, host=None):
        import urllib.error
        import urllib.request
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        if token:
            req.add_header("X-Token", token)
        if host:
            req.add_header("Host", host)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_page_needs_the_token(self):
        self.assertEqual(self.get("/")[0], 403)
        code, body = self.get(f"/?t={self.token}")
        self.assertEqual(code, 200)
        self.assertIn(b"Import a folder", body)
        self.assertNotIn(b"__TOKEN__", body)

    def test_api_refuses_wrong_token_and_other_hosts(self):
        self.assertEqual(self.get("/api/settings")[0], 403)
        self.assertEqual(self.get("/api/settings", "wrong")[0], 403)
        self.assertEqual(self.get("/api/settings", self.token, "evil.example")[0], 403)
        self.assertEqual(self.get("/api/settings", self.token)[0], 200)

    def post(self, path, body):
        import json
        import urllib.error
        import urllib.request
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body).encode(),
                                     headers={"X-Token": self.token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_open_only_opens_designs_the_vault_lists(self):
        import json
        import tempfile
        from unittest import mock
        from sw2sc import gui
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, vault.INDEX), "w", encoding="utf-8") as fh:
                json.dump({"items": {"a.sldprt.solidcraft": {"type": "part", "name": "a"}}}, fh)
            with open(os.path.join(d, "a.sldprt.solidcraft"), "w") as fh:
                fh.write("{}")
            with mock.patch.object(gui, "open_in_solidcraft") as opened:
                code, _ = self.post("/api/open", {"vault": d, "item": "..\\..\\x.exe"})
                self.assertEqual(code, 404)
                opened.assert_not_called()
                code, _ = self.post("/api/open", {"vault": d, "item": "a.sldprt.solidcraft"})
                self.assertEqual(code, 200)
                opened.assert_called_once_with(os.path.join(d, "a.sldprt.solidcraft"))

    def test_newest_solidcraft_is_preferred(self):
        from unittest import mock
        from sw2sc import gui
        old = r"C:\Program Files\SolidCraft\solidcraft.exe"
        new = r"C:\dev\solidcraft\target\release\solidcraft.exe"
        with mock.patch.object(gui, "load_settings", return_value={}),                 mock.patch.object(gui.shutil, "which", return_value=old),                 mock.patch.object(gui.os.path, "isfile", side_effect=lambda f: f in (old, new)),                 mock.patch.object(gui, "app_version", side_effect=lambda f: (0, 40, 1) if f == new else (0, 30, 1)):
            self.assertEqual(gui.find_solidcraft(), new)
        with mock.patch.object(gui, "load_settings", return_value={"solidcraft": old}),                 mock.patch.object(gui.os.path, "isfile", return_value=True):
            self.assertEqual(gui.find_solidcraft(), old)  # a path you set wins

    def test_open_goes_to_a_running_solidcraft(self):
        import json
        import socket
        import tempfile
        import threading
        from unittest import mock
        from sw2sc import gui

        def fake_app(reply):
            srv = socket.socket()
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            got = {}

            def serve():
                conn, _ = srv.accept()
                with conn:
                    got["request"] = json.loads(conn.makefile("r").readline())
                    conn.sendall((json.dumps(reply) + "\n").encode())
                srv.close()
            threading.Thread(target=serve, daemon=True).start()
            return srv.getsockname()[1], got

        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"SOLIDCRAFT_CONTROL_DIR": d}):
            self.assertFalse(gui.open_in_running_solidcraft("x.solidcraft"))  # no app running
            for reply, opened in (({"id": 1, "ok": True}, True),
                                  ({"ok": False, "error": "unauthorized: send the control token"}, False)):
                port, got = fake_app(reply)
                for name, text in (("current.port", str(port)), (f"{port}.token", "t0k")):
                    with open(os.path.join(d, name), "w") as fh:
                        fh.write(text)
                self.assertEqual(gui.open_in_running_solidcraft("x.solidcraft"), opened)
                self.assertEqual(got["request"]["token"], "t0k")
                self.assertEqual(got["request"]["params"],
                                 {"command": "doc.open", "params": {"path": os.path.abspath("x.solidcraft")}})
            with mock.patch.object(gui, "open_in_running_solidcraft", return_value=True) as running,                     mock.patch.object(gui.subprocess, "Popen") as started:
                gui.open_in_solidcraft("x.solidcraft")
                running.assert_called_once()
                started.assert_not_called()

    def test_vault_view_reads_the_index(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, vault.INDEX), "w", encoding="utf-8") as fh:
                json.dump({"items": {"a.sldprt.solidcraft": {"type": "part", "name": "a"}}}, fh)
            from urllib.parse import quote
            code, body = self.get("/api/vault?path=" + quote(d), self.token)
            self.assertEqual(code, 200)
            self.assertEqual(json.loads(body)["items"]["a.sldprt.solidcraft"]["name"], "a")


@unittest.skipUnless(os.path.isdir(SLIPPAD), "Slip-Pad samples not downloaded")
class SubassemblyVaultTests(unittest.TestCase):
    """The Slip-Pad tree: Assem4 nests four subassemblies."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.tmp = tempfile.mkdtemp()
        cls.vault = os.path.join(cls.tmp, "vault")
        cls.result = import_tree(SLIPPAD, cls.vault, keep_originals=False, use_git=False, log=lambda *_: None)

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def load(self, name):
        import json
        with open(os.path.join(self.vault, name), encoding="utf-8") as fh:
            return json.load(fh)

    def test_subassemblies_are_links(self):
        self.assertEqual(self.result.failed, [])
        d = self.load("Assem4.sldasm.solidcraft")
        paths = {link["path"] for link in d["links"].values()}
        self.assertIn("Bobbin_assem_v2.sldasm.solidcraft", paths)
        self.assertIn("modular_top_assem_v2.sldasm.solidcraft", paths)
        for link in d["links"].values():
            self.assertEqual(link["file_sha256"], vault.sha256_file(os.path.join(self.vault, link["path"])))
        self.assertEqual(validate.validate(d), [])
        # the linked subassembly's parts are not repeated as components of the top assembly
        self.assertNotIn("bearing_3x6x2", {c["name"] for c in d["components"]})

    def test_subassembly_geometry_places_every_visible_part(self):
        from sw2sc import stepasm
        d = self.load("Assem4.sldasm.solidcraft")
        bobbin = next(f for f in d["features"] if f["type"] == "import" and f["name"] == "Bobbin_assem_v2")
        self.assertEqual(bobbin["step"].count("MAPPED_ITEM("), 9)  # 9 instances in Bobbin_assem_v2
        self.assertEqual(bobbin["step"].count("REPRESENTATION_MAP("), 5)  # 5 distinct parts
        inner = self.load("Bobbin_assem_v2.sldasm.solidcraft")
        self.assertEqual(len(stepasm.leaf_placements(inner, lambda link: None)), 9)

    def test_bom_multiplies_through_levels(self):
        rows = {item: qty for level, item, qty, _ in vault.bom(self.vault, "Assem4") if level == 2}
        self.assertEqual(rows["bearing_3x6x2.sldprt.solidcraft"], 16)  # 4 bobbin assemblies x 4 bearings


@unittest.skipUnless(os.path.isdir(GRABCAD), "GrabCAD samples not present")
class GrabCadTests(unittest.TestCase):
    def test_every_file_converts_and_validates(self):
        files = [f for f in glob.glob(os.path.join(GRABCAD, "**", "*"), recursive=True)
                 if f.lower().endswith((".sldprt", ".sldasm"))]
        self.assertGreater(len(files), 100)
        for f in files:
            with self.subTest(f=os.path.basename(f)):
                design, _ = solidcraft.convert(f, None, False)
                self.assertEqual(validate.validate(design), [])


if __name__ == "__main__":
    unittest.main()
