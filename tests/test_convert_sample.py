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

    def test_cycles_cover_every_path_and_keep_pinned_regressions(self):
        paths = [f"part-{n}.sldprt" for n in range(10)]
        seen = set()
        for cycle in range(5):
            sample = convert_sample.sample_paths(paths, 3, seed=7, cycle=cycle, include=["part-0.sldprt"])
            self.assertLessEqual(len(sample), 3)
            self.assertIn("part-0.sldprt", sample)
            seen.update(sample)
        self.assertEqual(seen, set(paths))

    def test_dimension_coverage_includes_saved_dimensions_missed_by_the_reader(self):
        from sw2sc import features
        sk = features.Sketch("Sketch1", 0)
        sk.dims = [("D1", "sgPntPntDist", 0.010, [])]
        feats = [features.Feature("sketch", "Sketch1", 0, features.SKETCH, sketch=sk)]
        shown = {"Sketch1": [("D1", "10"), ("D2", "20"), ("D3", "<MOD-DIAM>30")]}
        result = convert_sample.dimension_coverage(feats, shown, {"params": [{"name": "Sketch1_D1"}]})
        self.assertEqual(result, {"expected": 2, "written": 1, "missing": ["Sketch1_D2"]})

    def test_cycle_baseline_does_not_learn_a_regression(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            baseline = os.path.join(tmp, "baseline.jsonl")
            results = os.path.join(tmp, "results.jsonl")
            good = {"file": "A", "summary": "A: rebuilt from its 2 features", "error": None, "items": [], "rebuild": {}}
            bad = {"file": "A", "summary": "A: its solid (the tree's rebuild didn't match)", "error": None, "items": [], "rebuild": {"closest": "no build"}}
            with open(baseline, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(good) + "\n")
            with open(results, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(bad) + "\n")
            convert_sample.merge_baseline(results, baseline)
            with open(baseline, encoding="utf-8") as fh:
                self.assertEqual(json.loads(fh.read()), good)

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
