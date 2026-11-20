import unittest
from copy import deepcopy
from dataclasses import asdict

from civsim import investment, investment31
from civsim.rules import Rules
from tests.test_economy import country


def policy(name):
    return Rules(labor="reallocate", investment="capital", policy31=name)


def budgeted_nation(people=10000):
    n = investment.prepare(country(people=people, ore=500, tools=500))
    n.land = 200
    n.soil = 700
    n.deposit = 12000
    return n


class NewPolicyTests(unittest.TestCase):
    def test_coverage_and_rank_adjust_marginal_upkeep_at_fixed_asset_count(self):
        for pop, expected_bonus, expected_wear in [(2000, 36, 4), (10000, 7, 16)]:
            with self.subTest(population=pop):
                n = budgeted_nation(pop)
                n.capital["farm"][0] = 3
                p = investment31.produce(n, 1000, policy("scaled-single"))
                i = p["investment"]
                self.assertEqual(i["farm_multiplier"], 1000 + expected_bonus)
                self.assertEqual(i["class_accounts"]["farm"]["upkeep_used"]["tools"], expected_wear)
                self.assertEqual(i["operated"]["farm"], 3)

    def test_diminishing_and_combined_apply_two_rounded_scalings_in_order(self):
        for mode, farm, industry, slots in [("diminishing", 1024, 1050, 48), ("combined", 1004, 1010, 48)]:
            n = budgeted_nation()
            for k in investment.ASSETS:
                n.capital[k][0] = 3
            p = investment31.produce(n, 1000, policy(mode + "-single"))
            i = p["investment"]
            self.assertEqual((i["farm_multiplier"], i["industry_multiplier"], i["added_land_capacity"]),
                             (farm, industry, slots))
            self.assertEqual(p["land"], 200)

    def test_multi_reprices_after_each_project_and_single_starts_with_identical_budget(self):
        original = budgeted_nation()
        n, single = deepcopy(original), deepcopy(original)
        p = investment31.produce(n, 1000, policy("diminishing-multi"))
        i = p["investment"]
        s = investment31.produce(single, 1000, policy("diminishing-single"))["investment"]
        rounds = i["selection_rounds"]
        self.assertEqual(rounds[0], s["selection_rounds"][0])
        self.assertEqual([r["selected"] for r in rounds], ["farm", "farm", "farm"])
        self.assertEqual(i["construction_labor"], 18)
        self.assertEqual(i["operated"]["farm"], 0)
        self.assertEqual(i["gross_gain_value"], 0)
        self.assertEqual(n.capital["farm"][0], 3)
        for j, r in enumerate(rounds):
            self.assertEqual((r["stock"]["ore"], r["stock"]["tools"], r["workers"], r["planned"]["farm"]),
                             (500-8*j, 500-8*j, 5000-6*j, j))
        self.assertGreater(rounds[0]["candidates"]["farm"]["net_value"],
                           rounds[1]["candidates"]["farm"]["net_value"])

    def test_limited_tools_do_not_pay_later_rank_or_any_new_project(self):
        n = budgeted_nation()
        n.stock["tools"] = 11
        n.capital["farm"][0] = 3
        i = investment31.produce(n, 1000, policy("scaled-multi"))["investment"]
        self.assertEqual(i["operated"]["farm"], 2)
        self.assertEqual(i["upkeep_used"]["tools"], 10)
        self.assertEqual(sum(i["built"].values()), 0)
        self.assertIsNone(i["selection_rounds"][0]["selected"])

    def test_fixed_multi_candidates_start_at_version_three_scores(self):
        n = budgeted_nation()
        legacy = investment.produce(deepcopy(n), 1000, policy("off"))["investment"]
        upgraded = investment31.produce(n, 1000, policy("fixed-multi"))["investment"]
        self.assertEqual(legacy["candidates"], upgraded["candidates"])
        self.assertEqual(legacy["forecast_base_stock"], upgraded["forecast_base_stock"])

    def test_leave_one_class_out_values_from_both_record_versions(self):
        for name in ("off", "combined-multi"):
            n = budgeted_nation()
            n.capital["farm"][1] = 1
            start = asdict(n)
            rules = policy(name)
            module = investment if name == "off" else investment31
            p = module.produce(n, 1000, rules)
            accounts = investment31.class_accounts({"opening": start, "production": p, "climate": 1000}, rules)
            self.assertEqual(accounts["farm"]["marginal_gain_value"], p["investment"]["gross_gain_value"])
            self.assertGreater(accounts["farm"]["marginal_gain_value"], 0)
            self.assertEqual(accounts["industry"]["marginal_gain_value"], 0)
            for good in ("food", "ore", "tools"):
                self.assertEqual(sum(a["upkeep_used"][good] for a in accounts.values()), p["investment"]["upkeep_used"][good])
                self.assertEqual(sum(a["build_used"][good] for a in accounts.values()), p["investment"]["build_used"][good])
