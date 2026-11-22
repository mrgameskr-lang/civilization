from copy import deepcopy
from itertools import product
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from civsim.annual_game import create, play, load, save
from civsim.game_journal import append_turn, new_journal
from civsim.peace62 import snapshot62
from civsim.regional_custody import audit_meal_custody
from civsim.unit_economy import Move, audit_game, step_game
from civsim.unit_upkeep import Upkeep
from experiments.priority_receipts import shortage, checkout_rows, COLUMNS
from experiments.turn_civil_balances import paired_civil_delta


class PriorityTests(unittest.TestCase):
    def test_partition_by_input_without_double_count(self):
        for n,f,t in product(range(3),range(5),range(5)):
            slots = [(j <= f, j <= t) for j in range(1,n+1)]
            expected = tuple(slots.count(pair) for pair in ((True,True),(False,True),(True,False),(False,False)))
            self.assertEqual(shortage(n,f,t),expected)
        for x in (-1, True, 0.5):
            with self.assertRaises(ValueError):
                shortage(2,x,0)

    def test_competing_claims_and_no_double_spending(self):
        g = create(0)
        for _ in range(6):
            previous = step_game(g)
        a,b,c = deepcopy(g),deepcopy(g),deepcopy(g)
        old = step_game(a,upkeep=Upkeep(5,2))
        relief = step_game(b,upkeep=Upkeep(5,2),relief_first=True)
        off = step_game(c)
        for r in (old,relief,off):
            audit_game(r,g.economy.world,previous)
            audit_meal_custody(r)
        self.assertNotIn("priority",old["unit_upkeep"])
        self.assertEqual(relief["unit_upkeep"]["version"],"annual-unit-upkeep/2")
        self.assertEqual(old["unit_upkeep"]["groups"][0]["supplied"],2)
        self.assertEqual(relief["unit_upkeep"]["groups"][0]["supplied"],0)
        self.assertEqual([v["government"]["relief"]["delivered"] for v in (old,relief,off)],[16,18,18])
        d = paired_civil_delta(old,relief)["world"]
        self.assertEqual((d["relief_delivered"],d["private_shipments"]["food"],d["food_eaten"],d["cash"]),(2,-2,0,0))
        self.assertEqual(d["government_stock"]["tools"],2)
        self.assertEqual(checkout_rows(relief)[5][COLUMNS.index("missing_food_only")],2)
        following = step_game(b)
        audit_game(following,b.economy.world,relief)
        self.assertEqual(following["unit_upkeep"]["opening"],relief["unit_upkeep"]["closing"])
        for key in ("priority","version"):
            self.assertEqual(following["unit_upkeep"][key],relief["unit_upkeep"][key])

    def test_unchanged_one_way_location_and_expenses_when_relief_has_no_claim(self):
        for q in (1,2):
            g=create(0)
            previous=step_game(g)
            old=step_game(deepcopy(g),Move(5,5,7,q),upkeep=Upkeep(5,q))
            row=step_game(g,Move(5,5,7,q),upkeep=Upkeep(5,q),relief_first=True)
            audit_game(row,g.economy.world,previous)
            self.assertEqual(row["unit_game"],old["unit_game"])
            for key in ("depots","roads","accounts"):
                self.assertEqual(row["government"][key],old["government"][key])
            self.assertEqual(row["government"]["relief"]["shipments"],old["government"]["relief"]["shipments"])
            self.assertEqual(row["unit_upkeep"]["groups"],old["unit_upkeep"]["groups"])
            self.assertEqual(row["unit_game"]["receipt"]["road_used"],q)
            self.assertEqual(step_game(g)["unit_upkeep"]["opening"],[[7,q,1]])

    def test_inconsistent_cost_or_priority_rejected_without_committing(self):
        g=create(0)
        prev=step_game(g)
        row=step_game(g,Move(5,5,7,2),upkeep=Upkeep(5,2),relief_first=True)
        snapshot=snapshot62(g.economy)
        with self.assertRaises(ValueError):
            step_game(g,relief_first=False)
        self.assertEqual(snapshot,snapshot62(g.economy))
        for change in ("drop_priority","before","phantom","wrong_version"):
            bad=deepcopy(row)
            if change=="drop_priority":
                del bad["unit_upkeep"]["priority"]
            elif change=="wrong_version":
                bad["unit_upkeep"]["version"]="annual-unit-upkeep/1"
            elif change=="phantom":
                bad["government"]["relief"]["delivered"]+=1
            else:
                bad["unit_upkeep"]["groups"][0]["before"]["food"]+=1
            with self.subTest(change=change),self.assertRaises(ValueError):
                audit_game(bad,g.economy.world,prev)

    def test_replay_and_save_preserve_selected_priority(self):
        game=create(0)
        journal=new_journal(0)
        command={"move":{"home":5,"source":5,"destination":7,"count":2},"upkeep":{"home":5,"count":2},
                 "relief_first":True}
        for c in (None,command):
            journal=append_turn(journal,c,play(game,c))
        with TemporaryDirectory() as td:
            path=Path(td)/"slot.json"
            save(path,journal,game.away,game.economy.game_upkeep)
            _,restored=load(path)
            self.assertEqual(play(game,None),play(restored,None))
            data=json.loads(path.read_bytes())
            del data["game_upkeep"]["priority"]
            path.write_text(json.dumps(data),encoding="utf-8")
            with self.assertRaises(ValueError):
                load(path)

    def test_priority_requires_active_existing_selection(self):
        g=create(0)
        with self.assertRaises(ValueError):
            step_game(g,relief_first=True)
        self.assertEqual(g.economy.world.year,0)
