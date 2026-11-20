import unittest
from copy import deepcopy
from unittest.mock import patch

from civsim.audit import BalanceError, audit
from civsim.engine import step
from civsim.investment import prepare
from civsim.model import generate_world
from civsim.rules import Rules


CAPITAL = Rules(labor="reallocate", investment="capital")
CONTROL = Rules(labor="reallocate", investment="inventory")


def operating_world():
    world = generate_world(42, width=12, height=8, nations=1)
    n = prepare(world.nations[0])
    n.population = 6000
    n.fertility = 700
    n.stock = {"food": 100, "ore": 500, "tools": 500}
    n.capital["farm"][7] = 1
    n.capital["industry"][0] = 1
    n.capital["land"][1] = 1
    world.nations[0] = n
    return world


class InvestmentAuditTests(unittest.TestCase):
    def test_capital_ages_and_annual_state_boundaries_match_for_ten_years(self):
        world = operating_world()
        for year in range(1, 11):
            previous = deepcopy(world.nations[0].capital)
            record = step(world, year, CAPITAL)
            audit(record)
            country = record["countries"][0]
            inv = country["production"]["investment"]
            self.assertEqual(country["opening"]["capital"], previous)
            for kind, cohorts in previous.items():
                self.assertEqual(inv["retired"][kind], cohorts[-1])
                self.assertEqual(country["closing"]["capital"][kind], [inv["built"][kind], *cohorts[:-1]])

    def test_changed_cohort_cost_labor_or_capacity_trace_is_rejected(self):
        record = step(operating_world(), 1, CAPITAL)
        original = record["countries"][0]["production"]["investment"]
        self.assertEqual(original["operated"], {"farm": 1, "industry": 1, "land": 1})
        self.assertEqual(sum(original["built"].values()), 1)
        edits = [
            ("upkeep_used", "tools"), ("upkeep_used", "ore"), ("build_used", "ore"),
            ("build_used", "tools"), ("sector_used", "tools"), ("retired", "farm"),
            ("built", "farm"), ("operated", "farm"), ("construction_labor", None),
            ("farm_multiplier", None), ("industry_multiplier", None), ("added_land_capacity", None),
            ("stock_after_upkeep", "tools"), ("stock_after_build", "ore"), ("tool_target", None),
        ]
        for key, subkey in edits:
            with self.subTest(key=key, subkey=subkey):
                sample = deepcopy(record)
                inv = sample["countries"][0]["production"]["investment"]
                if subkey is None:
                    inv[key] += 1
                else:
                    inv[key][subkey] += 1
                with self.assertRaises(BalanceError):
                    audit(sample)
        for boundary in ("opening", "closing"):
            with self.subTest(boundary=boundary):
                sample = deepcopy(record)
                sample["countries"][0][boundary]["capital"]["farm"][7] += 1
                with self.assertRaises(BalanceError):
                    audit(sample)

    def test_current_year_output_cannot_pay_for_opening_maintenance(self):
        world = operating_world()
        world.nations[0].stock.update(ore=0, tools=0)
        record = step(world, 1, CAPITAL)
        production = record["countries"][0]["production"]
        self.assertGreater(production["produced"]["ore"], 0)
        self.assertGreater(production["produced"]["tools"], 0)
        inv = production["investment"]
        self.assertEqual(sum(inv["operated"].values()), 0)
        self.assertEqual(sum(inv["built"].values()), 0)
        inv["operated"]["industry"] = 1
        inv["upkeep_used"].update(ore=1, tools=1)
        with self.assertRaises(BalanceError):
            audit(record)

    def test_idle_assets_depreciate_and_new_assets_retain_full_value_until_next_year(self):
        world = operating_world()
        world.nations[0].stock.update(ore=0, tools=0)
        first = step(world, 1, CAPITAL)
        account = first["countries"][0]["production"]["investment"]
        self.assertEqual(account["operated"]["farm"], 0)
        # The farm is in its final year. Value includes 8 tools, 8 ore and 6 workers.
        self.assertEqual(account["book"]["farm"],
                         {"open_eighths": 176, "depreciation_eighths": 176,
                          "additions_eighths": 0, "close_eighths": 0})
        built = step(operating_world(), 1, CAPITAL)
        capital = built["countries"][0]["production"]["investment"]
        self.assertEqual(capital["built"]["land"], 1)
        self.assertEqual(capital["book"]["land"],
                         {"open_eighths": 7 * 240, "depreciation_eighths": 240,
                          "additions_eighths": 8 * 240, "close_eighths": 14 * 240})
        # The residual still balances, but grants the new asset an unjustified charge.
        capital["book"]["land"]["depreciation_eighths"] += 240
        capital["book"]["land"]["close_eighths"] -= 240
        with self.assertRaises(BalanceError):
            audit(built)

    def test_inventory_control_requires_an_empty_asset_account_and_traced_phases(self):
        world = generate_world(12, width=8, height=6, nations=1)
        record = step(world, 1, CONTROL)
        for edit in ("unrecorded_phases", "fabricated_cohort"):
            with self.subTest(edit=edit):
                sample = deepcopy(record)
                c = sample["countries"][0]
                if edit == "unrecorded_phases":
                    del c["production"]["investment"]
                else:
                    c["closing"]["capital"]["industry"][0] = 1
                    c["production"]["investment"]["closing_capital"]["industry"][0] = 1
                with self.assertRaises(BalanceError):
                    audit(sample)

    def test_consumption_trace_must_explain_rations_spoilage_and_carry(self):
        world = operating_world()
        world.nations[0].stock["food"] = 30000
        original = step(world, 1, CAPITAL)
        for key in ("opening_food", "closing_food", "food_unmet", "food_need", "food_eaten"):
            with self.subTest(key=key):
                sample = deepcopy(original)
                sample["countries"][0]["consumption"][key] += 1
                with self.assertRaises(BalanceError):
                    audit(sample)
        # An exaggerated spoilage quantity can be perfectly balanced in the goods ledger.
        sample = deepcopy(original)
        c = sample["countries"][0]
        u = c["consumption"]
        u["food_spoiled"] += 1
        u["used"]["food"] += 1
        u["closing_food"] -= 1
        c["closing"]["stock"]["food"] -= 1
        c["demography"]["food_reserve"] -= 1
        with self.assertRaises(BalanceError):
            audit(sample)

    def test_industrial_capacity_and_depleted_mine_limit_reported_output(self):
        original = step(operating_world(), 1, CAPITAL)
        for key in ("factory_capacity", "mining_capacity", "factory_ore_limit", "ore_available"):
            with self.subTest(key=key):
                sample = deepcopy(original)
                p = sample["countries"][0]["production"]
                p[key] += 1
                with self.assertRaises(BalanceError):
                    audit(sample)
        # Shift one additional ore unit from the mine to the inventory. The physical
        # postings still balance, but the workers cannot mine that extra unit.
        sample = deepcopy(original)
        c = sample["countries"][0]
        p = c["production"]
        p["produced"]["ore"] += 1
        p["closing_stock"]["ore"] += 1
        sample["market"]["opening"]["0"]["stock"]["ore"] += 1
        c["closing"]["stock"]["ore"] += 1
        p["deposit_after"] -= 1
        c["closing"]["deposit"] -= 1
        with self.assertRaises(BalanceError):
            audit(sample)

    def test_failed_v3_audit_cannot_commit_in_place_cohort_mutations(self):
        world = operating_world()
        before = deepcopy(world)
        with patch("civsim.engine.audit", side_effect=BalanceError("forced review failure")):
            with self.assertRaises(BalanceError):
                step(world, 1, CAPITAL)
        self.assertEqual(world, before)
