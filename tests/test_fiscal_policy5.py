from copy import deepcopy
from dataclasses import dataclass
import unittest

from civsim.fiscal_policy import audit_collection, collect, decide, relief_throughput
from civsim.regions import Road


@dataclass
class State:
    id: int
    owner: int
    population: int
    soil: int
    farmland: int
    stock: dict
    cash: int = 73


def goods(food=0, ore=0, tools=0):
    return {"food": food, "ore": ore, "tools": tools}


def area(uid=0, p=1000, food=0, soil=1000):
    return State(uid, 0, p, soil, 20, goods(food, 100, 100))


def observation(need=1000, produced=1000, unmet=0, pop_delta=0, soil_delta=0):
    return {"food_need":need, "food_output":produced, "unmet":unmet, "pop_delta":pop_delta,
            "soil_delta":soil_delta}


class FiscalSelectionTests(unittest.TestCase):
    def test_relief_is_limited_by_need_stock_reach_and_administration(self):
        regions = [area(0,p=320), area(1,p=320)]
        depots = {0:goods(10), 1:goods(60)}
        prev = {0:observation(320,200,24), 1:observation(320,320)}
        disconnected = decide(0, regions, [], depots, prev, {}, "relief")
        self.assertEqual((disconnected["action"], disconnected["relief_limit"]), ("relief",10))
        road = Road(0,1,3,100,())
        connected = decide(0,regions,[road],depots,prev,{},"integrated")
        self.assertEqual(relief_throughput(640),20)
        self.assertEqual((connected["target_region"],connected["quantity"],connected["budget"]["food"]),
                         (0,20,21))

    def test_relief_forecast_prices_each_leg_and_respects_opening_shortage(self):
        places = [area(0,p=320,food=311),area(1,p=320),area(2,p=320)]
        stocks = {0:goods(2),1:goods(),2:goods(100)}
        old = {0:observation(320,200,24)}
        roads = [Road(0,1,25,8,()),Road(1,2,30,4,())]
        plan = decide(0,places,roads,stocks,old,{},"relief")
        relief = next(c for c in plan["candidates"] if c["action"]=="relief" and c["target_region"]==0)
        self.assertEqual((plan["quantity"],plan["budget"]["food"],relief["cost_value"]), (6,9,24))
        self.assertEqual([trip["quantity"] for trip in relief["inputs"]["estimated_routes"]], [2,4])
        self.assertEqual((relief["inputs"]["opening_shortage"],relief["score"]), (9,24))

    def test_congested_road_needs_exportable_surplus_at_opposite_endpoint(self):
        places = [area(0,p=5000),area(1,p=5000)]
        road = Road(0,1,8,200,())
        stock = {0:goods(100,10,8),1:goods()}
        old = {0:observation(5000,4980,80),1:observation(5000,4800,150)}
        plan = decide(0,places,[road],stock,old,{},"infrastructure",{(0,1):200})
        choice = next(c for c in plan["candidates"] if c["action"]=="road")
        self.assertEqual((choice["benefit_value"],choice["inputs"]["matched_quantity"]), (0,0))
        self.assertNotEqual(plan["action"],"road")
        places[0].stock["food"] = 60
        plan = decide(0,places,[road],stock,old,{},"infrastructure",{(0,1):200})
        choice = next(c for c in plan["candidates"] if c["action"]=="road")
        # 40 forecast surplus pays for 37 food and 3 freight; 38 would need 42.
        self.assertEqual((plan["action"],choice["inputs"]["matched_quantity"]), ("road",37))

    def test_road_and_soil_need_real_inventory_and_observed_pressure(self):
        a,b = area(0,p=5000), area(1,p=5000)
        road = Road(0,1,8,200,())
        previous = {0:observation(5000,6000),1:observation(5000,4800,150)}
        supplies = {0:goods(100,10,8),1:goods()}
        plan = decide(0,[a,b],[road],supplies,previous,{},"infrastructure", {(0,1):200})
        self.assertEqual((plan["action"],plan["target_edge"],plan["target_region"]), ("road",(0,1),0))
        self.assertEqual(plan["budget"],dict(food=2,ore=6,tools=4,workers=6,admin_units=1))
        no_funds = decide(0,[a,b],[road],{0:goods(),1:goods()},previous,{},"infrastructure",{(0,1):200})
        self.assertNotEqual(no_funds["action"],"road")
        s = area(soil=800)
        plan = decide(0,[s],[],{0:goods(0,2,2)},{0:observation(1000,1000,50,soil_delta=-2)},
                      {},"infrastructure")
        self.assertEqual((plan["action"],plan["quantity"],plan["budget"]["workers"]), ("soil",1,4))

    def test_emergency_reserve_and_defer_are_both_reachable(self):
        r = area(p=10000)
        depots = {0:goods()}
        plan = decide(0,[r],[],depots,{0:observation(10000,20000)},{},"relief")
        self.assertEqual(plan["action"],"reserve")
        idle = decide(0,[r],[],depots,{},{},"integrated")
        self.assertEqual((idle["action"],idle["admin_units"],idle["quantity"]),("defer",0,0))
        self.assertEqual(sum(idle["budget"].values()),0)

    def test_permissions_do_not_reprice_identical_candidates(self):
        r = area(p=320)
        prev = {0:observation(320,200,20)}
        stock = {0:goods(10)}
        captures = [decide(0,[r],[],stock,prev,{},mode) for mode in ("none","relief","integrated")]
        prices = [[(c["action"],c["score"]) for c in d["candidates"]] for d in captures]
        self.assertEqual(prices[0],prices[1])
        self.assertEqual(prices[1],prices[2])
        self.assertEqual([d["action"] for d in captures],["defer","relief","relief"])


class FiscalCollectionTests(unittest.TestCase):
    def test_supplemental_food_cost_is_explicit_and_all_balances_conserve(self):
        r = area(p=10000,food=20000)
        depots = {0:goods()}
        plan = decide(0,[r],[],depots,{0:observation(10000,20000)},{},"relief")
        rows = collect([r],depots,{0:plan},"relief")
        t = rows[0]
        # Private protected food = 11250. Ordinary levy capped by 10000//64 = 156.
        self.assertEqual(t["standing_levy"]["food"],156)
        self.assertEqual((t["extra_levy"]["food"],t["handling_used"]["food"]),(625,20))
        self.assertEqual((r.stock["food"],depots[0]["food"],r.cash),(19219,761,73))
        self.assertEqual(t["deposited"]["food"],761)
        audit_collection([r],{0:plan},"relief",rows)
        broken = deepcopy(rows)
        broken[0]["handling_used"]["food"] -= 1
        with self.assertRaises(ValueError):
            audit_collection([r],{0:plan},"relief",broken)

    def test_population_and_depot_caps_protect_private_rations(self):
        r = area(p=1600,food=1800)
        r.stock.update(ore=125,tools=125)
        depots = {0:goods(800,47,52)}
        d = decide(0,[r],[],depots,{},{},"integrated")
        row = collect([r],depots,{0:d},"integrated")[0]
        self.assertEqual(row["levied"],goods(0,3,0))
        self.assertEqual(depots[0],goods(800,50,52))

    def test_nonintervention_and_zero_population_do_not_create_goods(self):
        for mode,p in (("none",1000),("integrated",0)):
            r = area(p=p,food=20000)
            depots = {0:goods()}
            original = deepcopy(r)
            plan = decide(0,[r],[],depots,{}, {},mode)
            self.assertEqual(collect([r],depots,{0:plan},mode)[0]["levied"],goods())
            self.assertEqual(r,original)
            self.assertEqual(depots[0],goods())
