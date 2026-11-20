"""Hand-calculated sector, market, and consumption scenarios."""

import unittest
from copy import deepcopy

from civsim.economy import consume, market, produce
from civsim.model import GOODS, Nation


def country(identifier=0, *, people=1000, food=0, ore=0, tools=0, cash=1000):
    return Nation(id=identifier, name=str(identifier), population=people,
                  stock={"food": food, "ore": ore, "tools": tools},
                  cash=cash, productivity=1000, technology=1000, land=20,
                  fertility=1000, ore_grade=1000, deposit=400, soil=1000)


class ProductionTests(unittest.TestCase):
    def test_neutral_country_with_no_stock(self):
        nation = country()
        record = produce(nation, 1000)
        # 500 workers, of whom 380 farm, 60 mine and 60 manufacture.
        # 30 ore are mined, all converted to 15 tools in the same year.
        self.assertEqual(record["labor"], {"farm": 380, "mine": 60, "factory": 60})
        self.assertEqual(record["produced"], {"food": 1216, "ore": 30, "tools": 15})
        self.assertEqual(record["used"], {"food": 0, "ore": 30, "tools": 0})
        self.assertEqual(nation.stock, {"food": 1216, "ore": 0, "tools": 15})
        self.assertEqual(nation.deposit, 370)
        self.assertEqual(nation.soil, 999)

    def test_limited_deposit_and_odd_ore_remainder(self):
        nation = country(ore=2)
        nation.deposit = 3
        record = produce(nation, 1000)
        self.assertEqual(record["produced"]["ore"], 3)
        self.assertEqual(record["produced"]["tools"], 2)
        self.assertEqual(nation.stock["ore"], 1)
        self.assertEqual(nation.deposit, 0)
        self.assertEqual(produce(nation, 1000)["produced"]["ore"], 0)

    def test_tools_soil_climate_and_land_constrain_harvest(self):
        base = country()
        baseline = produce(deepcopy(base), 1000)["produced"]["food"]
        equipped = country(tools=100)
        record = produce(equipped, 1000)
        self.assertGreater(record["used"]["tools"], 0)
        self.assertGreater(record["produced"]["food"], baseline)
        self.assertLess(produce(deepcopy(base), 800)["produced"]["food"], baseline)
        for name, value in (("land", 2), ("soil", 700), ("fertility", 700),
                            ("productivity", 700), ("technology", 700)):
            with self.subTest(name=name):
                constrained = deepcopy(base)
                setattr(constrained, name, value)
                self.assertLess(produce(constrained, 1000)["produced"]["food"], baseline)

    def test_large_food_reserve_shifts_workers_from_farming(self):
        poor = produce(country(), 1000)["labor"]
        rich = produce(country(food=2000), 1000)["labor"]
        self.assertLess(rich["farm"], poor["farm"])
        self.assertGreater(rich["factory"], poor["factory"])
        self.assertEqual(sum(rich.values()), sum(poor.values()))

    def test_empty_country_does_not_produce(self):
        nation = country(people=0, ore=50, tools=15)
        record = produce(nation, 1000)
        self.assertEqual(sum(record["produced"].values()), 0)
        self.assertEqual(sum(record["used"].values()), 0)
        self.assertEqual(nation.stock, {"food": 0, "ore": 50, "tools": 15})


class MarketTests(unittest.TestCase):
    def test_cash_limited_buyer_and_conserved_settlement(self):
        seller = country(0, people=100, food=224)
        buyer = country(1, people=100, food=56, cash=53)
        opening_cash = seller.cash + buyer.cash
        record = market([seller, buyer])
        # Food target 112. Seller asks 4, buyer bids 16. Five units at 10.
        self.assertEqual(record["prices"][0]["food"], 4)
        self.assertEqual(record["prices"][1]["food"], 16)
        self.assertEqual(len(record["trades"]), 1)
        trade = record["trades"][0]
        self.assertEqual(tuple(trade[k] for k in ("good", "seller", "buyer",
                                                  "quantity", "unit_price")),
                         ("food", 0, 1, 5, 10))
        self.assertEqual((seller.stock["food"], buyer.stock["food"]), (219, 61))
        self.assertEqual(buyer.cash, 3)
        self.assertEqual(seller.cash + buyer.cash, opening_cash)

    def test_affluent_buyer_cannot_drain_seller_reserve(self):
        seller = country(0, people=100, food=114)
        buyer = country(1, people=100, cash=10000)
        record = market([seller, buyer])
        self.assertEqual([row["quantity"] for row in record["trades"]], [2])
        self.assertEqual(seller.stock["food"], 112)

    def test_no_trade_without_counterparty_or_available_credit(self):
        buyer = country(0, cash=0)
        seller = country(1, food=3000)
        self.assertEqual(market([buyer, seller])["trades"], [])
        self.assertEqual(market([buyer])["trades"], [])

    def test_multi_good_partial_fills_and_order_independence(self):
        nations = [country(2, food=0, ore=0, tools=0, cash=50000),
                   country(1, food=1200, ore=80, tools=80),
                   country(3, food=1500, ore=75, tools=45)]
        reverse = list(reversed(deepcopy(nations)))
        before = {g: sum(n.stock[g] for n in nations) for g in GOODS}
        trace = market(nations)
        self.assertEqual(trace, market(reverse))
        self.assertEqual({row["good"] for row in trace["trades"]}, set(GOODS))
        self.assertEqual(before, {g: sum(n.stock[g] for n in nations) for g in GOODS})
        self.assertEqual(nations, list(reversed(reverse)))
        self.assertTrue(all(n.cash >= 0 and min(n.stock.values()) >= 0 for n in nations))


class ConsumptionTests(unittest.TestCase):
    def test_deficit_is_unmet_need_without_negative_stock(self):
        nation = country(people=100, food=35)
        record = consume(nation)
        self.assertEqual((record["food_need"], record["food_eaten"]), (100, 35))
        self.assertEqual(record["food_spoiled"], 0)
        self.assertEqual(nation.stock["food"], 0)

    def test_surplus_food_carries_after_explicit_storage_loss(self):
        nation = country(people=100, food=160, ore=4, tools=8)
        record = consume(nation)
        self.assertEqual((record["food_eaten"], record["food_spoiled"]), (100, 5))
        self.assertEqual(record["used"], {"food": 105, "ore": 0, "tools": 0})
        self.assertEqual(nation.stock, {"food": 55, "ore": 4, "tools": 8})
