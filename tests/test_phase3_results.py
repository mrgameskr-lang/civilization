"""Release checks for the published paired experiment and its historical controls."""

import csv
from pathlib import Path
import unittest


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


class PublishedInvestmentResultsTests(unittest.TestCase):
    def test_50_year_controls_reproduce_the_phase_two_ledgers_for_all_seeds(self):
        previous = {(int(r["seed"]), r["labor"]): r for r in
                    rows(EXAMPLES / "phase2-seeds-0-19/runs.csv") if r["order"] == "food-ore-tools"}
        current = [r for r in rows(EXAMPLES / "phase3/runs.csv")
                   if r["arm"] in ("v1", "v2") and int(r["horizon"]) == 50]
        self.assertEqual(len(previous), 40)
        self.assertEqual(len(current), 40)
        for r in current:
            expected = previous[int(r["seed"]), "idle" if r["arm"] == "v1" else "reallocate"]
            self.assertEqual((r["initial_sha256"], r["years_sha256"]),
                             (expected["initial_sha256"], expected["years_sha256"]))

    def test_complete_factorial_design_and_conserved_terminal_resources(self):
        results = rows(EXAMPLES / "phase3/runs.csv")
        keys = {(int(r["seed"]), r["arm"], int(r["horizon"])) for r in results}
        expected = {(seed, arm, horizon) for seed in range(20)
                    for arm in ("v1", "v2", "inventory", "capital") for horizon in (50, 200)}
        self.assertEqual(keys, expected)
        self.assertEqual(len(keys), len(results))
        for seed in range(20):
            self.assertEqual(len({r["initial_sha256"] for r in results if int(r["seed"]) == seed}), 1)
        for r in results:
            self.assertEqual(int(r["initial_cash"]), int(r["final_cash"]))
            self.assertEqual(int(r["initial_deposit"]), int(r["final_deposit"]) + int(r["ore_output"]))
