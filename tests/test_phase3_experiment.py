import csv
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from civsim.engine import step
from civsim.model import generate_world
from civsim.rules import Rules
from civsim.storage import write_run
from experiments.phase3 import _comparisons, run_experiment


def read_rows(directory, name):
    with (directory / name).open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


class PhaseThreeExperimentTests(unittest.TestCase):
    def test_paired_effects_and_roi_keep_seed_weights_and_skip_undefined_ratios(self):
        runs = []
        for seed, (cost, gain, pop_effect) in enumerate([(10, 20, 10), (30, 15, -3), (0, 0, 1)]):
            for arm in ("v1", "v2", "inventory", "capital"):
                capital = arm == "capital"
                runs.append({
                    "seed": seed, "arm": arm, "horizon": 50,
                    "final_population": 100 + seed + (pop_effect if capital else 0),
                    "investment_input_value": cost if capital else 0,
                    "gross_gain_value": gain if capital else 0,
                    "local_net_roi": (gain - cost) / cost if capital and cost else None,
                    "food_need": [100, 300, 1000][seed], "food_deficit": [20, 60, 0][seed],
                    "deficit_share": [0.2, 0.2, 0][seed],
                })
        pairs, means = _comparisons(runs, [50])
        self.assertEqual([r["delta_final_population"] for r in pairs], [10, -3, 1])
        capital = next(r for r in means if r["arm"] == "capital")
        self.assertEqual(capital["roi_defined_seeds"], 2)
        self.assertEqual(capital["local_net_roi"], 0.25)
        self.assertEqual(capital["pooled_local_net_roi"], -0.125)
        self.assertAlmostEqual(capital["pooled_deficit_share"], 80 / 1400)
        self.assertAlmostEqual(capital["deficit_share"], 0.4 / 3)
        self.assertTrue(all(r["local_net_roi"] is None for r in means if r["arm"] != "capital"))

    def test_all_arms_and_horizons_share_world_and_match_independent_run_bytes(self):
        with tempfile.TemporaryDirectory() as scratch:
            output = Path(scratch) / "results"
            subprocess.run([sys.executable, "-m", "experiments.phase3", "--out", str(output),
                            "--seeds", "1", "--horizons", "1,3"], check=True, capture_output=True)
            rows = read_rows(output, "runs.csv")
            self.assertEqual(len(rows), 8)
            self.assertEqual(len({r["initial_sha256"] for r in rows}), 1)
            for r in rows:
                arm, horizon = r["arm"], int(r["horizon"])
                rules = {"v1": Rules(), "v2": Rules("reallocate"),
                         "inventory": Rules("reallocate", investment="inventory"),
                         "capital": Rules("reallocate", investment="capital")}[arm]
                directory = Path(scratch) / f"{arm}-{horizon}"
                write_run(directory, seed=0, years=horizon, rules=rules)
                for name, key in [("world.json", "initial_sha256"), ("years.jsonl", "years_sha256")]:
                    self.assertEqual(hashlib.sha256((directory / name).read_bytes()).hexdigest(), r[key])
                self.assertEqual(r["initial_cash"], r["final_cash"])
                self.assertEqual(int(r["initial_deposit"]) - int(r["final_deposit"]), int(r["ore_output"]))
                if arm != "capital":
                    self.assertEqual(r["local_net_roi"], "")
            assets = read_rows(output, "assets.csv")
            self.assertEqual(len(assets), 24)
            self.assertTrue(all(int(r["terminal"]) == int(r["built"]) - int(r["retired"]) for r in assets))
            means = read_rows(output, "means.csv")
            self.assertEqual(len(means), 8)
            for mean in means:
                source = next(r for r in rows if (r["arm"], r["horizon"]) == (mean["arm"], mean["horizon"]))
                self.assertEqual(float(mean["food_deficit"]), int(source["food_deficit"]))
            for pair in read_rows(output, "paired.csv"):
                selected = {r["arm"]: int(r["final_population"]) for r in rows if r["horizon"] == pair["horizon"]}
                self.assertEqual(int(pair["delta_final_population"]), selected["capital"] - selected["inventory"])
            before = (output / "runs.csv").read_bytes()
            with self.assertRaises(FileExistsError):
                run_experiment(output, seeds=1, horizons=(1,))
            self.assertEqual((output / "runs.csv").read_bytes(), before)

    def test_metrics_match_saved_flows_and_repeated_horizons_are_not_resimulated(self):
        with tempfile.TemporaryDirectory() as scratch:
            output = Path(scratch) / "experiment"
            with patch("experiments.phase3.step", wraps=step) as transition:
                run_experiment(output, seeds=1, horizons=(2, 12))
            self.assertEqual(transition.call_count, 4 * 12)
            row = next(r for r in read_rows(output, "runs.csv")
                       if r["arm"] == "capital" and r["horizon"] == "12")
            world = generate_world(0)
            records = [step(world, year, Rules("reallocate", investment="capital"))
                       for year in range(1, 13)]
            countries = [c for year in records for c in year["countries"]]
            plans = [c["production"]["investment"] for c in countries]
            prices = {"food": 8, "ore": 4, "tools": 12}
            input_value = sum(
                8 * plan["construction_labor"] + sum(
                    price * (plan["build_used"][g] + plan["upkeep_used"][g])
                    for g, price in prices.items()
                ) for plan in plans
            )
            gain = sum(plan["gross_gain_value"] for plan in plans)
            self.assertGreater(input_value, 0)
            self.assertEqual(int(row["investment_input_value"]), input_value)
            self.assertEqual(int(row["gross_gain_value"]), gain)
            self.assertAlmostEqual(float(row["local_net_roi"]), gain / input_value - 1)
            self.assertEqual(int(row["food_deficit"]), sum(c["consumption"]["food_unmet"] for c in countries))
            food_need = sum(c["consumption"]["food_need"] for c in countries)
            food_eaten = sum(c["consumption"]["food_eaten"] for c in countries)
            self.assertEqual(int(row["food_need"]), food_need)
            self.assertEqual(int(row["food_eaten"]), food_eaten)
            self.assertAlmostEqual(float(row["deficit_share"]), (food_need - food_eaten) / food_need)
            cap = [c for c in countries if c["production"]["tool_need"] > 0 and
                   c["production"]["investment"]["sector_used"]["tools"] == c["production"]["tool_need"]]
            excess = sum(c["production"]["produced"]["tools"] > c["production"]["tool_need"]
                         and c["closing"]["stock"]["tools"] > c["production"]["tool_need"] for c in cap)
            self.assertEqual(int(row["saturated_country_years"]), len(cap))
            self.assertEqual(int(row["saturated_excess_country_years"]), excess)
            self.assertEqual(int(row["final_tools_stock"]), sum(n.stock["tools"] for n in world.nations))
            saved_assets = [r for r in read_rows(output, "assets.csv")
                            if r["arm"] == "capital" and r["horizon"] == "12"]
            for r in saved_assets:
                asset = r["asset"]
                candidates = [p["candidates"][asset] for p in plans if asset in p["candidates"]]
                self.assertEqual(int(r["candidate_years"]), len(candidates))
                self.assertEqual(int(r["positive_return_years"]), sum(c["net_value"] > 0 for c in candidates))
                self.assertEqual(int(r["eligible_years"]), sum(not c["constraints"] for c in candidates))
                books = [plan["book"][asset] for plan in plans]
                additions = sum(book["additions_eighths"] for book in books)
                depreciation = sum(book["depreciation_eighths"] for book in books)
                self.assertEqual(int(r["book_additions_eighths"]), additions)
                self.assertEqual(int(r["book_depreciation_eighths"]), depreciation)
                self.assertEqual(int(r["book_close_eighths"]), additions - depreciation)
                self.assertEqual(int(r["book_open_eighths"]), 0)
                capacity = sum(sum(plan["opening_capital"][asset]) for plan in plans)
                operated = sum(plan["operated"][asset] for plan in plans)
                self.assertEqual(int(r["operated"]), operated)
                self.assertEqual(int(r["available"]), capacity)
                if capacity:
                    self.assertAlmostEqual(float(r["utilization"]), operated / capacity)
                else:
                    self.assertEqual(r["utilization"], "")

    def test_invalid_horizons_or_interrupted_simulation_publish_no_directory(self):
        with tempfile.TemporaryDirectory() as scratch:
            output = Path(scratch) / "out"
            for horizons in [(), (1, 1), (0, 10)]:
                with self.subTest(horizons=horizons), self.assertRaises(ValueError):
                    run_experiment(output, seeds=1, horizons=horizons)
            with patch("experiments.phase3.step", side_effect=RuntimeError("stopped")):
                with self.assertRaises(RuntimeError):
                    run_experiment(output, seeds=1, horizons=(2,))
            self.assertEqual(list(Path(scratch).iterdir()), [])
