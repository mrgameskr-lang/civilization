from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from civsim.annual_game import create
from civsim.unit_economy import Move, step_game
from civsim.regional_custody import audit_meal_custody, position_exits


class RegionalCustodyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        game=create(0)
        step_game(game)
        cls.record=step_game(game,Move(5,5,4,1))

    def test_paid_home_issue_enters_ordinary_meals_once(self):
        receipts=audit_meal_custody(self.record)
        row=next(r for r in receipts if r["home"]==5)
        self.assertEqual((row["private_before_public"],row["public_issue"],row["meal_open"],
                          row["food_eaten"],row["food_left"]),(846,10,856,846,10))
        self.assertEqual(sum(r["food_eaten"] for r in receipts),64955)
        bad=deepcopy(self.record)
        bad["regions"][5]["consumption"]["opening_food"]+=10
        with self.assertRaises(ValueError):
            audit_meal_custody(bad)

    def test_integer_exits_have_a_place_and_a_single_cause(self):
        turn={"opening_away":[[0,1,3],[0,2,3]],"retained_away":[[0,1,3],[0,2,2]],
              "after_move_away":[[0,1,3],[0,2,2]],"closing_away":[[0,1,3]]}
        rows=[dict(id=0,owner=0,opening_roster=8,released=3,enrolled=1,serving=6,
                   service_deaths=2,service_emigrants=1,closing_roster=3)]
        rows.extend(dict(id=i,owner=0,opening_roster=0,released=0,enrolled=0,serving=0,
                         service_deaths=0,service_emigrants=0,closing_roster=0) for i in (1,2))
        trace=position_exits(turn,rows)
        self.assertEqual(trace,[{"home":0,"location":0,"released":2,"deaths":1,"emigrants":0},
                                {"home":0,"location":2,"released":1,"deaths":1,"emigrants":1}])
        turn["closing_away"]=[]
        with self.assertRaises(ValueError):
            position_exits(turn,rows)

    def test_no_receipt_reclassifies_resident_meals_as_unit_meals(self):
        food=self.record["service"]["regions"][5]["ration_food"]
        self.assertEqual(food,10)
        for field in ("ration_food","tools_used"):
            edited=deepcopy(self.record)
            edited["service"]["regions"][5][field]+=1
            with self.subTest(field=field),self.assertRaises(ValueError):
                audit_meal_custody(edited)

    def test_optional_reader_checks_existing_save_without_writing_it(self):
        save=Path(__file__).resolve().parents[1]/"examples"/"annual-unit-v1"/"position-saves"/"moved.json"
        original=save.read_bytes()
        cmd=[sys.executable,"-B","-m","civsim.annual_game","show",str(save)]
        plain=json.loads(subprocess.check_output(cmd))
        shown=json.loads(subprocess.check_output([*cmd,"--custody"]))
        view=shown.pop("custody")
        self.assertEqual(plain,shown)
        self.assertEqual(save.read_bytes(),original)
        self.assertEqual(view["present_counts"]["4"],62)
        self.assertEqual(sum(r["count"] for r in view["office_counts"]),
                         sum(r["roster_close"] for r in view["home_accounts"]))
        self.assertEqual(view["meal_receipts"][4]["public_before_relief"],{"food":0,"ore":108,"tools":73})
