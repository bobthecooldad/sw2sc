import unittest

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


if __name__ == "__main__":
    unittest.main()
