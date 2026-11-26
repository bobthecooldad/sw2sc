"""Optional external sample batches stay separate from the existing long-run baseline."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import checks  # noqa: E402


class ExternalSampleTests(unittest.TestCase):
    def test_external_sample_has_its_own_baseline_and_commit_seed(self):
        self.assertTrue(hasattr(checks, "external_sample"), "external sample job is missing")
        cfg = {"external_sample_list": "private-list.txt", "external_sample_n": 40,
               "external_sample_jobs": 8}
        cmd, out, base = checks.external_sample(cfg, "12345678abcdef")
        self.assertEqual(out, os.path.join(checks.BASE, "external-sample-12345678.jsonl"))
        self.assertEqual(base, os.path.join(checks.BASE, "external-sample.jsonl"))
        self.assertNotEqual(base, os.path.join(checks.BASE, "sample.jsonl"))
        self.assertIn("private-list.txt", cmd)
        self.assertEqual(cmd[cmd.index("--n") + 1], "40")
        self.assertEqual(cmd[cmd.index("--jobs") + 1], "8")
        self.assertEqual(cmd[cmd.index("--seed") + 1], str(int("12345678", 16)))

    def test_external_sample_is_optional(self):
        self.assertTrue(hasattr(checks, "external_sample"), "external sample job is missing")
        self.assertIsNone(checks.external_sample({}, "12345678abcdef"))

    def test_long_run_waits_for_the_external_batch(self):
        cfg = {"sample_list": "public-list.txt", "external_sample_list": "private-list.txt"}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(checks, "BASE", tmp), mock.patch.object(checks, "config", return_value=cfg):
            rev = "12345678abcdef"
            open(os.path.join(tmp, "sample-12345678.jsonl"), "w").close()
            self.assertFalse(checks.long_done(rev))
            open(os.path.join(tmp, "external-sample-12345678.jsonl"), "w").close()
            self.assertTrue(checks.long_done(rev))


if __name__ == "__main__":
    unittest.main()
