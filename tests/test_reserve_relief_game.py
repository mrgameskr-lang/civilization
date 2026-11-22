from contextlib import redirect_stdout
from copy import deepcopy
import io
from pathlib import Path
import tempfile
import json
import unittest

from civsim.annual_game import create, load, main
from civsim.unit_economy import audit_game, step_game
from experiments.food_reserve_study import advance
from experiments.token_upkeep_study import ORDER, SELECTION


class ReserveReliefGameTests(unittest.TestCase):
    def test_shared_opening_and_real_next_year(self):
        base = create(0)
        step_game(base)
        first = advance(base,2,"C")
        control = deepcopy(base)
        normal = step_game(control)
        extra = step_game(base,reserve_policy="emergency")
        audit_game(extra,base.economy.world,first)
        self.assertEqual(normal["public_harvest"],extra["public_harvest"])
        self.assertEqual(normal["government"]["relief"],extra["government"]["relief"])
        self.assertEqual(normal["border_market"],extra["border_market"])
        self.assertEqual(normal["service"]["regions"],extra["service"]["regions"])
        self.assertGreater(extra["emergency_relief"]["delivered"],0)
        self.assertEqual(sum(r["consumption"]["food_eaten"] for r in normal["regions"]),
                         sum(r["consumption"]["food_eaten"] for r in extra["regions"]))
        following = step_game(base)
        audit_game(following,base.economy.world,extra)
        self.assertEqual(following["public_policy"]["reserve_policy"],"emergency")
        for r in extra["government"]["roads"]:
            self.assertEqual(r["capacity"], sum(r[k] for k in ("works_use","supply_use","duty_use","unit_use",
                                 "relief_use","emergency_use","private_use","unused")))

    def test_forged_records_rejected(self):
        g = create(0)
        old = step_game(g)
        row = step_game(g, ORDER, upkeep=SELECTION, reserve_policy="emergency")
        alterations = [("emergency_relief","shipments",0,"quantity"), ("emergency_relief","admin",0,"limit"),
                       ("government","roads",0,"emergency_use"), ("government","depots",0,"closing","food"),
                       ("countries",0,"closing","cash"), ("regions",0,"closing","population"),
                       ("public_harvest","regions",0,"workers_public")]
        for path in alterations:
            with self.subTest(path=path):
                changed = deepcopy(row)
                leaf = changed
                for k in path[:-1]:
                    leaf = leaf[k]
                leaf[path[-1]] += 1
                with self.assertRaises(ValueError):
                    audit_game(changed,g.economy.world,old)

    def test_all_choices_replay_through_saved_game(self):
        for name in ("7-day","14-day","emergency"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
                start, current, future = [Path(folder)/str(y) for y in range(3)]
                main(["new","--seed","0","--out",str(start)])
                main(["step",str(start),"--reserve-policy",name,"--out",str(current)])
                main(["step",str(current),"--out",str(future)])
                saved, game = load(future)
                self.assertEqual(game.economy.reserve_policy,name)
                self.assertEqual(game.economy.world.year,2)
                main(["show",str(future),"--custody"])
                forged = json.loads(future.read_bytes())
                forged["reserve_policy"] = "other"
                future.write_text(json.dumps(forged),encoding="utf-8")
                with self.assertRaises(ValueError):
                    load(future)

    def test_failure_does_not_change_policy_or_advance_time(self):
        game = create(0)
        step_game(game,reserve_policy="7-day")
        for options in ({"reserve_policy":"14-day"},{"public_farm":False},{"reserve_policy":True}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                step_game(game,**options)
            self.assertEqual((game.economy.world.year,game.economy.reserve_policy),(1,"7-day"))

    def test_relief_first_and_emergency_share_only_remaining_inventory(self):
        game = create(0)
        old = step_game(game)
        new = step_game(game, ORDER, upkeep=SELECTION, relief_first=True, reserve_policy="emergency")
        audit_game(new, game.economy.world, old)
        opening = {r["id"]:r["depot_open"] for r in new["emergency_relief"]["nodes"]}
        for group in new["unit_upkeep"]["groups"]:
            self.assertEqual(group["after"], opening[group["location"]])
