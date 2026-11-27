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
