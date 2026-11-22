from copy import deepcopy
import unittest

from civsim import economy
from civsim.investment import ASSETS, LIFE, prepare, produce
from civsim.rules import Rules
from tests.test_economy import country


CAPITAL = Rules(labor="reallocate", investment="capital")
INVENTORY = Rules(labor="reallocate", investment="inventory")


class InvestmentTests(unittest.TestCase):
    def test_public_produce_requires_preparation_and_runs_the_selected_policy(self):
        base = country()
        snapshot = deepcopy(base)
        with self.assertRaisesRegex(ValueError, "prepare"):
            economy.produce(base, 1000, INVENTORY)
        self.assertEqual(base, snapshot)
        result = economy.produce(prepare(base), 1000, INVENTORY)
        self.assertEqual(result["investment"]["policy"], "inventory")

    def test_preparation_copies_stocks_and_all_age_cohorts(self):
        original = country()
        national = prepare(original)
        clone = prepare(national)
        clone.stock["food"] += 1
        clone.capital["farm"][0] += 1
        self.assertEqual(original.stock["food"], national.stock["food"])
        self.assertEqual(national.capital, {k: [0]*LIFE for k in ASSETS})

    def test_surplus_tools_stop_manufacturing_and_preserve_ore(self):
        nation = prepare(country(food=500, ore=200, tools=500))
        record = produce(nation, 1000, INVENTORY)
        invest = record["investment"]
        self.assertGreater(record["factory_capacity"], 0)
        self.assertLess(invest["tool_target"], 500 - record["tool_need"])
        self.assertEqual(record["produced"]["tools"], 0)
        self.assertEqual(nation.stock["ore"], 200 + record["produced"]["ore"])

    def test_positive_return_builds_after_upkeep_and_operates_next_year(self):
        nation = prepare(country(ore=80, tools=100))
        nation.soil = 700
        cash = nation.cash
        first = produce(nation, 1000, CAPITAL)
        trace = first["investment"]
        self.assertEqual(trace["built"], {"farm": 1, "industry": 0, "land": 0})
        self.assertEqual(trace["operated"]["farm"], 0)
        self.assertEqual(trace["gross_gain_value"], 0)
        self.assertEqual(trace["construction_labor"], 6)
        self.assertEqual(first["workers"], 494)
        self.assertEqual(trace["build_used"], {"food": 0, "ore": 8, "tools": 8})
        self.assertEqual(trace["book"]["farm"], {"open_eighths": 0, "depreciation_eighths": 0,
                                                "additions_eighths": 1408, "close_eighths": 1408})
        self.assertEqual(nation.capital["farm"], [1] + [0] * 7)
        self.assertEqual(nation.cash, cash)
        for g in ("food","ore","tools"):
            self.assertEqual(first["closing_stock"][g], first["opening_stock"][g]
                             + first["produced"][g] - first["used"][g])
        second = produce(nation, 1000, CAPITAL)
        trace = second["investment"]
        self.assertEqual(trace["operated"]["farm"], 1)
        self.assertEqual(trace["upkeep_used"]["tools"], 1)
        self.assertEqual(trace["farm_multiplier"], 1012)
        self.assertGreater(trace["gross_gain_value"], 0)

    def test_unpaid_oldest_equipment_retires_and_cannot_produce_bonus(self):
        nation = prepare(country(ore=0, tools=0))
        for key in ASSETS:
            nation.capital[key][-1] = 1
        result = produce(nation, 1000, CAPITAL)["investment"]
        self.assertEqual(result["operated"], dict.fromkeys(ASSETS,0))
        self.assertEqual(result["retired"], dict.fromkeys(ASSETS,1))
        self.assertEqual(result["built"], dict.fromkeys(ASSETS,0))
        self.assertEqual(result["upkeep_used"], {"food":0,"ore":0,"tools":0})
        self.assertEqual(result["gross_gain_value"], 0)
        self.assertEqual(nation.capital, {k:[0]*8 for k in ASSETS})

    def test_book_depreciation_continues_when_equipment_is_idle_and_expires(self):
        nation = prepare(country(ore=0, tools=0))
        nation.capital["farm"][3] = nation.capital["farm"][7] = 1
        old_cash = nation.cash
        trace = produce(nation, 1000, CAPITAL)["investment"]
        self.assertEqual(trace["operated"]["farm"], 0)
        self.assertEqual(trace["retired"]["farm"], 1)
        # Construction value is 176. Opening units have 5 and 1 years remaining.
        self.assertEqual(trace["book"]["farm"], {"open_eighths": 1056, "depreciation_eighths": 352,
                                                "additions_eighths": 0, "close_eighths": 704})
        self.assertEqual(nation.cash, old_cash)

    def test_reclamation_is_bounded_by_territory_and_industry_by_resources(self):
        nation = prepare(country(ore=2, tools=100))
        nation.land = 5
        nation.deposit = 3
        nation.capital["land"][0] = nation.capital["industry"][0] = 1
        result = produce(nation, 1000, CAPITAL)
        inv = result["investment"]
        self.assertEqual((nation.land, inv["added_land_capacity"], result["land_capacity"]), (5,20,120))
        self.assertEqual(inv["industry_multiplier"], 1025)
        self.assertEqual(result["produced"]["ore"], 3)
        self.assertLessEqual(result["produced"]["tools"], 2)

    def test_rich_saturated_economy_declines_all_investments(self):
        nation = prepare(country(food=5000, ore=1000, tools=1000))
        result = produce(nation, 1000, CAPITAL)["investment"]
        self.assertEqual(result["built"], dict.fromkeys(ASSETS,0))
        self.assertTrue(all(c["net_value"] < 0 for c in result["candidates"].values()))

    def test_land_pressure_and_industrial_scarcity_select_distinct_projects(self):
        crowded = prepare(country(ore=80, tools=100))
        crowded.land = 5
        industrial = prepare(country(people=10000, food=10000, ore=500, tools=110))
        industrial.land = 300
        industrial.deposit = 10000
        for nation, kind in [(crowded, "land"), (industrial, "industry")]:
            with self.subTest(kind=kind):
                trace = produce(nation, 1000, CAPITAL)["investment"]
                self.assertEqual(trace["built"][kind], 1)
                self.assertEqual(sum(trace["built"].values()), 1)
                self.assertGreater(trace["candidates"][kind]["net_value"], 0)
                territory = nation.land
                economy.consume(nation)
                following = produce(nation, 1000, CAPITAL)
                inv = following["investment"]
                self.assertEqual(inv["operated"][kind], 1)
                self.assertEqual(nation.land, territory)
                good = "food" if kind == "land" else "ore"
                self.assertGreater(following["produced"][good], inv["reference_output"][good])
                self.assertGreater(inv["gross_gain_value"], 0)

    def test_industrial_capacity_bonus_yields_real_ore_and_tools_with_feedstock(self):
        nation = prepare(country(people=10000, food=10000, ore=5, tools=10))
        nation.land = 300
        nation.deposit = 10000
        nation.capital["industry"][0] = 5
        trace = produce(nation, 1000, CAPITAL)
        self.assertEqual(trace["investment"]["operated"]["industry"], 5)
        for good in ("ore", "tools"):
            self.assertGreater(trace["produced"][good], trace["investment"]["reference_output"][good])

    def test_inventory_target_independent_of_investment_arm(self):
        left = prepare(country(ore=80, tools=100))
        right = deepcopy(left)
        a = produce(left,1000,INVENTORY)["investment"]
        b = produce(right,1000,CAPITAL)["investment"]
        self.assertEqual(a["tool_target"], b["tool_target"])
