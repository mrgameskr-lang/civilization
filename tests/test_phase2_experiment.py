import csv
import hashlib
import itertools
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from civsim.model import GOODS, generate_world
from civsim.storage import write_run
from experiments.phase2 import measure_records, run_experiment


class PhaseTwoExperimentTests(unittest.TestCase):
    def test_cash_and_labor_metrics_use_signed_fills_and_end_of_year_thresholds(self):
        nations = generate_world(0, 2, 1, 2).nations
        for nation in nations:
            nation.cash = 100
            nation.population = 1000
        records = []
        for year, (seller, buyer, good, quantity, price, a_cash) in enumerate([
            (1, 0, "ore", 3, 33, 1),
            (1, 0, "tools", 1, 1, 0),
            (0, 1, "food", 2, 11, 22),
        ], 1):
            rows = []
            for i, cash in enumerate((a_cash, 200 - a_cash)):
                production = {"workers": 200, "farm_share": 500, "active_farmers": 90,
                              "produced": {"food": 40, "ore": 10, "tools": 5}}
                if i == 1:
                    production["reassigned"] = {"mine": 4, "factory": 6}
                rows.append({"id": i, "closing": {"population": 1000 + i, "cash": cash},
                             "consumption": {"food_need": 1000, "food_eaten": 999 + i},
                             "production": production})
            records.append({"year": year, "countries": rows, "market": {"trades": [
                {"seller": seller, "buyer": buyer, "good": good, "quantity": quantity,
                 "unit_price": price}]}})
        run, (a, b) = measure_records(nations, records)
        expected = {"initial_population": 2000, "final_population": 2001, "food_deficit": 3,
                    "shortage_country_years": 3, "food_output": 240, "ore_output": 60,
                    "tools_output": 30, "food_trade": 2, "ore_trade": 3, "tools_trade": 1,
                    "trade_value": 122, "farm_overflow": 60, "reassigned_mine": 12,
                    "reassigned_factory": 18, "zero_country_years": 1,
                    "near_zero_country_years": 2}
        self.assertEqual({k: run[k] for k in expected}, expected)
        self.assertAlmostEqual(run["final_top1_share"], 0.89)
        self.assertAlmostEqual(run["final_hhi"], 0.8042)
        expected_a = {"initial_cash": 100, "final_cash": 22, "min_cash": 0,
                      "first_zero_year": 2, "zero_years": 1, "near_zero_years": 2,
                      "net_food_cash": 22, "net_ore_cash": -99, "net_tools_cash": -1,
                      "food_deficit": 3, "shortage_years": 3}
        self.assertEqual({k: a[k] for k in expected_a}, expected_a)
        self.assertEqual(a["peak_cash_share"], 0.5)
        self.assertEqual(b["peak_cash_share"], 1.0)
        self.assertIsNone(b["first_zero_year"])
        records[-1]["countries"][0]["closing"]["cash"] += 1
        with self.assertRaisesRegex(ValueError, "cash"):
            measure_records(nations, records)

    def test_cli_emits_all_paired_scenarios_and_matches_saved_baseline_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp, "matrix")
            subprocess.run([sys.executable, "-m", "experiments.phase2", "--out", str(out),
                            "--seeds", "1", "--years", "2"], check=True, capture_output=True)
            with (out / "runs.csv").open(encoding="utf-8-sig", newline="") as f:
                runs = list(csv.DictReader(f))
            with (out / "countries.csv").open(encoding="utf-8-sig", newline="") as f:
                countries = list(csv.DictReader(f))
            expected = {(labor, "-".join(order)) for order in itertools.permutations(GOODS)
                        for labor in ("idle", "reallocate")}
            self.assertEqual({(r["labor"], r["order"]) for r in runs}, expected)
            self.assertEqual(len(runs), 12)
            self.assertEqual({(r["seed"], r["years"]) for r in runs}, {("0", "2")})
            self.assertEqual(len(countries), 96)
            self.assertEqual(len({(r["labor"], r["order"], r["nation_id"]) for r in countries}), 96)
            self.assertEqual(len({r["initial_sha256"] for r in runs}), 1)
            legacy = [r for r in runs if r["model_version"] == "1.0"]
            self.assertEqual([(r["labor"], r["order"]) for r in legacy], [("idle", "food-ore-tools")])
            self.assertEqual(sum(r["model_version"] == "2.0" for r in runs), 11)
            reference = Path(temp, "reference")
            write_run(reference, seed=0, years=2)
            for key, name in [("initial_sha256", "world.json"), ("years_sha256", "years.jsonl")]:
                digest = hashlib.sha256((reference / name).read_bytes()).hexdigest()
                self.assertEqual(legacy[0][key], digest)
            marker = out / "keep"
            marker.write_text("original", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                run_experiment(out, seeds=1, years=1)
            self.assertEqual(marker.read_text(encoding="utf-8"), "original")

    def test_mismatched_initial_world_aborts_before_publishing(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp, "matrix")
            original = generate_world(0)
            changed = generate_world(0)
            changed.nations[0].cash += 1
            with patch("experiments.phase2.generate_world", side_effect=[original, changed]):
                with self.assertRaisesRegex(ValueError, "initial"):
                    run_experiment(out, seeds=1, years=1)
            self.assertFalse(out.exists())
            self.assertEqual(list(Path(temp).iterdir()), [])
