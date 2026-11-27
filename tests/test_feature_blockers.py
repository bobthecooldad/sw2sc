import unittest
from unittest import mock

from tools import feature_blockers


class BlockerSummaryTests(unittest.TestCase):
    def test_single_and_shared_blockers_are_counted_separately(self):
        only, anyc = feature_blockers.summarize([
            {"feature A"},
            {"feature A", "sketch plane"},
            set(),
            None,
        ])
        self.assertEqual(only["feature A"], 1)
        self.assertEqual(only["(nothing: fully decoded)"], 1)
        self.assertEqual(anyc["feature A"], 2)
        self.assertEqual(anyc["sketch plane"], 1)
        only, _ = feature_blockers.summarize([set()], dimensions_only=True)
        self.assertEqual(only["(nothing: no detected dimension loss)"], 1)

    def test_dimension_mode_separates_unread_and_unwritten_dimensions(self):
        from sw2sc import features
        sk = features.Sketch("Sketch1", 0)
        sk.add_plane((features.FRONT, (0.0, 0.0, 0.0)), "test")
        sk.dims = [("D1", "sgAnglDim", 0.1, [])]
        feats = [features.Feature("sketch", "Sketch1", 0, features.SKETCH, sketch=sk)]
        sw = mock.Mock()
        sw.xml.return_value = '<Sketch id="1" Name="Sketch1"><Dimension Name="D1">10</Dimension><Dimension Name="D2">20</Dimension></Sketch>'
        kinds = feature_blockers.dimension_kinds(sw, feats)
        self.assertEqual(kinds, {"dimension sgAnglDim", "dimension record unread"})

    def test_sample_option_uses_the_shared_full_coverage_sampler(self):
        with mock.patch.object(feature_blockers, "parts", return_value=[f"part-{n}" for n in range(8)]), \
                mock.patch.object(feature_blockers, "scan", return_value=({}, {})) as scan:
            feature_blockers.main(["folder", "--dimensions-only", "--sample", "3", "--seed", "7"])
        self.assertEqual(len(scan.call_args.args[0]), 3)

    def test_each_part_has_a_timeout_and_memory_limit(self):
        result = mock.Mock(stdout='["feature A"]', stderr="", returncode=0)
        with mock.patch.object(feature_blockers.process_limit, "run", return_value=result) as run:
            kinds = feature_blockers.read_one("Part A.SLDPRT", timeout=123, memory_mb=456)
        self.assertEqual(kinds, {"feature A"})
        self.assertEqual(run.call_args.kwargs, {"timeout": 123, "memory_mb": 456})
        self.assertIn("--one", run.call_args.args[0])

    def test_a_timed_out_part_is_reported_and_does_not_stop_the_scan(self):
        result = mock.Mock(stdout="", stderr="timeout 300s", returncode=-9)
        with mock.patch.object(feature_blockers.process_limit, "run", return_value=result):
            self.assertEqual(feature_blockers.read_one("Part A.SLDPRT"), {"read timeout"})


if __name__ == "__main__":
    unittest.main()
