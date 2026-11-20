import csv
import tempfile
import unittest
from pathlib import Path

from experiments.compare import paired_stats, compare, ORDERS, METRICS


class PairedExperimentTests(unittest.TestCase):
    def test_pairs_by_seed_and_flags_outside_inclusive_fences(self):
        a = {s: 100 - s for s in range(6)}
        b = {s: a[s] + d for s, d in reversed(list(enumerate([0, 0, 1, 1, -1, 12])))}
        stats = paired_stats(a, b)
        self.assertEqual((stats["increased"], stats["equal"], stats["decreased"]), (3, 2, 1))
        self.assertEqual((stats["min_delta"], stats["max_delta"]), (-1, 12))
        self.assertEqual(stats["max_seeds"], "5")
        self.assertEqual(stats["outlier_seeds"], "5")
        self.assertEqual(stats["median_delta"], 0.5)
        with self.assertRaises(ValueError):
            paired_stats(a, {1: 9})

    def test_refuses_unmatched_world_and_compares_only_one_factor_at_a_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runs.csv"
            out = Path(tmp) / "comparisons.csv"
            data = []
            for seed in range(2):
                for labor in ("idle", "reallocate"):
                    for order in ORDERS:
                        data.append({"seed": seed, "years": 50, "labor": labor, "order": order,
                                     "initial_sha256": str(seed),
                                     **dict.fromkeys(METRICS, 0)})
            def save():
                with path.open("w", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=data[0].keys())
                    w.writeheader()
                    w.writerows(data)
            save()
            compare(path, out)
            with out.open(encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), (6 + 2 * 5) * len(METRICS))
            for row in rows:
                self.assertNotEqual(row["a_labor"] != row["b_labor"],
                                    row["a_order"] != row["b_order"])
            with self.assertRaises(FileExistsError):
                compare(path, out)
            data[0]["initial_sha256"] = "wrong"
            save()
            with self.assertRaisesRegex(ValueError, "initial"):
                compare(path, Path(tmp) / "invalid.csv")
