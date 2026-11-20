import csv
import hashlib
import json
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

from civsim.regional_storage import write_regional_run
from experiments.phase4 import POLICIES, run_study


def read(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


class RegionalStudyTests(unittest.TestCase):
    def test_published_pairs_and_all_region_and_road_totals(self):
        examples = Path(__file__).resolve().parents[1] / "examples"
        output = examples / "phase4" / "study"
        published = read(output / "runs.csv")
        expected = {(s, a, y) for s in range(20) for a in POLICIES for y in (50, 200)}
        def key(row):
            return int(row["seed"]), row["arm"], int(row["year"])
        self.assertEqual(len(published), len(expected))
        self.assertEqual({key(r) for r in published}, expected)
        old = {int(r["seed"]): r["initial_sha256"]
               for r in read(examples / "phase31" / "investment" / "dev" / "runs.csv")
               if r["arm"] == "combined-multi" and r["horizon"] == "200"}
        regional = defaultdict(list)
        for row in read(output / "regions.csv"):
            regional[key(row)].append(row)
        roads = defaultdict(list)
        for row in read(output / "roads.csv"):
            roads[key(row)].append(row)
        initial = {}
        for row in published:
            s, arm, y = key(row)
            with self.subTest(seed=s, arm=arm, horizon=y):
                self.assertEqual(row["initial_national_sha256"], old[s])
                self.assertEqual(initial.setdefault(s, row["initial_regional_sha256"]),
                                 row["initial_regional_sha256"])
                places = regional[s, arm, y]
                edges = roads[s, arm, y]
                self.assertEqual({int(r["region"]) for r in places}, set(range(32)))
                for column in ("food_need", "food_eaten", "food_deficit", "ore_output", "care_tools"):
                    self.assertEqual(sum(int(r[column]) for r in places), int(row[column]))
                self.assertEqual(sum(int(r["population"]) for r in places), int(row["final_population"]))
                self.assertEqual(sum(int(r["used"]) for r in edges), int(row["road_load"]))
                self.assertEqual(sum(int(r["cost_food"]) for r in edges), int(row["domestic_cost_food"]))
                if arm == "limited":
                    comparable = sum(int(row["region_years_cap_" + outcome])
                                     for outcome in ("worse", "better", "equal"))
                    self.assertEqual(comparable, 32 * y)
                    self.assertEqual(row["frozen_limited_unmet"], row["food_deficit"])

    def test_four_arms_two_checkpoints_and_raw_digest_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp, "study")
            run_study(output, seeds=1, horizons=(1, 2), workers=1)
            runs = read(output / "runs.csv")
            self.assertEqual(len(runs), 8)
            self.assertEqual({r["arm"] for r in runs}, set(POLICIES))
            self.assertEqual(len({r["initial_regional_sha256"] for r in runs}), 1)
            primary = next(r for r in runs if r["arm"] == "limited" and r["year"] == "2")
            exact = Path(tmp, "saved")
            write_regional_run(exact, seed=0, years=2)
            for field, name in [("years_sha256", "years.jsonl"), ("initial_regional_sha256", "world.json")]:
                self.assertEqual(primary[field], hashlib.sha256((exact / name).read_bytes()).hexdigest())
            for r in runs:
                self.assertEqual(int(r["food_need"]) - int(r["food_eaten"]), int(r["food_deficit"]))
                self.assertEqual(int(r["initial_deposit"]) - int(r["final_deposit"]), int(r["ore_output"]))
                if r["arm"] == "limited":
                    self.assertEqual(int(r["frozen_limited_unmet"]), int(r["food_deficit"]))
                else:
                    self.assertEqual(r["frozen_limited_unmet"], "")
            regions = [r for r in read(output / "regions.csv") if r["arm"] == "limited" and r["year"] == "2"]
            self.assertEqual(len(regions), 32)
            self.assertEqual(sum(int(r["food_deficit"]) for r in regions), int(primary["food_deficit"]))
            roads = [r for r in read(output / "roads.csv") if r["arm"] == "limited" and r["year"] == "2"]
            self.assertEqual(sum(int(r["used"]) for r in roads), int(primary["road_load"]))
            self.assertEqual(sum(int(r["cost_food"]) for r in roads), int(primary["domestic_cost_food"]))
            self.assertEqual(len(read(output/"paired.csv")), 6)
            with self.assertRaises(FileExistsError):
                run_study(output, seeds=1, horizons=(1,), workers=1)

    def test_mean_diagnostic_and_care_turn_off_only_in_matched_arm(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp, "results")
            run_study(output, seeds=1, horizons=(3,), workers=1)
            means = {r["arm"]:r for r in read(output / "means.csv")}
            self.assertEqual(float(means["limited-no-care"]["care_tools"]), 0)
            self.assertEqual(float(means["limited-no-care"]["care_labor"]), 0)
            self.assertGreater(float(means["limited"]["care_labor"]), 0)
            self.assertAlmostEqual(float(means["limited"]["pooled_deficit_share"]),
                                   float(means["limited"]["food_deficit"]) / float(means["limited"]["food_need"]))
            self.assertIsInstance(json.loads((output / "cases.json").read_text(encoding="utf-8")), list)
