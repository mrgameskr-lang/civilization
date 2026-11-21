from copy import deepcopy
from dataclasses import replace
import unittest

from civsim import peace62
from civsim.model import generate_world
from civsim.regions import regionalize
from civsim.unit_economy import AnnualUnitGame, Move, step_game, audit_game, location_totals


def opening(*, narrow=False):
    world = regionalize(generate_world(0))
    if narrow:
        world.roads = [replace(e, capacity=1) if (e.a,e.b)==(0,3) else e for e in world.roads]
    sim = peace62.start62(world)
    peace62.step62(sim, 1, "C")
    return AnnualUnitGame(sim)


class AnnualMoves(unittest.TestCase):
    def test_real_road_store_and_next_opening(self):
        game=opening()
        control=deepcopy(game)
        order=Move(home=5, source=5, destination=4, count=1)
        row=step_game(game, order)
        held=step_game(control)
        receipt=row["unit_game"]["receipt"]
        self.assertTrue(receipt["ok"])
        self.assertEqual((receipt["road"],receipt["food_spent"],receipt["road_used"]),([4,5],1,1))
        self.assertEqual(row["unit_game"]["closing_away"],[[5,4,1]])
        self.assertEqual(held["unit_game"]["closing_away"],[])
        following=step_game(deepcopy(game))
        self.assertEqual(following["unit_game"]["opening_away"],[[5,4,1]])
        audit_game(following,game.economy.world,previous=row)
        for label in ("food_before","remaining_before"):
            self.assertGreaterEqual(receipt[label],1)
        self.assertEqual(receipt["food_before"]-receipt["food_after"],1)
        self.assertEqual(receipt["remaining_before"]-receipt["remaining_after"],1)
        self.assertEqual(row["service"],held["service"])
        for key in ("countries","regions"):
            self.assertEqual([r["opening"] for r in row[key]],[r["opening"] for r in held[key]])

    def test_rejections_have_same_economic_state_as_hold(self):
        for narrow,order,reason in [
            (False,Move(4,4,5,1),"insufficient_food"),
            (False,Move(5,5,4,99999),"insufficient_tokens"),
            (True,Move(3,3,0,1),"insufficient_capacity"),
        ]:
            with self.subTest(reason=reason):
                game=opening(narrow=narrow)
                control=deepcopy(game)
                failed=step_game(game,order)
                held=step_game(control)
                receipt=failed["unit_game"]["receipt"]
                self.assertEqual((receipt["reason"],receipt["food_spent"],receipt["road_used"]),(reason,0,0))
                self.assertEqual(failed["unit_game"]["closing_away"],held["unit_game"]["closing_away"])
                self.assertEqual({k:v for k,v in failed.items() if k!="unit_game"},
                                 {k:v for k,v in held.items() if k!="unit_game"})

    def test_tampered_cost_road_population_and_position_fail_audit(self):
        game=opening()
        row=step_game(game,Move(5,5,4,1))
        road=next(i for i,r in enumerate(row["government"]["roads"]) if (r["a"],r["b"])==(4,5))
        for path in (("unit_game","receipt","food_after"),("government","roads",road,"unit_use"),
                     ("regions",5,"closing","population"),("regions",5,"closing","cash"),("unit_game","closing_away",0,2)):
            bad=deepcopy(row)
            parent=bad
            for key in path[:-1]:
                parent=parent[key]
            parent[path[-1]]+=1
            with self.subTest(path=path), self.assertRaises(ValueError):
                audit_game(bad,game.economy.world)

    def test_roster_exits_and_new_registrations_preserve_existing_positions(self):
        from civsim.unit_economy import absent_from_home, begin_turn, close_turn
        service = {"regions":[{"id":0,"owner":0,"opening_roster":5,"released":3,"enrolled":2,"closing_roster":1},
                              {"id":1,"owner":0,"opening_roster":0,"released":0,"enrolled":0,"closing_roster":0}]}
        turn = begin_turn([[0,1,4]],None,service)
        self.assertEqual(absent_from_home(turn),{0:2})
        turn["after_move_away"] = turn["retained_away"]
        close_turn(turn,service)
        self.assertEqual(turn["closing_away"],[[0,1,1]])
        self.assertEqual(location_totals({"unit_game":turn,"service":service},"closing"),{0:0,1:1})

    def test_lost_position_or_foreign_edge_is_rejected(self):
        game = opening()
        row = step_game(game,Move(5,5,4,1))
        with self.assertRaises(ValueError):
            peace62.step62(game.economy,3,"C")
        following = step_game(game,Move(5,4,0,1))
        self.assertEqual(following["unit_game"]["receipt"]["reason"],"invalid_edge")
        self.assertEqual(following["unit_game"]["closing_away"],[[5,4,1]])
        bad = deepcopy(row)
        bad["unit_game"]["closing_away"] = []
        with self.assertRaises(ValueError):
            audit_game(following,game.economy.world,previous=bad)
