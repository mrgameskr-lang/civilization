import json
from pathlib import Path
import unittest

from civsim.model import generate_world
from civsim.regions import regionalize
from experiments.aid_incidence61 import replay_meals


class MealInputTests(unittest.TestCase):
    def test_replay_uses_only_information_available_at_dispatch_and_the_supplied_invoices(self):
        archive = Path(__file__).resolve().parents[1]/"examples/phase6a/seed0-diplomacy/years.jsonl"
        row = json.loads(archive.read_bytes().splitlines()[3])
        geometry = regionalize(generate_world(0))
        public = row["government"]
        # Whitelist pre-dispatch approvals, post-works stocks and post-production private stocks.
        # No region's observed meal, border settlement, migration, closing politics or world totals survive.
        reduced = {
            "regions":[{"id":r["id"],"opening":r["opening"],
                        "production":{"closing_stock":r["production"]["closing_stock"]}} for r in row["regions"]],
            "government":{
                "accounts":[{"id":c["id"],"decision":c["decision"]} for c in public["accounts"]],
                "works":{"nodes":[{"id":n["id"],"depot_close":n["depot_close"]} for n in public["works"]["nodes"]]},
                "roads":[{k:r[k] for k in ("a","b","capacity","works_use")} for r in public["roads"]],
            },
            "diplomacy":{"arm":row["diplomacy"]["arm"],
                         "pairs":[{"policy":p["policy"]} for p in row["diplomacy"]["pairs"]]},
            "collective":{
                "regions":[{"id":r["id"],"groups":{
                    k:{field:g[field] for field in ("action","participants","members")}
                    for k,g in r["groups"].items()}} for r in row["collective"]["regions"]],
                "responses":[{k:r[k] for k in ("id","admin_remaining","legal_concession_permille",
                                                "concession_region","concession_group")}
                             for r in row["collective"]["responses"]],
            },
        }
        invoices = row["diplomacy"]["physical"]["aid"]["shipments"]
        self.assertEqual((len(invoices),sum(s["received"] for s in invoices)),(5,228))
        for shipments,expected_eaten in ((invoices,69953),([],70090)):
            with self.subTest(shipments=len(shipments)):
                meals = replay_meals(reduced,geometry,shipments)
                self.assertEqual(len(meals),32)
                self.assertEqual(meals,replay_meals(row,geometry,shipments))
                self.assertEqual(sum(m["food_eaten"] for m in meals.values()),expected_eaten)
                if shipments:
                    self.assertEqual(meals,{r["id"]:r["consumption"] for r in row["regions"]})
