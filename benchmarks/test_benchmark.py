import unittest

from benchmarks.benchmark import build_report


class BenchmarkTests(unittest.TestCase):
    def test_small_run_measures_all_four_scenarios_and_profiles_persistence(self):
        result = build_report(repeats=1, years=1)
        self.assertEqual(result["seed"], 42)
        self.assertEqual(result["years"], 1)
        self.assertEqual(result["repeats"], 1)
        scenarios = result["scenarios"]
        dimensions = {(s["width"], s["height"], s["nations"]) for s in scenarios}
        self.assertEqual(dimensions, {(48, 32, 8), (48, 32, 32), (96, 64, 8), (96, 64, 32)})
        for case in scenarios:
            self.assertGreater(case["bytes_persisted"], 0)
            for key in ("init_ms", "core_ms", "end_to_end_ms"):
                self.assertGreater(case[key], 0)
        for ordering in ("by_self_time", "by_cumulative_time"):
            rows = result["profile"][ordering]
            self.assertGreater(len(rows), 0)
            for row in rows:
                self.assertNotIn("\\", row["function"])
                self.assertNotIn("/", row["function"])
