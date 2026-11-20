import unittest
from copy import deepcopy
from dataclasses import asdict, dataclass

from civsim.investment import InvestingNation, prepare
from civsim.regional_production import audit_production, produce_regions
from tests.test_economy import country


@dataclass(slots=True)
class ProductionRegion(InvestingNation):
    owner: int
    farmland: int


def region(uid=0, owner=0, farmland=10, people=1000, soil=1000, ore=100, tools=100):
    base = country(uid, people=people, ore=ore, tools=tools)
    base.soil = soil
    return ProductionRegion(**asdict(prepare(base)), owner=owner, farmland=farmland)


def states(regions):
    return {r.id: asdict(r) for r in regions}


class RegionalProductionTests(unittest.TestCase):
    def run_checked(self, regions, scope="regional", care=True):
        pre = states(regions)
        climate = {r.owner: 1000 for r in regions}
        p = produce_regions(regions, climate, scope, care)
        audit_production(pre, states(regions), p, climate, scope, care)
        return p

    def test_crops_use_farmland_and_no_fields_preserve_soil(self):
        barren = region(farmland=0, soil=800)
        p = self.run_checked([barren])[0]
        self.assertEqual((p["produced"]["food"], barren.soil, barren.land), (0, 800, 20))
        self.assertEqual(p["soil_care"]["packages"], 0)
        small = region(farmland=2)
        self.assertEqual(self.run_checked([small])[0]["active_farmers"], 40)

    def test_host_spends_maintenance_and_same_points_reach_only_domestic_regions(self):
        a, b, c = region(0), region(1), region(2, owner=1)
        a.capital["farm"][0] = a.capital["industry"][0] = a.capital["land"][0] = 1
        regions = [a, b, c]
        regional = self.run_checked(deepcopy(regions), "regional", False)
        national = self.run_checked(regions, "national", False)
        self.assertEqual([regional[i]["investment"]["farm_multiplier"] for i in range(3)], [1012,1000,1000])
        self.assertEqual([national[i]["investment"]["farm_multiplier"] for i in range(3)], [1006,1006,1000])
        self.assertEqual([national[i]["investment"]["industry_multiplier"] for i in range(3)], [1013,1012,1000])
        self.assertEqual([national[i]["land_capacity"] for i in range(3)], [224,200,200])
        for uid in range(3):
            for field in ("built","operated","book","upkeep_used","build_used","construction_labor"):
                self.assertEqual(regional[uid]["investment"][field], national[uid]["investment"][field])
        self.assertEqual(national[0]["investment"]["upkeep_used"], {"food":0,"ore":1,"tools":3})
        self.assertEqual(national[1]["investment"]["upkeep_used"]["tools"], 0)

    def test_soil_care_spends_existing_goods_and_labor_with_lag(self):
        # Two projects cover ten tiles, require eight workers and pay two of each material.
        weak = region(soil=900, tools=2, ore=2)
        untreated = deepcopy(weak)
        p = self.run_checked([weak])[0]
        q = self.run_checked([untreated], care=False)[0]
        s = p["soil_care"]
        self.assertEqual((s["packages"],s["treated_tiles"],s["workers"],s["recovery"]), (2,10,8,8))
        self.assertEqual(s["used"], {"food":0,"ore":2,"tools":2})
        self.assertEqual(p["workers"] + s["workers"] + p["investment"]["construction_labor"], 500)
        self.assertEqual((weak.soil, untreated.soil), (906,898))
        self.assertLess(p["produced"]["food"], q["produced"]["food"])
        self.assertEqual(p["soil_before"], q["soil_before"])

    def test_opening_maintenance_precedes_care_and_new_output_cannot_pay(self):
        r = region(soil=900, tools=1, ore=1)
        r.capital["farm"][7] = 1
        p = self.run_checked([r])[0]
        self.assertEqual(p["investment"]["operated"]["farm"], 1)
        self.assertEqual(p["soil_care"]["packages"], 0)
        self.assertEqual(p["investment"]["retired"]["farm"], 1)
        self.assertEqual(sum(p["investment"]["built"].values()), 0)
        self.assertGreater(p["produced"]["ore"], 0)

    def test_zero_rounding_gain_skips_treatment(self):
        r = region(farmland=80, soil=949, tools=1, ore=1)
        r.land = 100
        self.assertEqual(self.run_checked([r])[0]["soil_care"]["packages"], 0)

    def test_order_independence_eligibility_and_unallocated_points(self):
        a, b, c = region(0, farmland=0), region(1), region(2, owner=1, people=0)
        a.capital["farm"][3] = c.capital["farm"][0] = 1
        forward = self.run_checked(deepcopy([a,b,c]), "national", False)
        self.assertEqual(forward, self.run_checked([c,b,a], "national", False))
        self.assertEqual([forward[i]["investment"]["farm_multiplier"] for i in range(3)], [1000,1012,1000])
        self.assertEqual(forward[2]["capital_effect"]["unallocated"]["farm"], 12)

    def test_independent_audit_rejects_falsified_spending_yield_scope_or_soil(self):
        regions = [region(soil=900),region(1, soil=900)]
        regions[0].capital["farm"][1] = 1
        pre = states(regions)
        trace = self.run_checked(regions, "national")
        post = states(regions)
        for path in [("soil_care","recovery"),("soil_care","workers"),("produced","food"),
                     ("investment","construction_labor"),("investment","farm_multiplier"),
                     ("capital_effect","applied_bonus","farm")]:
            with self.subTest(path=path):
                bad = deepcopy(trace)
                obj = bad[0]
                for k in path[:-1]:
                    obj = obj[k]
                obj[path[-1]] += 1
                with self.assertRaises(ValueError):
                    audit_production(pre, post, bad, {0:1000}, "national", True)

    def test_invalid_group_cannot_partially_spend_materials(self):
        regions = [region(),region(1,owner=1)]
        pre = states(regions)
        with self.assertRaises(ValueError):
            produce_regions(regions, {0:1000})
        self.assertEqual(states(regions), pre)

    def test_invalid_opening_stock_or_capital_cannot_be_committed(self):
        for field in ("stock", "capital"):
            with self.subTest(field=field):
                regions = [region(), region(1)]
                if field == "stock":
                    regions[1].stock["ore"] = -1
                else:
                    regions[1].capital["farm"] = [0] * 7
                pre = states(regions)
                with self.assertRaises(ValueError):
                    produce_regions(regions, {0: 1000})
                self.assertEqual(states(regions), pre)

    def test_audit_accepts_json_keys_and_rejects_altered_input_or_forecast(self):
        regions = [region()]
        before = states(regions)
        trace = self.run_checked(regions)
        audit_production({"0":before[0]}, {"0":states(regions)[0]}, {"0":trace[0]}, {"0":1000})
        for path in [("productivity",), ("investment","candidates","farm","annual_gain_value")]:
            bad = deepcopy(trace)
            item = bad[0]
            for k in path[:-1]:
                item = item[k]
            item[path[-1]] += 1
            with self.assertRaises(ValueError):
                audit_production(before, states(regions), bad, {0: 1000})
