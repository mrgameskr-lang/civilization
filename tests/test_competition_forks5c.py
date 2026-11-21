import json
from pathlib import Path
import unittest

from experiments.competition_forks5c import run_case


class RealizedCabinetChoices(unittest.TestCase):
    def test_paired_annual_receipts_replay_and_measure_real_opportunity_costs(self):
        root = Path(__file__).resolve().parents[1] / "examples/phase5c/forks"
        cases = {}
        for kind,year,owner in (("election",13,1),("election",17,0),("tax",13,1)):
            with self.subTest(kind=kind,year=year):
                result = run_case(kind,0,year,owner)
                expected = json.loads((root/f"{kind}-{year}.json").read_text(encoding="utf-8"))
                self.assertEqual(expected, result)
                cases[kind,year] = result
        early, late, tax = cases["election",13], cases["election",17], cases["tax",13]
        self.assertEqual(early["common_opening_sha256"], tax["common_opening_sha256"])
        self.assertEqual(early["elected"]["record_sha256"], tax["fixed"]["record_sha256"])
        for record in (early, late):
            self.assertTrue(record["elected"]["election"]["turnover"])
            self.assertEqual(record["elected"]["election"], record["kept_incumbent"]["election"])
        road, relief = (early[k]["countries"][1] for k in ("kept_incumbent","elected"))
        self.assertEqual((road["public_labor"], relief["relief_food"]), (6,29))
        self.assertEqual(road["capacities"]["next_year_effective_capacity"]
                         -relief["capacities"]["next_year_effective_capacity"], 48)
        self.assertEqual(road["unmet"]-relief["unmet"], 29)
        soil, relief = (late[k]["countries"][0] for k in ("kept_incumbent","elected"))
        self.assertEqual((soil["harvest"]-relief["harvest"], relief["relief_food"], relief["unmet"]-soil["unmet"]),
                         (20,2,18))
        fixed, platform = (tax[k]["countries"][1] for k in ("fixed","platform"))
        self.assertEqual(fixed["choice"], platform["choice"])
        self.assertEqual((platform["standing"]["food"]-fixed["standing"]["food"],
                          platform["unmet"]-fixed["unmet"]), (2,2))
