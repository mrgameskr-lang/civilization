from copy import deepcopy
import unittest
from types import SimpleNamespace

from civsim.annual_game import create
from civsim.peace62 import audit62
from civsim.research71 import prepare, post
from civsim.unit_economy import step_game


class ResearchTests(unittest.TestCase):
    def test_prior_hunger_and_failed_execution_halt_progress(self):
        site = SimpleNamespace(id=7, owner=1, farmland=48, soil=800)
        old = {"food_output":1000, "unmet":251, "food_need":1000}
        plans = {1: {"action":"soil", "target_region":7,
                     "observations":[{"region":7, "previous":old}]}}
        study, targets = prepare([site], plans, None, 4, False)
        self.assertEqual(targets, set())
        self.assertEqual(study["regions"][0]["reason"], "urgent_hunger")
        old["unmet"] = 250
        study, targets = prepare([site], plans, None, 4, False)
        self.assertEqual(targets, {7})
        post(study, [], 4)
        self.assertEqual(study["regions"][0]["reason"], "project_unfunded")
        self.assertEqual(study["regions"][0]["trial_workers"], 0)
        self.assertEqual(study["regions"][0]["closing_trials"], 0)

    def test_funded_trial_displaces_immediate_soil_treatment_and_affects_next_harvest(self):
        game = create(0)
        for year in range(1, 5):
            step_game(game, research=True if year == 1 else None, public_farm=True if year == 2 else None,
                      reserve_policy="emergency" if year == 2 else None)
        held_game = deepcopy(game)
        paid = step_game(game)
        held = step_game(held_game, hold_research=True)
        site = 28
        project, = [p for p in paid["government"]["works"]["projects"] if p["target"] == site]
        standard, = [p for p in held["government"]["works"]["projects"] if p["target"] == site]
        receipt = paid["research"]["regions"][site]
        self.assertEqual((receipt["opening_trials"], receipt["level_after"], receipt["adoption_year"]), (1,1,5))
        self.assertEqual((receipt["trial_workers"], receipt["trial_ore"], receipt["trial_tools"]), (2,1,1))
        self.assertEqual((standard["treated_tiles"], project["treated_tiles"]), (12,6))
        self.assertEqual(project["used"], standard["used"])
        self.assertEqual(project["workers"], standard["workers"])
        self.assertLess(project["soil_gain"], standard["soil_gain"])
        self.assertEqual(paid["regions"][site]["production"]["farm_tech_level"], 0)
        self.assertEqual(held["research"]["regions"][site]["closing_trials"], 1)
        applied = step_game(game)
        delayed = step_game(held_game)
        audit62(applied, geography=game.economy.world, previous_record=paid)
        self.assertTrue(applied["research"]["regions"][site]["first_application"])
        actual = applied["regions"][site]["production"]
        self.assertEqual((actual["farm_tech_level"], actual["food_without_tech"], actual["produced"]["food"]),
                         (1, 7037, 7248))
        self.assertEqual(delayed["regions"][site]["production"]["produced"]["food"], 7052)
        for field in ("farm_tech_level", "food_without_tech"):
            with self.subTest(field=field):
                bad = deepcopy(applied)
                bad["regions"][site]["production"][field] += 1
                with self.assertRaises(ValueError):
                    audit62(bad, geography=game.economy.world, previous_record=paid)
        bad = deepcopy(applied)
        bad["research"]["regions"][site]["opening_trials"] = 1
        with self.assertRaises(ValueError):
            audit62(bad, geography=game.economy.world, previous_record=paid)
        bad = deepcopy(paid)
        bad["government"]["works"]["projects"][receipt["project_id"]]["treated_tiles"] = 12
        with self.assertRaises(ValueError):
            audit62(bad, geography=game.economy.world)

    def test_activation_records_zero_progress_and_does_not_forge_payment(self):
        game = create(0)
        row = step_game(game, research=True)
        self.assertTrue(row["research"]["first_turn"])
        self.assertTrue(all(r["closing_trials"] == 0 for r in row["research"]["regions"]))
        self.assertTrue(all(r["production"]["farm_tech_level"] == 0 for r in row["regions"]))
        bad = deepcopy(row)
        bad["research"]["regions"][0]["cumulative_ore"] = 1
        with self.assertRaises(ValueError):
            audit62(bad, geography=game.economy.world)

    def test_disabled_trace_is_unmodified_and_failed_mode_change_is_atomic(self):
        game = create(0)
        baseline = step_game(game)
        self.assertNotIn("research", baseline)
        bad = deepcopy(baseline)
        bad["public_policy"]["research_rule"] = "farm-trial/1"
        bad["research"] = None
        with self.assertRaises(ValueError):
            audit62(bad, geography=game.economy.world)
        enabled = step_game(game, research=True)
        self.assertTrue(enabled["research"]["first_turn"])
        before = deepcopy(game.economy.research)
        with self.assertRaises(ValueError):
            step_game(game, research=False)
        self.assertEqual(before, game.economy.research)
        self.assertEqual(game.economy.world.year, 2)
