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

    def test_large_files_run_separately_from_small_files(self):
        self.assertTrue(hasattr(convert_sample, "split_large"), "large-file partition is missing")
        with tempfile.TemporaryDirectory() as tmp:
            small = os.path.join(tmp, "small.SLDPRT")
            large = os.path.join(tmp, "large.SLDPRT")
            open(small, "w").close()
            with open(large, "wb") as fh:
                fh.truncate(2 * 1024 * 1024)
            large_paths, normal_paths = convert_sample.split_large([small, large], 1)
            self.assertEqual(large_paths, [large])
            self.assertEqual(normal_paths, [small])
            workers = []

            class Pool:
                def __init__(self, jobs):
                    workers.append(jobs)

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def map(self, fn, paths):
                    return [fn(p) for p in paths]

            def result(path, timeout, memory_mb=8192):
                return {"file": path, "seconds": 0, "summary": None, "error": None, "items": [], "rebuild": None}

            with mock.patch.object(convert_sample, "ThreadPoolExecutor", Pool), \
                    mock.patch.object(convert_sample, "run", side_effect=result):
                with open(os.path.join(tmp, "out.jsonl"), "w") as fh:
                    convert_sample.run_batch(large_paths, 1, 900, fh, [])
                    convert_sample.run_batch(normal_paths, 2, 900, fh, [])
            self.assertEqual(workers, [1, 2])

    def test_run_uses_requested_timeout(self):
        result = subprocess_result = mock.Mock()
        result.stdout = "{}"
        result.stderr = ""
        result.returncode = 0
        with mock.patch.object(convert_sample.process_limit, "run", return_value=subprocess_result) as run:
            convert_sample.run("Part A.SLDPRT", timeout=3600)
        self.assertEqual(run.call_args.kwargs["timeout"], 3600)


if __name__ == "__main__":
    unittest.main()
