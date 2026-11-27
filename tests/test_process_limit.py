"""Conversion child processes have a hard memory ceiling on Windows."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import convert_sample  # noqa: E402
import process_limit  # noqa: E402


class ProcessLimitTests(unittest.TestCase):
    def test_convert_sample_passes_timeout_and_memory_limit(self):
        self.assertTrue(hasattr(convert_sample, "process_limit"), "memory-limited process runner is missing")
        result = mock.Mock(stdout="{}", stderr="", returncode=0)
        with mock.patch.object(convert_sample.process_limit, "run", return_value=result) as run:
            convert_sample.run("Part A.SLDPRT", timeout=3600, memory_mb=8192)
        self.assertEqual(run.call_args.kwargs["timeout"], 3600)
        self.assertEqual(run.call_args.kwargs["memory_mb"], 8192)

    @unittest.skipUnless(os.name == "nt", "Windows Job Objects are required")
    def test_job_limit_stops_a_large_allocation(self):
        self.assertTrue(hasattr(process_limit, "run"), "memory-limited process runner is missing")
        result = process_limit.run([sys.executable, "-c", "import time; x = bytearray(512 * 1024 * 1024); time.sleep(5); print(len(x))"],
                                   timeout=30, memory_mb=128)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
