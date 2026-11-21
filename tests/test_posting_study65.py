import unittest
from copy import deepcopy
from collections import Counter
from tempfile import TemporaryDirectory
from pathlib import Path
import gzip
import json

from experiments.posting_study65 import historical_controls, one_seed, regional_accounts, run_study
from experiments.posting_summary65 import goods_account


class PostingStudyTests(unittest.TestCase):
    def test_all_archived_cash_and_food_checkpoints_are_pinned(self):
        controls, pins = historical_controls()
        self.assertEqual(len(controls), 40*2*3)
        self.assertEqual(len(pins), 3)
        self.assertEqual(controls[0,"A",50]["years_sha256"],
                         "a5d465c3ac64c1720fd551ffb9490d8a88b5c8f349f002c254649d6ce512b75b")

    def test_meals_use_residents_once_and_border_sales_reconcile_cash(self):
        def region(i):
            stock={"food":3,"ore":1,"tools":1}
            return {"id":i,"owner":i,"opening":{"population":5,"cash":8,"stock":stock},
                    "closing":{"population":5,"cash":8+(-2 if i else 2),"stock":stock},
                    "consumption":{"food_need":5,"food_eaten":4,"food_unmet":1},
                    "demography":dict(births=1,deaths=1,immigrants=0,emigrants=0),
                    "production":{"produced":dict(food=4,ore=0,tools=0),"used":dict(food=0,ore=0,tools=0)}}
        rows = [region(0),region(1)]
        depots = [{"region":r["id"],"owner":r["owner"],"opening":dict(food=0,ore=0,tools=0),
                   "closing":dict(food=0,ore=0,tools=0)} for r in rows]
        accounts = [{"id":r["owner"],"private_close":r["closing"]["stock"],"public_close":d["closing"]}
                    for r,d in zip(rows,depots)]
        year = {"regions":rows,"government":{"depots":depots,"accounts":accounts},
                "border_market":{"trades":[{"seller":0,"buyer":1,"value":2,"quantity":1,"good":"tools"}]}}
        region_data = regional_accounts(year)
        self.assertEqual(sum(r["food_unmet"] for r in region_data.values()),2)
        self.assertEqual(region_data[0]["exports_value"],2)
        tampered=deepcopy(year)
        tampered["regions"][1]["consumption"]["food_need"]=6
        with self.assertRaises(ValueError):
            regional_accounts(tampered)

    def test_audited_seed_has_a_filing_then_a_carried_affiliation(self):
        with TemporaryDirectory() as folder:
            where=Path(folder)
            one_seed((0,3,where,{}))
            sample=where/"seed-00"
            cases=json.loads((sample/"cases.json").read_bytes())
            self.assertEqual((cases["held_entry"]["year"],cases["carried"]["year"]),(2,3))
            a,b=(cases["held_entry"][k] for k in ("ordinary","held"))
            def residents(book):
                values=Counter()
                for cell in book["closing"]:
                    values[cell["home"]]+=cell["count"]
                return values
            self.assertNotEqual(a["closing"],b["closing"])
            self.assertEqual(residents(a),residents(b))
            with gzip.open(sample/"affiliations.jsonl.gz","rb") as raw:
                rows=[json.loads(line) for line in raw]
            self.assertEqual(rows[1]["closing"],rows[2]["opening"])
            with self.assertRaises(FileExistsError):
                run_study(sample,"dev")

    def test_legacy_meal_from_depot_moves_between_public_and_private(self):
        r=Counter(opening_public_food=4, service_ration_food=2, meal_used_food=3, service_travel_food=1,
                  opening_public_tools=1, service_tools_used=1)
        private,public=goods_account(r,dict(food=4,tools=1,ore=0))
        self.assertEqual(private,dict(food=3,ore=0,tools=1))
        self.assertEqual(public,dict(food=1,ore=0,tools=0))
