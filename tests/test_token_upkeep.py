import json
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from civsim.annual_game import create, load, play, save
from civsim.game_journal import append_turn, new_journal
from civsim.peace62 import snapshot62
from civsim.regional_custody import audit_meal_custody, position_exits
from civsim.unit_economy import Move, audit_game, step_game
from civsim.unit_upkeep import Upkeep, close, settle
from experiments.turn_civil_balances import paired_civil_delta


class LocalInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.game = create(0)
        cls.first = step_game(cls.game)

    def play_two(self, count=2, dest=7):
        game = deepcopy(self.game)
        paid = step_game(game, Move(5, 5, dest, count), upkeep=Upkeep(5, count))
        following = step_game(game)
        audit_game(paid, game.economy.world, self.first)
        audit_game(following, game.economy.world, paid)
        audit_meal_custody(paid)
        audit_meal_custody(following)
        return paid, following

    def test_one_piece_pays_at_destination_and_next_turn_rechecks(self):
        first, following = self.play_two(1)
        issue = first["unit_upkeep"]
        g, = issue["groups"]
        self.assertEqual((g["location"], g["nominal"], g["supplied"], g["unsupplied"]), (7, 1, 1, 0))
        self.assertEqual(g["before"], {"food":1, "ore":4, "tools":3})
        self.assertEqual(g["after"], {"food":0, "ore":4, "tools":2})
        self.assertEqual(issue["closing"], following["unit_upkeep"]["opening"])
        self.assertEqual(following["unit_upkeep"]["closing"], [[7, 1, 0]])
        self.assertEqual(following["unit_game"]["closing_away"], [[5, 7, 1]])

    def test_partial_and_empty_issues_do_not_move_or_delete_pieces(self):
        partial, _ = self.play_two()
        g, = partial["unit_upkeep"]["groups"]
        self.assertEqual((g["nominal"], g["supplied"], g["unsupplied"]), (2, 1, 1))
        empty, _ = self.play_two(2, 4)
        g, = empty["unit_upkeep"]["groups"]
        self.assertEqual((g["nominal"], g["supplied"], g["unsupplied"]), (2, 0, 2))
        self.assertEqual(g["after"], g["before"])
        self.assertEqual(empty["unit_game"]["closing_away"], [[5, 4, 2]])

    def test_same_opening_switch_and_hold_charge_the_same_real_accounts(self):
        cmd = Move(5, 5, 7, 2)
        on = step_game(deepcopy(self.game), cmd, upkeep=Upkeep(5, 2))
        off = step_game(deepcopy(self.game), cmd)
        hold = step_game(deepcopy(self.game), upkeep=Upkeep(5, 2))
        diff = paired_civil_delta(off, on)["world"]
        self.assertEqual(diff["government_stock"], {"food":-1, "ore":0, "tools":-1})
        for k in ("road_used", "cash", "population", "relief_delivered", "food_eaten", "food_unmet"):
            self.assertEqual(diff[k], 0)
        self.assertFalse(any(diff["private_shipments"].values()))
        self.assertEqual(on["service"], off["service"])
        self.assertEqual(on["unit_game"], off["unit_game"])
        self.assertEqual(paired_civil_delta(hold, on)["world"]["road_used"], 2)
        self.assertEqual(hold["unit_upkeep"]["closing"], [[5, 2, 2]])
        self.assertEqual(on["unit_upkeep"]["closing"], [[7, 2, 1]])
        self.assertNotIn("unit_upkeep", off)

    def test_late_activation_marks_existing_visitors_and_rejected_orders_do_not_move_tags(self):
        game = deepcopy(self.game)
        step_game(game, Move(5, 5, 7, 2))
        failed = step_game(game, Move(5, 7, 5, 3), upkeep=Upkeep(5, 2))
        self.assertFalse(failed["unit_game"]["receipt"]["ok"])
        self.assertEqual(failed["unit_upkeep"]["opening"], [[7, 2, 0]])
        self.assertEqual(failed["unit_upkeep"]["marked_moved"], 0)

    def test_home_register_declines_and_location_still_reconciles(self):
        game = create(2)
        prev = step_game(game)
        for year in range(2, 6):
            row = step_game(game, Move(7, 7, 4, 1) if year == 2 else None,
                            upkeep=Upkeep(7, 1) if year == 2 else None)
            audit_game(row, game.economy.world, prev)
            exits = position_exits(row["unit_game"], row["service"]["regions"])
            prev = row
        home = next(r for r in row["service"]["regions"] if r["id"] == 7)
        self.assertLess(home["closing_roster"], home["opening_roster"])
        self.assertTrue(any(e["home"] == 7 for e in exits))
        self.assertEqual(row["unit_upkeep"]["closing"][0][:2], [4, 1])

    def test_release_and_later_demographic_exit_do_not_create_replacements(self):
        staff = {"regions":[{"id":0, "opening_roster":3, "released":2, "serving":2, "closing_roster":0}]}
        turn = {"opening_away":[[0,1,2]], "retained_away":[[0,1,1]], "after_move_away":[[0,1,1]],
                "closing_away":[], "receipt":None}
        # One pre-marked visitor exits at opening. The remaining visitor exits at close.
        stock = {1:{"food":2, "tools":1, "ore":0}}
        issue = settle(Upkeep(0,2), [[1,2,1]], turn, staff, stock)
        close(issue, turn, staff)
        self.assertEqual((issue["released"],issue["demographic_exits"],issue["closing"]), (1,1,[]))
        self.assertEqual(stock[1], {"food":1, "tools":0, "ore":0})
        next_turn = {"opening_away":[], "retained_away":[], "after_move_away":[], "receipt":None}
        self.assertEqual(settle(Upkeep(0,2), [], next_turn, staff, {})["groups"], [])

    def test_reject_changed_receipts_and_discontinuous_saved_status(self):
        r, following = self.play_two()
        targets = [("unit_upkeep","groups",0,"supplied"), ("unit_upkeep","groups",0,"tools"),
                   ("unit_upkeep","groups",0,"after","food"), ("unit_upkeep","closing",0,2),
                   ("unit_upkeep","groups",0,"location"), ("government","accounts",1,"totals","unit_upkeep_tools")]
        for path in targets:
            bad = deepcopy(r)
            obj = bad
            for key in path[:-1]:
                obj = obj[key]
            obj[path[-1]] += 1
            with self.subTest(path=path), self.assertRaises(ValueError):
                audit_game(bad, self.game.economy.world, self.first)
        following["unit_upkeep"]["opening"][0][2] = 0
        with self.assertRaises(ValueError):
            audit_game(following, self.game.economy.world, r)

    def test_legacy_control_and_custody_reject_unposted_inventory(self):
        from civsim.peace62 import audit62, step62
        game = create(2)
        control = step62(game.economy, 1, "A")
        control["unit_upkeep"] = {"groups":[]}
        with self.assertRaises(ValueError):
            audit62(control, geography=game.economy.world)
        bad = deepcopy(self.first)
        bad["unit_upkeep"] = {"groups":[{"location":999,"food":1,"tools":1}]}
        with self.assertRaises(ValueError):
            audit_meal_custody(bad)

    def test_real_domestic_relief_and_private_market_respond_to_checkout(self):
        game = create(0)
        for _ in range(6):
            previous = step_game(game)
        other = deepcopy(game)
        off = step_game(game)
        on = step_game(other, upkeep=Upkeep(5,2))
        audit_game(on, other.economy.world, previous)
        delta = paired_civil_delta(off,on)["world"]
        self.assertEqual(on["unit_upkeep"]["closing"], [[5,2,2]])
        self.assertEqual((delta["relief_delivered"],delta["private_shipments"]["food"],delta["food_eaten"]),
                         (-2, 2, 0))

    def test_actual_group_can_split_across_two_existing_cells(self):
        row = step_game(deepcopy(self.game), Move(5,5,7,1), upkeep=Upkeep(5,2))
        self.assertEqual(row["unit_upkeep"]["closing"], [[5,1,1],[7,1,1]])
        for g in row["unit_upkeep"]["groups"]:
            self.assertEqual(g["before"]["tools"] - g["after"]["tools"], 1)

    def test_empty_tool_shelf_leaves_twenty_two_food_in_actual_depot(self):
        game = create(0)
        for _ in range(9):
            previous = step_game(game)
        row = step_game(game, upkeep=Upkeep(3,2))
        audit_game(row, game.economy.world, previous)
        issue = row["unit_upkeep"]
        g, = issue["groups"]
        self.assertEqual((g["before"], g["after"]), ({"food":22,"ore":14,"tools":0},)*2)
        self.assertEqual((g["supplied"],g["unsupplied"],issue["closing"]), (0,2,[[3,2,0]]))

    def test_replay_save_and_atomic_invalid_selection(self):
        game = create(0)
        journal = new_journal(0)
        cmd = {"upkeep":{"home":5, "count":2},"move":{"home":5,"source":5,"destination":7,"count":2}}
        for c in (None, cmd):
            journal = append_turn(journal,c,play(game,c))
        before = snapshot62(game.economy)
        with self.assertRaises(ValueError):
            step_game(game, upkeep=Upkeep(4,1))
        self.assertEqual(before,snapshot62(game.economy))
        with TemporaryDirectory() as td:
            path = Path(td)/"turn2.json"
            save(path,journal,game.away,game.economy.game_upkeep)
            j, recovered = load(path)
            self.assertEqual(j,journal)
            self.assertEqual(play(recovered,None),play(game,None))
            bad = json.loads(path.read_bytes())
            bad["game_upkeep"]["closing"][0][2] = 0
            path.write_text(json.dumps(bad),encoding="utf-8")
            with self.assertRaises(ValueError):
                load(path)
