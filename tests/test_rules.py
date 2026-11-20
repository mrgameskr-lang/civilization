"""Labor capacity, shared import budgets and v1 trace compatibility."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import hashlib
from itertools import permutations
import json
import unittest

from civsim.economy import market, produce
from civsim.model import GOODS, climate_factor, generate_world
from civsim.rules import LEGACY, Rules
from tests.test_economy import country


class RulesTests(unittest.TestCase):
    def test_only_the_default_combination_replays_v1(self):
        self.assertEqual(LEGACY, Rules("idle", GOODS))
        for order in permutations(GOODS):
            with self.subTest(order=order):
                self.assertEqual(Rules("idle", order).version, "1.0" if order == GOODS else "2.0")
                self.assertEqual(Rules("reallocate", order).version, "2.0")
        with self.assertRaises(FrozenInstanceError):
            LEGACY.labor = "reallocate"

    def test_invalid_configuration_cannot_be_used(self):
        for labor, order in [("unknown", GOODS), ("IDLE", GOODS), ("idle", list(GOODS)),
                             ("idle", ("food", "food", "ore")), ("idle", ("ore", "tools")),
                             ("idle", ("food", "ore", "coins")), ("idle", "food,ore,tools")]:
            with self.subTest(labor=labor, order=order):
                with self.assertRaises(ValueError):
                    Rules(labor, order)

    def test_seed_42_year_one_matches_published_v1_economy_byte_digests(self):
        world = generate_world(42)
        rows = [produce(n, climate_factor(42, 1, n.id)) for n in world.nations]
        # Canonical bytes measured before rules were introduced.
        for value, digest in [
            (rows, "966eca343c24d88f52432552a9aa49284046af1279b6f4703b6519f5019b988e"),
            (market(world.nations), "33384fb49124f429d40d4ebb50665af15a4647c126ec1841c6ba1bbac9afc4a0"),
        ]:
            data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            self.assertEqual(hashlib.sha256(data.encode("utf-8")).hexdigest(), digest)

    def test_odd_surplus_workers_split_after_land_cap(self):
        nation = country(people=1005)
        nation.land = 5
        original = deepcopy(nation)
        idle = produce(original, 1000, Rules(order=("tools", "ore", "food")))
        shifted = produce(nation, 1000, Rules(labor="reallocate"))
        self.assertEqual(shifted["labor_before"], {"farm": 381, "mine": 60, "factory": 61})
        self.assertEqual(shifted["idle_before"], 281)
        self.assertEqual(shifted["idle_after"], 0)
        self.assertEqual(shifted["reassigned"], {"mine": 140, "factory": 141})
        self.assertEqual(shifted["active_labor"], {"farm": 100, "mine": 200, "factory": 202})
        self.assertEqual(shifted["active_labor"], shifted["labor"])
        self.assertEqual(shifted["workers"], sum(shifted["active_labor"].values()))
        self.assertEqual(shifted["produced"], {"food": 320, "ore": 100, "tools": 50})
        self.assertEqual(shifted["produced"]["food"], idle["produced"]["food"])
        self.assertEqual(idle["idle_before"], idle["idle_after"])
        self.assertEqual(idle["idle_after"], 281)
        self.assertEqual(idle["reassigned"], {"mine": 0, "factory": 0})
        self.assertEqual(sum(idle["active_labor"].values()) + idle["idle_after"], idle["workers"])
        self.assertEqual(nation.soil, original.soil)

    def test_reassigned_workers_still_require_ore_and_reserves(self):
        nation = country(people=1005, ore=1)
        nation.land = 5
        nation.deposit = 5
        result = produce(nation, 1000, Rules("reallocate"))
        self.assertEqual((result["mining_capacity"], result["produced"]["ore"]), (100, 5))
        self.assertEqual((result["ore_available"], result["factory_ore_limit"]), (6, 3))
        self.assertEqual((result["factory_capacity"], result["produced"]["tools"]), (67, 3))
        self.assertEqual((nation.deposit, nation.stock["ore"], nation.stock["tools"]), (0, 0, 3))

    def test_no_overflow_leaves_actual_production_unchanged(self):
        original = country(food=1000, ore=70, tools=30)
        alternate = deepcopy(original)
        baseline = produce(original, 1000)
        record = produce(alternate, 1000, Rules("reallocate"))
        self.assertEqual(record["reassigned"], {"mine": 0, "factory": 0})
        self.assertEqual(record["idle_before"], 0)
        self.assertEqual(record["produced"], baseline["produced"])
        self.assertEqual(alternate, original)

    def test_market_order_controls_which_good_spends_a_scarce_budget(self):
        seller = country(0, people=100, food=224, ore=10, tools=4)
        buyer = country(1, people=100, cash=18)
        for order, expected_good, units in [(GOODS, "food", 1),
                                            (("ore", "food", "tools"), "ore", 2),
                                            (("tools", "food", "ore"), "tools", 1)]:
            with self.subTest(order=order):
                nations = deepcopy([seller, buyer])
                result = market(nations, Rules(labor="reallocate", order=order))
                self.assertEqual(result["settlement_order"], list(order))
                self.assertEqual([(t["good"], t["quantity"]) for t in result["trades"]],
                                 [(expected_good, units)])
                self.assertEqual(nations[0].cash + nations[1].cash, seller.cash + buyer.cash)
