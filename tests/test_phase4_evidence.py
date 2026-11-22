"""Published data must reconcile independently across the regional and national tables."""
from collections import defaultdict
import csv
from pathlib import Path
import unittest

from civsim.storage import verify_run
from experiments.phase4 import POLICIES
from experiments.road_closure4 import compare


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


class Evidence4Tests(unittest.TestCase):
    def test_complete_seed_pairs_initial_hashes_and_region_balances(self):
        init = {r["seed"]: r for r in read_csv(EXAMPLES / "phase4a/initial-worlds.csv")}
        folder = EXAMPLES / "phase4/study"
        runs = read_csv(folder / "runs.csv")
        self.assertEqual(len(runs), 20*4*2)
        expected = {(str(seed), arm, str(year)) for seed in range(20) for arm in POLICIES for year in (50,200)}
        self.assertEqual({(r["seed"],r["arm"],r["year"]) for r in runs}, expected)
        groups = defaultdict(list)
        for r in read_csv(folder / "regions.csv"):
            groups[r["seed"],r["arm"],r["year"]].append(r)
        for r in runs:
            initial = init[r["seed"]]
            self.assertEqual(r["initial_national_sha256"], initial["initial_world_sha256"])
            self.assertEqual(r["initial_regional_sha256"], initial["regional_world_sha256"])
            parts = groups[r["seed"],r["arm"],r["year"]]
            self.assertEqual(len({p["region"] for p in parts}), 32)
            for regional, national in (("cash","final_cash"), ("population","final_population"),
                                       ("deposit","final_deposit"), ("food_deficit","food_deficit")):
                self.assertEqual(sum(int(p[regional]) for p in parts), int(r[national]))
            self.assertEqual(r["final_cash"], initial["cash"])
            self.assertEqual(int(r["final_deposit"]) + int(r["ore_output"]), int(initial["deposit"]))

    def test_detailed_example_and_fixed_opening_road_closure(self):
        self.assertEqual(verify_run(EXAMPLES / "phase4/seed7-two-years"),
                         "cb5600c4af37f4a580eec64cf0cace1c0697b695b52cf526fc7d2c5665a005b4")
        unlimited, limited, closed = compare(7)
        self.assertEqual(unlimited["food_output"], closed["food_output"])
        self.assertEqual(limited["unmet"], 0)
        self.assertEqual(closed["unmet"], 962)
        self.assertEqual(closed["food_shipped"], 0)
