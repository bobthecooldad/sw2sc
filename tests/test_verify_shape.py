import json
import os
import tempfile
import unittest
from unittest import mock

from sw2sc import features, verify


def box(move=0.0):
    from tests.test_features import sketch
    sk = sketch({1: (0, 0), 2: (10, 0), 3: (10, 10), 4: (0, 10)},
                lines=[(1, 2), (2, 3), (3, 4), (4, 1)])
    sk.name = "Sketch1"
    feats = [features.Feature("sketch", "Sketch1", 0, features.SKETCH, sketch=sk),
             features.Feature("boss", "Boss-Extrude1", 1, features.BOSS, profile="Sketch1", depth_mm=10.0)]
    if move:
        feats.append(features.Feature("move", "Move", 2, "moMoveCopyBody_c", translate=(move, 0.0, 0.0)))
    return features.design("Box", feats, {})


def write(path, design):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(design, fh)


class ShapeDifferenceTests(unittest.TestCase):
    def test_identical_solids_pass_and_a_shifted_solid_fails(self):
        cli = verify.find_cli()
        if not cli:
            self.skipTest("solidcraft-cli not found")
        with tempfile.TemporaryDirectory() as tmp:
            reference = os.path.join(tmp, "reference.solidcraft")
            same = os.path.join(tmp, "same.solidcraft")
            shifted = os.path.join(tmp, "shifted.solidcraft")
            write(reference, box())
            write(same, box())
            write(shifted, box(20.0))
            self.assertTrue(verify.same_shape(cli, reference, same))
            self.assertFalse(verify.same_shape(cli, reference, shifted))

    def test_rebuild_cannot_accept_when_the_shape_check_fails(self):
        cli = verify.find_cli()
        if not cli:
            self.skipTest("solidcraft-cli not found")
        from tests.test_features import sketch
        sk = sketch({1: (0, 0), 2: (10, 0), 3: (10, 10), 4: (0, 10)},
                    lines=[(1, 2), (2, 3), (3, 4), (4, 1)])
        sk.name = "Sketch1"
        feats = [features.Feature("sketch", "Sketch1", 0, features.SKETCH, sketch=sk),
                 features.Feature("boss", "Boss-Extrude1", 1, features.BOSS, profile="Sketch1", depth_mm=10.0)]
        with mock.patch.object(verify, "same_shape", return_value=False):
            self.assertIsNone(verify.rebuild(feats, box(), "Box", cli))

    def test_a_failed_difference_is_not_a_match(self):
        self.assertFalse(verify.shape_differences_within(None, None, 1.0))
        self.assertTrue(verify.shape_differences_within(0.5, 0.5, 1000.0))
        self.assertFalse(verify.shape_differences_within(2.0, 0.0, 1000.0))


if __name__ == "__main__":
    unittest.main()
