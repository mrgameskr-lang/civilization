import json
from pathlib import Path
import unittest

from experiments.political_forks5 import study


class SingleYearChoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = study()

    def test_archived_cases_replay_from_the_full_prior(self):
        path = Path(__file__).resolve().parents[1] / "examples/phase5b/political-forks-dev0.json"
        self.assertEqual(self.result, json.loads(path.read_text(encoding="utf-8")))
        for case in self.result["cases"]:
            self.assertEqual(case["changed_country_count"], 1)
            self.assertEqual(case["prior_years"], case["year"]-1)
            self.assertTrue(case["prior_feedback"])

    def test_shipped_relief_and_retargeted_soil_change_actual_consumption(self):
        relief, soil = self.result["cases"]
        a, b = relief["economic_approval"], relief["political_approval"]
        self.assertEqual(b["world_harvest"], a["world_harvest"])
        self.assertEqual(sum(s["quantity"] for s in b["relief_shipments"]), 84)
        self.assertEqual(sum(s["quantity"] for s in a["private_shipments"])-sum(
                         s["quantity"] for s in b["private_shipments"]), 70)
        self.assertEqual(b["country_unmet"]-a["country_unmet"], -14)
        a, b = soil["economic_approval"], soil["political_approval"]
        self.assertEqual(a["border_trades"], b["border_trades"])
        self.assertEqual(a["private_shipments"], b["private_shipments"])
        self.assertEqual([b["world_unmet"]-a["world_unmet"], b["world_harvest"]-a["world_harvest"]], [2, -2])
        self.assertEqual([(r["region"], r["meal"]["food_unmet"]-s["meal"]["food_unmet"])
                          for r,s in zip(b["regions"],a["regions"],strict=True)], [(8,-30),(9,0),(10,0),(11,32)])
