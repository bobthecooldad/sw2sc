import copy
import os
import tempfile
import unittest
from unittest import mock

from tools import render_compare


class RenderCompareTests(unittest.TestCase):
    def test_output_is_ignored_safe_and_distinct_for_duplicate_names(self):
        one = render_compare.image_folder("folder/Part A.sldprt", "out/check-images")
        two = render_compare.image_folder("other/Part A.sldprt", "out/check-images")
        self.assertNotEqual(one, two)
        self.assertIn("Part_A", os.path.basename(one))
        self.assertNotIn("folder", os.path.basename(one))

    def test_import_only_design_is_not_a_feature_rebuild(self):
        imported = {"format": "solidcraft/55", "features": [{"type": "import", "step": "saved solid"}]}
        self.assertFalse(render_compare.feature_rebuild(imported))
        self.assertFalse(render_compare.feature_rebuild(copy.deepcopy(imported)))
        self.assertFalse(render_compare.feature_rebuild({"features": [{"type": "extrude", "suppressed": True}]}))
        self.assertFalse(render_compare.feature_rebuild({"features": [{"type": "extrude"}], "pending": "Fillet1"}))

    def test_fallback_cannot_be_rendered_as_the_rebuild(self):
        imported = {"format": "solidcraft/55", "features": [{"type": "import", "step": "saved solid"}]}
        with tempfile.TemporaryDirectory() as out, mock.patch("subprocess.run") as run:
            self.assertIsNone(render_compare.render_part("part.sldprt", out, copy.deepcopy(imported), imported, "cli"))
            run.assert_not_called()

    def test_skipping_a_rebuild_removes_its_stale_comparison(self):
        imported = {"features": [{"type": "import"}]}
        with tempfile.TemporaryDirectory() as out:
            folder = render_compare.image_folder("part.sldprt", out)
            os.makedirs(folder)
            old = os.path.join(folder, "comparison.png")
            open(old, "wb").close()
            self.assertIsNone(render_compare.render_part("part.sldprt", out, imported, imported, "cli"))
            self.assertFalse(os.path.exists(old))


if __name__ == "__main__":
    unittest.main()
