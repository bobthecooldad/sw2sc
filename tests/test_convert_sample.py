"""Full-folder conversion sampling skips lock files and accepts long per-part timeouts."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import convert_sample  # noqa: E402


class ConvertSampleTests(unittest.TestCase):
    def test_folder_includes_models_but_not_lock_files(self):
        self.assertTrue(hasattr(convert_sample, "paths_of"), "folder expansion is missing")
        with tempfile.TemporaryDirectory() as tmp:
            real = os.path.join(tmp, "Part A.SLDPRT")
            lock = os.path.join(tmp, "~$Part A.SLDPRT")
            other = os.path.join(tmp, "readme.txt")
            for path in (real, lock, other):
                open(path, "w").close()
            self.assertEqual(convert_sample.paths_of(tmp), [real])

    def test_run_uses_requested_timeout(self):
        result = subprocess_result = mock.Mock()
        result.stdout = "{}"
        result.stderr = ""
        result.returncode = 0
        with mock.patch.object(convert_sample.subprocess, "run", return_value=subprocess_result) as run:
            convert_sample.run("Part A.SLDPRT", timeout=3600)
        self.assertEqual(run.call_args.kwargs["timeout"], 3600)


if __name__ == "__main__":
    unittest.main()
