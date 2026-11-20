import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from civsim.model import generate_world
from civsim.rules import Rules
from civsim.storage import write_run
from experiments.investment31 import ARMS, contrasts, run_experiment, summarize_run


def rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


class InvestmentMatrix31Tests(unittest.TestCase):
    def test_reference_rejects_overlapping_seeds_or_changed_rules_before_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            dev = base / "dev"
            run_experiment(dev, seed_start=1, seeds=1, horizons=(1,), workers=1)
            out = base / "holdout"
            with self.assertRaisesRegex(ValueError, "overlap"):
                run_experiment(out, seed_start=1, seeds=1, horizons=(1,), workers=1, match_design=dev)
            meta = json.loads((dev / "execution.json").read_text(encoding="utf-8"))
            meta["model_sha256"] = "0" * 64
            (dev / "execution.json").write_text(json.dumps(meta), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "reference model"):
                run_experiment(out, seed_start=2, seeds=1, horizons=(1,), workers=1, match_design=dev)
            self.assertFalse(out.exists())

    def test_published_matrices_are_disjoint_and_reproduce_40_previous_controls(self):
        examples = Path(__file__).resolve().parents[1] / "examples"
        base = examples / "phase31" / "investment"
        metadata = [json.loads((base / part / "execution.json").read_text(encoding="utf-8"))
                    for part in ("dev", "holdout")]
        self.assertEqual(metadata[0]["model_sha256"], metadata[1]["model_sha256"])
        self.assertEqual(metadata[0]["seeds"], list(range(20)))
        self.assertEqual(metadata[1]["seeds"], list(range(20, 40)))
        historical = {(int(r["seed"]), int(r["horizon"])): (r["initial_sha256"], r["years_sha256"])
                      for r in rows(examples / "phase3" / "runs.csv") if r["arm"] == "capital"}
        checked = 0
        for part, meta in zip(("dev", "holdout"), metadata):
            results = rows(base / part / "runs.csv")
            self.assertEqual(len(results), 640)
            self.assertEqual({(int(r["seed"]), r["arm"], int(r["horizon"])) for r in results},
                             {(s, a, h) for s in meta["seeds"] for a in ARMS for h in (50, 100, 150, 200)})
            for r in results:
                key = (int(r["seed"]), int(r["horizon"]))
                if r["arm"] == "control" and key in historical:
                    self.assertEqual((r["initial_sha256"], r["years_sha256"]), historical[key])
                    checked += 1
        self.assertEqual(checked, 40)

    def test_crossed_arms_share_world_and_class_costs_reconcile_with_postings(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            out = base / "experiment"
            run_experiment(out, seed_start=0, seeds=1, horizons=(2, 8), workers=1)
            all_runs = rows(out / "runs.csv")
            all_assets = rows(out / "assets.csv")
            self.assertEqual((len(all_runs), len(all_assets)), (16, 48))
            self.assertEqual(len({r["initial_sha256"] for r in all_runs}), 1)
            for run in all_runs:
                group = [a for a in all_assets if (a["arm"], a["horizon"]) == (run["arm"], run["horizon"])]
                for field in ("cost_value", "built", "available", "operated"):
                    self.assertEqual(sum(int(r[field]) for r in group), int(run[field]))
                self.assertEqual(int(run["initial_cash"]), int(run["final_cash"]))
                self.assertEqual(int(run["initial_deposit"]) - int(run["final_deposit"]), int(run["ore_output"]))
                self.assertEqual(int(run["food_need"]) - int(run["food_eaten"]), int(run["food_deficit"]))
                for r in group:
                    self.assertEqual(int(r["marginal_net_value"]), int(r["marginal_gain_value"]) - int(r["cost_value"]))
                    self.assertEqual(int(r["prospects"]), 8 * int(run["horizon"]))
            control = next(r for r in all_runs if r["horizon"] == "8" and r["arm"] == "control")
            reference = base / "reference"
            write_run(reference, years=8, seed=0, rules=Rules("reallocate", investment="capital"))
            self.assertEqual(control["years_sha256"], hashlib.sha256((reference / "years.jsonl").read_bytes()).hexdigest())
            control_assets = [r for r in all_assets if r["horizon"] == "8" and r["arm"] == "control"]
            self.assertGreater(sum(int(r["marginal_gain_value"]) for r in control_assets), 0)
            self.assertEqual(len(rows(out / "paired.csv")), 14)
            self.assertEqual(len(rows(out / "factors.csv")), 24)
            with self.assertRaises(FileExistsError):
                run_experiment(out, seed_start=0, seeds=1, horizons=(2,), workers=1)

    def test_factor_edges_change_one_bit_and_primary_effect_is_paired(self):
        self.assertEqual(len(ARMS), 8)
        data = [{"seed": 3, "horizon": 50, "arm": name, "final_population": i,
                 "deficit_share": i / 100, "final_hhi": 0.8, "ore_output": 1, "food_deficit": 20,
                 "food_output": 9, "depleted_nations": 0, "built": 3, "cost_value": 4,
                 "tools_output": 3, "final_soil": 980, "final_deposit": 250,
                 "shortage_country_years": 0, "final_top1_share": 0.55,
                 "gross_gain_value": 7, "local_net_value": 3} for i, name in enumerate(ARMS)]
        paired, factors = contrasts(data)
        self.assertEqual(len(factors), 12)
        self.assertEqual(len({(r["factor"], r["control"], r["treatment"]) for r in factors}), 12)
        cube = dict(zip(ARMS, [(0, 0, 0), (0, 0, 1), (1, 0, 0), (1, 0, 1),
                              (0, 1, 0), (0, 1, 1), (1, 1, 0), (1, 1, 1)]))
        for r in factors:
            self.assertEqual(sum(a != b for a, b in zip(cube[r["control"]], cube[r["treatment"]])), 1)
        primary = next(r for r in paired if r["treatment"] == "combined-multi")
        self.assertEqual(primary["delta_final_population"], 7)

    def test_class_margins_are_computed_from_reference_and_may_differ_from_portfolio(self):
        world = generate_world(7)
        runs, assets = summarize_run(world, "control", (12,))
        run = runs[0]
        self.assertEqual(run["marginal_interaction_gap"],
                         run["gross_gain_value"] - sum(a["marginal_gain_value"] for a in assets))
        self.assertTrue(any(a["available"] > 0 and a["marginal_gain_value"] > 0 for a in assets))
        for a in assets:
            self.assertLessEqual(a["prospect_min"], a["prospect_p50"])
            self.assertLessEqual(a["prospect_p50"], a["prospect_max"])
