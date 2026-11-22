"""A migration can transmit a method, but adoption needs a later paid job."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

from civsim import diffusion72
from civsim.annual_game import create
from civsim.peace62 import audit62
from civsim.research71 import post, prepare
from civsim.unit_economy import step_game


class ExchangeTests(unittest.TestCase):
    def setUp(self):
        self.sites = [SimpleNamespace(id=i, owner=0, farmland=48, soil=800) for i in range(3)]
        self.roads = [SimpleNamespace(a=0, b=1, distance=3), SimpleNamespace(a=1,b=2,distance=2)]
        self.known = [{"id":i, "trials":2 if i == 0 else 0,
                       "adoption_year":2 if i == 0 else None} for i in range(3)]
        self.plans = {0:{"action":"soil", "target_region":1, "observations":[
            {"region":i,"previous":{"food_output":1000,"unmet":0,"food_need":1000}} for i in range(3)]}}

    def first_contact(self):
        log = diffusion72.opening(self.sites, self.roads, None, self.known, 3, None)
        study, _ = prepare(self.sites, self.plans, self.known, 3, False)
        post(study, [], 3)
        moves = [{"source":0,"target":1,"people":2,"distance":3},
                 {"source":1,"target":2,"people":5,"distance":2}]
        diffusion72.finish(log, study, moves, self.roads, 3)
        return log

    def test_contact_is_not_mastery_and_cannot_relay_in_same_year(self):
        contact = self.first_contact()["regions"]
        self.assertEqual(contact[1]["closing_contact"], dict(year=3,move_index=0,source=0,target=1,people=2,distance=3))
        self.assertIsNone(contact[1]["closing_method"])
        self.assertIsNone(contact[2]["closing_contact"])

    def test_current_year_mastery_and_foreign_migration_do_not_transmit(self):
        self.sites[2].owner = 1
        self.known[1]["trials"] = 1
        log = diffusion72.opening(self.sites,self.roads,None,self.known,3,None)
        studies = {"regions":[{"id":0,"level_before":1,"level_after":1,"closing_trials":2},
                              {"id":1,"level_before":0,"level_after":1,"closing_trials":2},
                              {"id":2,"level_before":0,"level_after":0,"closing_trials":0}]}
        moves = [{"source":0,"target":1,"people":1,"distance":3},
                 {"source":0,"target":2,"people":1,"distance":4},
                 {"source":1,"target":2,"people":1,"distance":2}]
        diffusion72.finish(log, studies, moves, self.roads[:1], 3)
        self.assertEqual(log["regions"][1]["closing_method"], "independent")
        self.assertTrue(all(r["closing_contact"] is None for r in log["regions"]))

    def test_invalid_historical_source_and_unmapped_domestic_move_are_rejected(self):
        state = diffusion72.closing(self.first_contact())
        self.known[0]["adoption_year"] = 3
        with self.assertRaises(ValueError):
            diffusion72.opening(self.sites,self.roads,state,self.known,4,None)
        self.known[0]["adoption_year"] = 2
        log = diffusion72.opening(self.sites,self.roads,None,self.known,3,None)
        study, _ = prepare(self.sites,self.plans,self.known,3,False)
        post(study,[],3)
        with self.assertRaises(ValueError):
            diffusion72.finish(log, study, [{"source":0,"target":2,"people":1,"distance":5}],self.roads,3)

    def test_later_paid_trial_and_two_trial_precedence(self):
        contact = diffusion72.closing(self.first_contact())
        for previous, method in [(0, "transfer"), (1, "independent")]:
            with self.subTest(previous=previous):
                research = deepcopy(self.known)
                research[1]["trials"] = previous
                log = diffusion72.opening(self.sites, self.roads, contact, research, 4, None)
                knowledge = diffusion72.by_region(log)
                study, targets = prepare(self.sites, self.plans, research, 4, False, knowledge=knowledge)
                self.assertIn(1, targets)
                unfunded = deepcopy(study)
                post(unfunded, [], 4, knowledge=knowledge)
                self.assertEqual(unfunded["regions"][1]["level_after"], 0)
                post(study,[{"target":1,"field_trial":True,"project_id":0}],4,knowledge=knowledge)
                diffusion72.finish(log, study, [], self.roads, 4)
                site = study["regions"][1]
                self.assertEqual((site["level_before"],site["level_after"],site["closing_trials"],
                                  site["trial_workers"],site["trial_ore"],site["trial_tools"]),
                                 (0,1,previous+1,2,1,1))
                self.assertEqual(log["regions"][1]["closing_method"], method)

    def test_edge_validation_and_sticky_options_are_atomic(self):
        game = create(0)
        with self.assertRaises(ValueError):
            step_game(game, diffusion=True)
        for edge in [(0,0), (True,2), (987,988), [0,1]]:
            with self.subTest(edge=edge), self.assertRaises(ValueError):
                step_game(game, research=True, diffusion=True, blocked_migration=edge)
        self.assertEqual(game.economy.world.year,0)
        baseline = step_game(deepcopy(game), research=True)
        actual = step_game(game, research=True, diffusion=True)
        self.assertEqual(actual["regions"],baseline["regions"])
        self.assertNotIn("diffusion", baseline)
        with self.assertRaises(ValueError):
            step_game(game, diffusion=False)
        self.assertEqual(game.economy.world.year, 1)
        bad = deepcopy(actual)
        bad["diffusion"]["regions"][0]["closing_method"] = "transfer"
        with self.assertRaises(ValueError):
            audit62(bad, geography=game.economy.world)

    def test_actual_migration_receipt_then_paid_adoption_then_audited_harvest(self):
        game = create(2)
        previous = None
        for year in range(1, 18):
            if year == 5:
                held = deepcopy(game)
            row = step_game(game, research=True if year==1 else None, diffusion=True if year==1 else None,
                            public_farm=True if year==2 else None, reserve_policy="emergency" if year==2 else None)
            site = row["diffusion"]["regions"][19]
            trial = row["research"]["regions"][19]
            if year == 5:
                blocked = step_game(held, blocked_migration=(16,19))
                audit62(blocked, geography=held.economy.world, previous_record=previous)
                receipt = dict(source=16, target=19, people=23, distance=10)
                self.assertEqual(row["moves"][10], receipt)
                self.assertEqual(site["closing_contact"], {**receipt, "move_index":10, "year":5})
                self.assertIsNone(blocked["diffusion"]["regions"][19]["closing_contact"])
                self.assertFalse(any({m["source"],m["target"]} == {16,19} for m in blocked["moves"]))
                self.assertEqual(row["domestic"], blocked["domestic"])
                self.assertEqual(row["border_market"], blocked["border_market"])
                bad = deepcopy(row)
                bad["diffusion"]["regions"][19]["closing_contact"]["move_index"] += 1
                with self.assertRaises(ValueError):
                    audit62(bad, geography=game.economy.world, previous_record=previous)
            if year == 6:
                reopened = step_game(held)
                self.assertEqual(reopened["diffusion"]["regions"][19]["closing_contact"]["people"],28)
                self.assertEqual(site["opening_contact"]["year"],5)
                self.assertIsNone(reopened["diffusion"]["blocked_migration"])
                bad = deepcopy(row)
                region = bad["diffusion"]["regions"][19]
                region["opening_contact"] = region["closing_contact"] = None
                with self.assertRaises(ValueError):
                    audit62(bad, geography=game.economy.world, previous_record=previous)
            if year == 16:
                self.assertEqual((trial["opening_trials"], trial["closing_trials"],trial["level_before"],trial["level_after"]),
                                 (0,1,0,1))
                self.assertEqual((trial["trial_workers"],trial["trial_ore"],trial["trial_tools"]), (2,1,1))
                self.assertTrue(row["government"]["works"]["projects"][trial["project_id"]]["field_trial"])
                self.assertEqual(site["closing_method"],"transfer")
                self.assertEqual(row["regions"][19]["production"]["farm_tech_level"],0)
            if year == 17:
                audit62(row, geography=game.economy.world, previous_record=previous)
                p = row["regions"][19]["production"]
                self.assertTrue(trial["first_application"])
                self.assertEqual((p["farm_tech_level"],p["food_without_tech"],p["produced"]["food"]), (1,1543,1589))
                self.assertEqual(trial["closing_trials"],1)
            previous = row

    def test_late_activation_keeps_independently_learned_origins(self):
        game = create(2)
        for year in range(1,5):
            previous = step_game(game, research=True if year==1 else None, public_farm=True if year==2 else None,
                                 reserve_policy="emergency" if year==2 else None)
        row = step_game(game,diffusion=True)
        audit62(row, geography=game.economy.world,previous_record=previous)
        self.assertTrue(row["diffusion"]["first_turn"])
        self.assertEqual(row["diffusion"]["regions"][16]["opening_method"],"independent")
        self.assertTrue(row["diffusion"]["regions"][19]["new_contact"])
