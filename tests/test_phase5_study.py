import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from civsim.fiscal_storage import write_government_run
from civsim.model import generate_world
from civsim.regional_engine import step_regional
from civsim.regions import regionalize
from civsim.storage import canonical_line
from experiments.phase5a import MODES, disparity, run_study


def rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


class GovernmentStudyTests(unittest.TestCase):
    def test_disparity_weights_rations_and_distinguishes_within_country(self):
        # Country 0 fulfills zero and two rations out of two persons each.
        # Country 1 fulfills four of four, and its empty region has no weight.
        population = {0: (0, 2, 0), 1: (0, 2, 2), 2: (1, 4, 4), 3: (1, 0, 0)}
        world, within = disparity(population)
        self.assertEqual(sum(world.values()) / 8, 0.375)
        self.assertEqual(sum(within.values()) / 8, 0.25)
        self.assertEqual(world[3], 0)

    def test_matched_arms_checkpoints_replay_and_public_accounts(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp, "dev")
            run_study(out, sample="dev", seeds=1, horizons=(1, 3), workers=1)
            data = rows(out / "runs.csv")
            self.assertEqual({(r["mode"], r["year"]) for r in data},
                             {(m, y) for m in MODES for y in ("1", "3")})
            self.assertEqual(len({r["initial_fiscal_sha256"] for r in data}), 1)
            self.assertEqual(len({r["initial_regional_sha256"] for r in data}), 1)
            for r in data:
                self.assertEqual(int(r["food_need"]) - int(r["food_eaten"]), int(r["food_deficit"]))
                self.assertEqual(int(r["initial_cash"]), int(r["final_cash"]))
                if r["mode"] == "none":
                    self.assertEqual(int(r["levied_food"]) + int(r["public_reserve_food"]), 0)
            countries = rows(out / "countries.csv")
            self.assertEqual(len(countries), 8 * len(data))
            for r in data:
                group = [c for c in countries if (c["mode"], c["year"]) == (r["mode"], r["year"])]
                for k in ("public_reserve_food", "levied_food", "food_deficit", "final_cash"):
                    self.assertEqual(sum(int(c[k]) for c in group), int(r[k]))
            world, digest = regionalize(generate_world(0)), hashlib.sha256()
            for year in range(1, 4):
                digest.update(canonical_line(step_regional(world, year)))
            self.assertEqual(next(r["control_regional_sha256"] for r in data
                                  if r["mode"] == "none" and r["year"] == "3"), digest.hexdigest())
            saved = Path(temp, "annual")
            write_government_run(saved, seed=0, years=3, policy="integrated")
            full = next(r for r in data if r["mode"] == "integrated" and r["year"] == "3")
            for filename, field in (("world.json", "initial_fiscal_sha256"), ("years.jsonl", "years_sha256")):
                self.assertEqual(hashlib.sha256((saved / filename).read_bytes()).hexdigest(), full[field])
            self.assertEqual(len(rows(out / "paired.csv")), 6)
            self.assertIsInstance(json.loads((out / "cases.json").read_text(encoding="utf-8")), list)
            for filename in ("cases.json", "execution.json"):
                self.assertNotIn(b"\r", (out / filename).read_bytes())
            with self.assertRaises(FileExistsError):
                run_study(out, sample="dev", seeds=1, horizons=(1,), workers=1)
            repeated = Path(temp, "repeat")
            run_study(repeated, sample="dev", seeds=1, horizons=(1, 3), workers=1, verify=out)
            self.assertEqual((out / "runs.csv").read_bytes(), (repeated / "runs.csv").read_bytes())
            with (repeated / "means.csv").open("a", encoding="utf-8") as stream:
                stream.write("corrupt row\n")
            rejected = Path(temp, "rejected")
            with self.assertRaisesRegex(ValueError, "means.csv"):
                run_study(rejected, sample="dev", seeds=1, horizons=(1, 3), workers=1, verify=repeated)
            self.assertFalse(rejected.exists())

    def test_rejects_overlapping_and_invalid_experiment_specs(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp, "result")
            for spec in ({"sample": "dev", "seeds": 21}, {"sample": "dev", "horizons": (2, 2)},
                         {"sample": "both"}, {"sample": "dev", "workers": 0}):
                with self.subTest(spec=spec), self.assertRaises(ValueError):
                    run_study(out, **spec)
            self.assertFalse(out.exists())
