import csv
import gzip
import tempfile
import unittest
from pathlib import Path

from civsim.model import generate_world
from experiments.stability31 import STABILITY_ARMS, apply_opening, regime_events, run_study


class StabilityStudyTests(unittest.TestCase):
    def test_population_weighted_cash_transfer_and_one_shot_finite_seam(self):
        w = generate_world(4, 3, 1, 3)
        for n, cash, population in zip(w.nations, (53, 0, 0), (0, 2, 1)):
            n.cash, n.population = cash, population
        seam = {n.id: n.deposit for n in w.nations}
        apply_opening(w, "cash", 51, seam)
        self.assertEqual([n.cash for n in w.nations], [43, 7, 3])
        apply_opening(w, "deep_ore", 51, seam)
        apply_opening(w, "deep_ore", 52, seam)
        self.assertTrue(all(n.deposit == 2 * seam[n.id] for n in w.nations))

    def test_sustained_transition_is_dated_from_the_first_year_and_confirmed_later(self):
        net = [(y, x) for y, x in enumerate([1, 1, 1, 1, 1, -2, 1, -1, 0, -2, -1, 0], 1)]
        events = regime_events(net)
        self.assertEqual([(e["start_year"], e["confirmed_year"], e["regime"]) for e in events],
                         [(1, 5, "growth"), (8, 12, "non_growth")])

    def test_paired_start_resource_accounts_and_deterministic_compression(self):
        with tempfile.TemporaryDirectory() as temp:
            dirs = [Path(temp) / x for x in ("one", "two")]
            for directory in dirs:
                run_study(directory, seeds=1, baseline_years=54, treatment_years=53)
            for name in ("country_year.csv.gz", "world_year.csv.gz", "transitions.csv",
                         "turning_points.csv", "checkpoints.csv", "paired.csv"):
                self.assertEqual((dirs[0] / name).read_bytes(), (dirs[1] / name).read_bytes())
            with gzip.open(dirs[0] / "country_year.csv.gz", "rt", encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), (54 + 3 * (53 - 50)) * 8)
            for row in rows:
                n = lambda key: int(row[key])
                self.assertEqual(n("pop_close") - n("pop_open"), n("births")-n("deaths")+n("net_migration"))
                self.assertEqual(n("deposit_close"), n("deposit_before_policy")+n("deposit_added")-n("ore_mined"))
                self.assertEqual(n("cash_close"), n("cash_before_policy")+n("cash_transfer")
                                 +n("exports_value")-n("imports_value"))
                if row["arm"] == "soil_floor":
                    self.assertGreaterEqual(n("soil_close"), n("soil_open"))
            for arm in STABILITY_ARMS:
                y51 = [r for r in rows if r["arm"] == arm and r["year"] == "51"]
                self.assertEqual(sum(int(r["cash_transfer"]) for r in y51), 0)
            for i in range(8):
                first = [r for r in rows if r["year"] == "51" and r["nation_id"] == str(i)]
                for key in ("pop_open", "soil_open", "deposit_before_policy", "cash_before_policy"):
                    self.assertEqual(len({r[key] for r in first}), 1)
            with self.assertRaises(FileExistsError):
                run_study(dirs[0], seeds=1, baseline_years=54, treatment_years=53)
