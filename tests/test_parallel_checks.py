"""Parallel feature-check and rebuild-triage runners keep their input order and errors."""
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import feature_check  # noqa: E402
import rebuild_triage  # noqa: E402


class ParallelCheckTests(unittest.TestCase):
    def test_cli_accepts_jobs(self):
        for tool in ("feature_check.py", "rebuild_triage.py"):
            with self.subTest(tool=tool):
                r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", tool), "--help"],
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, 0)
                self.assertIn("--jobs", r.stdout)

    def test_feature_check_parallel_preserves_order_and_read_errors(self):
        self.assertTrue(hasattr(feature_check, "run_checks"), "parallel feature-check runner is missing")
        with tempfile.TemporaryDirectory() as tmp:
            paths = [os.path.join(tmp, f"Part {c}.sldprt") for c in "AB"]
            rows = feature_check.run_checks(paths, "", jobs=2)
        self.assertEqual([r["path"] for r in rows], paths)
        self.assertEqual([r["status"] for r in rows], ["unreadable", "unreadable"])

    def test_triage_parallel_preserves_order_and_errors(self):
        self.assertTrue(hasattr(rebuild_triage, "run_triages"), "parallel triage runner is missing")
        with tempfile.TemporaryDirectory() as tmp:
            paths = [os.path.join(tmp, f"Part {c}.sldprt") for c in "AB"]
            rows = rebuild_triage.run_triages(paths, "", budget=0.01, jobs=2)
        self.assertEqual([p for p, _r in rows], paths)
        self.assertTrue(all(r["result"].startswith("error ") for _p, r in rows))


if __name__ == "__main__":
    unittest.main()
