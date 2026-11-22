import csv
import tempfile
import unittest
from pathlib import Path

from experiments.investment_case import write_case


class InvestmentCaseTests(unittest.TestCase):
    def test_same_opening_population_and_reconciled_country_ledger(self):
        with tempfile.TemporaryDirectory() as scratch:
            target = Path(scratch) / "case.csv"
            write_case(target, seed=7, nation=7, years=8)
            with target.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 16)
            self.assertEqual({r["name"] for r in rows}, {"타비르"})
            first = [r for r in rows if r["year"] == "1"]
            self.assertEqual({r["arm"] for r in first}, {"inventory", "capital"})
            for key in ("population_open", "soil_open", "cash_open", "deposit_open", "food_open",
                        "ore_open", "tools_open"):
                self.assertEqual(first[0][key], first[1][key])
            by_arm = {}
            for r in rows:
                opening, closing = int(r["population_open"]), int(r["population_close"])
                if r["arm"] in by_arm:
                    self.assertEqual(opening, by_arm[r["arm"]])
                by_arm[r["arm"]] = closing
                self.assertEqual(closing, opening + int(r["births"]) - int(r["deaths"])
                                 + int(r["immigrants"]) - int(r["emigrants"]))
                self.assertEqual(int(r["food_need"]), int(r["food_eaten"]) + int(r["food_unmet"]))
            build = next(r for r in rows if r["year"] == "6" and r["arm"] == "capital")
            self.assertEqual([int(build[k]) for k in ("built_farm", "build_tools", "build_ore",
                                                      "construction_labor")], [1, 8, 8, 6])
            self.assertEqual(build["food_output"], build["reference_food_output"])
            previous = target.read_bytes()
            with self.assertRaises(FileExistsError):
                write_case(target, seed=8, nation=2, years=1)
            self.assertEqual(target.read_bytes(), previous)

    def test_invalid_country_or_horizon_cannot_publish_partial_csv(self):
        with tempfile.TemporaryDirectory() as scratch:
            target = Path(scratch) / "case.csv"
            for nation, years in [(8, 2), (-1, 2), (7, 0)]:
                with self.subTest(nation=nation, years=years), self.assertRaises(ValueError):
                    write_case(target, seed=7, nation=nation, years=years)
                self.assertFalse(target.exists())
