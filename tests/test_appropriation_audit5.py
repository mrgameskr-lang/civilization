import json
import unittest
from copy import deepcopy

from civsim.appropriation_audit import audit_appropriations
from civsim.government import start_government, step_government
from civsim.model import generate_world
from civsim.regions import regionalize


class AppropriationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sim = start_government(regionalize(generate_world(0,12,8,3),2))
        cls.years = [step_government(sim,y,"integrated") for y in range(1,4)]

    def test_archived_and_live_decisions_match_openings_and_previous_record(self):
        for i, year in enumerate(self.years):
            audit_appropriations(year)
            prior = self.years[i-1] if i else None
            audit_appropriations(json.loads(json.dumps(year)), previous_record=prior)

    def test_rejects_changed_appropriation_or_tax_composition(self):
        for item in ("authority", "candidate_score", "constraints", "levy_component", "opening", "mode"):
            with self.subTest(item=item):
                year = deepcopy(self.years[-1])
                gov = year["government"]
                d = gov["accounts"][0]["decision"]
                if item == "authority":
                    d["quantity"] += 100_000
                    d["budget"]["admin_units"] += 100
                elif item == "candidate_score":
                    d["candidates"][0]["score"] += 1
                elif item == "constraints":
                    d["candidates"][0]["constraints"].append("fixture")
                elif item == "levy_component":
                    gov["levies"][0]["standing_levy"]["food"] += 100
                elif item == "opening":
                    d["observations"][0]["private_stock"]["food"] += 42
                else:
                    d["mode"] = "none"
                with self.assertRaises(ValueError):
                    audit_appropriations(year)

    def test_prior_record_validates_historical_observations(self):
        prior = deepcopy(self.years[-2])
        prior["regions"][0]["production"]["produced"]["food"] += 7
        with self.assertRaises(ValueError):
            audit_appropriations(self.years[-1], previous_record=prior)
        prior = deepcopy(self.years[-2])
        prior["government"]["roads"][0]["unused"] += 1
        with self.assertRaises(ValueError):
            audit_appropriations(self.years[-1], previous_record=prior)

    def test_cannot_spend_without_approved_relief_or_works(self):
        for purpose in ("road", "relief"):
            with self.subTest(purpose=purpose):
                year = deepcopy(self.years[0])
                gov = year["government"]
                self.assertEqual(gov["accounts"][0]["decision"]["action"], "defer")
                if purpose == "road":
                    gov["works"]["projects"].append({
                        "project_id": 0, "action": "build", "owner": 0, "source": 0, "target": 1,
                        "edge": [0,1], "workers": 6, "used": {"ore":6,"tools":4,"food":0},
                    })
                else:
                    gov["relief"]["shipments"].append({"owner":0, "target":0, "quantity":1,"cost_food":0})
                with self.assertRaises(ValueError):
                    audit_appropriations(year)
