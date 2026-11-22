from copy import deepcopy
from types import SimpleNamespace
import unittest

from civsim import crisis73
from civsim.annual_game import create
from civsim.diplomatic_flows import ForeignFlows
from civsim.diplomatic_rules import _empty_pair
from civsim.unit_economy import audit_game, step_game


class CivilBorderTests(unittest.TestCase):
    def plan(self, *, denied=0, previous=None, hold=False, capacity=10, shortage=0, free=2):
        memory = _empty_pair(0, 1)
        memory["year"] = 2
        memory["last"][0]["trade_denied"] = denied
        memory["last"][0]["goods"]["food"] = 1
        ctx = {"year": 3, "countries": [{"id": n, "shortage_permille": shortage} for n in (0, 1)],
               "pairs": [{"a": 0, "b": 1, "opening": memory, "adjacent": capacity > 0}]}
        sites = [SimpleNamespace(id=0, owner=1), SimpleNamespace(id=1, owner=0)]
        roads = [SimpleNamespace(a=0, b=1, distance=4, capacity=capacity)]
        return crisis73.plan(ctx, sites, roads, {0: free, 1: free}, previous, hold)

    def test_actual_denial_and_geographic_border_required(self):
        self.assertEqual(self.plan(denied=5, capacity=0)["pairs"], [])
        calm, = self.plan()["pairs"]
        self.assertEqual((calm["closing_level"], calm["workers"]), (0, 0))
        active, = self.plan(denied=5)["pairs"]
        self.assertEqual((active["transition"], active["road"], active["workers"]), ("start", [1, 0], 2))
        for refusal in ({"free": 0}, {"shortage": 350}, {"hold": True}):
            with self.subTest(refusal=refusal):
                p, = self.plan(denied=5, **refusal)["pairs"]
                self.assertEqual((p["closing_level"], p["workers"]), (1, 0))

    def test_persistence_and_quiet_relaxation(self):
        old = [{"a": 0, "b": 1, "level": 1}]
        high, = self.plan(denied=5, previous=old)["pairs"]
        self.assertEqual((high["transition"], high["closing_level"]), ("escalate", 2))
        low, = self.plan(previous=[{"a": 0, "b": 1, "level": 2}])["pairs"]
        self.assertEqual((low["transition"], low["closing_level"]), ("ease", 1))
        resolved, = self.plan(previous=old)["pairs"]
        self.assertEqual((resolved["transition"], resolved["closing_level"]), ("resolve", 0))

    def test_desk_budget_shared_across_directions_goods_and_people(self):
        road = SimpleNamespace(a=0, b=1, capacity=10, distance=4)
        sites = [SimpleNamespace(id=i, owner=i) for i in range(2)]
        directions = [{"source": i, "target": 1-i, "trade_limit_permille": 500, "migration_limit_permille": 500,
                       "migration_accept_permille": 500, "aid_quantity": 0} for i in range(2)]
        ctx = {"arm": "D", "pairs": [{"policy": {"directions": directions, "agreement_active": False}}]}
        desk = {"road": [0, 1], "staffed": True, "goods_released": 0, "people_released": 0}
        flows = crisis73.Appeals(ForeignFlows(ctx, sites, [road], 10), {"pairs": [desk]})
        self.assertEqual(flows.trade(0, 1, "food", road, 7), 7)
        self.assertEqual(flows.trade_attempts[0]["ordinary_passed"], 5)
        self.assertEqual((flows.direction_used[0, 1], flows.private_used[0, 1]), (7, 7))
        donor, host = {"requested_departures": 8}, {"host_capacity": 6}
        self.assertEqual(flows.migrate(1, 0, 6, donor, host), 5)
        receipt = flows.migration_attempts[-1]
        self.assertEqual((receipt["ordinary_passed"], receipt["appeal_granted"], receipt["denied_exit"],
                          receipt["denied_entry"]), (3, 2, 1, 0))
        self.assertEqual((flows.exits[1, 0], flows.entries[1, 0]), (5, 5))
        self.assertEqual(flows.trade(0, 1, "ore", road, 2), 0)
        self.assertEqual((desk["goods_released"], desk["people_released"]), (2, 2))

    def test_road_without_desk_retains_ordinary_receipts(self):
        road = SimpleNamespace(a=0, b=1, capacity=8, distance=4)
        sites = [SimpleNamespace(id=i, owner=i) for i in range(2)]
        flags = {"source": 0, "target": 1, "trade_limit_permille": 500, "migration_limit_permille": 1000,
                 "migration_accept_permille": 1000, "aid_quantity": 0}
        ctx = {"arm": "D", "pairs": [{"policy": {"directions": [flags], "agreement_active": False}}]}
        original = ForeignFlows(ctx, sites, [road], 10)
        active = crisis73.Appeals(deepcopy(original), {"pairs": []})
        self.assertEqual(original.trade(0, 1, "tools", road, 7), active.trade(0, 1, "tools", road, 7))
        self.assertEqual(original.trade_attempts, active.trade_attempts)

    def test_real_opening_labour_census_and_commerce_audit(self):
        game = create(0)
        for year in range(1, 6):
            previous = step_game(game, research=True if year == 1 else None, diffusion=True if year == 1 else None,
                                 crisis=True if year == 1 else None, public_farm=True if year == 2 else None,
                                 reserve_policy="emergency" if year == 2 else None)
        held = deepcopy(game)
        actual = step_game(game)
        control = step_game(held, hold_response=True)
        original_works = deepcopy(actual["government"]["works"])
        audit_game(actual, game.economy.world, previous=previous)
        self.assertEqual(actual["government"]["works"], original_works)
        audit_game(control, held.economy.world, previous=previous)
        i, pair = next((i, p) for i, p in enumerate(actual["crisis"]["pairs"]) if p["staffed"])
        self.assertEqual((pair["a"], pair["b"], pair["road"], pair["workers"], pair["people_released"]),
                         (2, 3, [9, 15], 2, 3))
        for row, expected in ((actual, 11), (control, 8)):
            receipt, = [m for m in row["moves"] if (m["source"], m["target"]) == (15, 9)]
            self.assertEqual(receipt["people"], expected)
        for endpoint in pair["road"]:
            self.assertEqual(actual["regions"][endpoint]["production"]["workers"] + 1,
                             control["regions"][endpoint]["production"]["workers"])
        for key, wrong in (("people_released", 4), ("workers", 0), ("evidence_year", 6),
                           ("opening_level", 0), ("road", [8, 15])):
            bad = deepcopy(actual)
            bad["crisis"]["pairs"][i][key] = wrong
            with self.subTest(key=key), self.assertRaises(ValueError):
                audit_game(bad, game.economy.world, previous=previous)
        bad = deepcopy(actual)
        invoice = next(m for m in bad["diplomacy"]["physical"]["migration_attempts"] if m.get("appeal_granted"))
        invoice["ordinary_passed"] += 1
        with self.assertRaises(ValueError):
            audit_game(bad, game.economy.world, previous=previous)

    def test_policy_cannot_silently_disappear_or_hold_disabled_response(self):
        game = create(1)
        with self.assertRaises(ValueError):
            step_game(game, hold_response=True)
        self.assertEqual(game.economy.world.year, 0)
        step_game(game, crisis=True)
        with self.assertRaises(ValueError):
            step_game(game, crisis=False)
        self.assertEqual(game.economy.world.year, 1)
