from copy import deepcopy
from types import SimpleNamespace as Row
import unittest

from civsim.fiscal_policy import decide
from civsim.political_rules import initial_politics, observe, prioritize


def goods(food=0, ore=0, tools=0):
    return {"food":food, "ore":ore, "tools":tools}


def sample():
    regions = [Row(id=i,owner=0,population=100,stock=goods(),soil=1000,farmland=4) for i in (0,1)]
    record = {"year":1, "regions":[], "domestic":{"nodes":[],"shipments":[]},
              "government":{"levies":[],"depots":[],"roads":[],"works":{"projects":[]},"relief":{"shipments":[]}}}
    for r in regions:
        record["regions"].append({"id":r.id,"owner":0,"opening":{"population":100,"soil":1000},
                "closing":{"soil":1000}, "consumption":{"food_need":100,"food_eaten":100,"food_unmet":0},
                "production":{"labor":{"farm":25,"mine":10,"factory":10},"produced":goods(100,20,10)}})
        record["domestic"]["nodes"].append({"id":r.id,"targets":goods(100,10,10),"unmet_after":goods()})
        record["government"]["levies"].append({"region":r.id,"levied":goods()})
        record["government"]["depots"].append({"region":r.id,"closing":goods()})
    return regions, record


class PoliticalRuleTests(unittest.TestCase):
    def test_initial_classification_waits_for_labor_and_empty_states_are_neutral(self):
        regions, record = sample()
        initial = initial_politics(Row(regions=regions))
        self.assertEqual(initial[0]["unclassified"],100)
        snapshot = deepcopy(initial)
        result = observe(record,initial)
        self.assertEqual(initial,snapshot)
        groups = result[0]["groups"]
        self.assertEqual([g["members"] for g in groups.values()], [25,20,55])
        self.assertTrue(all((g["support"],g["discontent"],g["demand"])==(500,0,"none") for g in groups.values()))
        record["regions"][0]["production"]["labor"].update(farm=0)
        record["government"]["levies"][0]["levied"] = goods(5)
        result = observe(record,initial)
        self.assertEqual(result[0]["groups"]["consumer"]["levy_value"],40)
        self.assertEqual(result[0]["groups"]["farm"]["pressure"],0)

    def test_hunger_lags_tax_incidence_relief_allocation_and_persistence(self):
        regions, record = sample()
        initial = initial_politics(Row(regions=regions))
        record["regions"][0]["consumption"].update(food_eaten=60,food_unmet=40)
        record["government"]["levies"][0]["levied"] = goods(4,2,1)
        record["government"]["relief"]["shipments"].append({"target":0,"quantity":11})
        result = observe(record,initial)
        self.assertEqual(result[0]["evidence"]["country_shortage_permille"],200)
        groups = result[0]["groups"]
        self.assertEqual([g["relief_food"] for g in groups.values()],[3,2,6])
        self.assertEqual([g["levy_value"] for g in groups.values()],[32,20,0])
        self.assertTrue(all(g["demand"]=="relief" and g["age"]==1 for g in groups.values()))
        record["year"] += 1
        next_state = observe(record,result)
        self.assertEqual(next_state[0]["groups"]["farm"]["age"],2)
        self.assertLess(next_state[0]["groups"]["farm"]["support"],groups["farm"]["support"])
        self.assertGreater(next_state[0]["groups"]["farm"]["pressure"],groups["farm"]["pressure"])
        self.assertEqual(result[1]["groups"]["farm"]["discontent"],0)
        record["year"] += 1
        record["regions"][0]["consumption"].update(food_eaten=100,food_unmet=0)
        third = observe(record,next_state)
        self.assertEqual(third[0]["groups"]["consumer"]["demand"],"reserve")
        record["year"] += 1
        fourth = observe(record,third)
        history = fourth[0]["groups"]["farm"]["history"]
        self.assertEqual([item["year"] for item in history],[2,3,4])
        self.assertEqual(history[0]["burden"],next_state[0]["groups"]["farm"]["burden"])
        self.assertEqual(history[0]["levy_value"],32)

    def test_credited_road_cargo_uses_only_the_extra_final_leg(self):
        regions, record = sample()
        initial = initial_politics(Row(regions=regions))
        record["government"]["roads"] = [{"a":0,"b":1,"base":10,"capacity":58,
                    "opening_units":1,"works_use":2,"relief_use":1,"private_use":12,"unused":43}]
        record["domestic"]["shipments"] = [{"source":0,"target":1,"good":"ore","quantity":12,
                                          "legs":[{"a":0,"b":1}]}]
        after = observe(record,initial)
        self.assertEqual(after[1]["evidence"]["road_enabled_receipts"],goods(0,5,0))
        self.assertEqual(after[0]["evidence"]["road_enabled_receipts"],goods())
        self.assertEqual(after[1]["groups"]["industry"]["benefit"],125)

    def test_priority_changes_target_and_cannot_bypass_hard_constraints(self):
        regions, record = sample()
        states = initial_politics(Row(regions=regions))
        previous = {i:{"unmet":5,"food_need":100,"food_output":80,"pop_delta":0,"soil_delta":0} for i in states}
        plan = decide(0,regions,[],{i:goods(10) for i in states},previous,{},"integrated")
        self.assertEqual((plan["action"],plan["target_region"]),("relief",0))
        selected, trace = prioritize(plan,states)
        self.assertEqual(selected, plan)
        self.assertFalse(trace["changed"])
        selected["candidates"][0]["budget"]["food"] = 9999
        self.assertNotEqual(selected,plan)
        observed = observe(record,states)
        observed[1]["groups"]["consumer"].update(demand="relief",pressure=1000,age=4)
        selected, trace = prioritize(plan,observed)
        self.assertEqual((selected["target_region"],selected["budget"]),(1,plan["budget"]))
        self.assertTrue(trace["changed"])
        self.assertTrue(all(c["total_score"]==c["economic_score"]+c["political_score"] for c in trace["candidates"]))
        disabled = decide(0,regions,[],{i:goods() for i in states},previous,{},"integrated")
        self.assertEqual(prioritize(disabled,observed)[0]["action"],"defer")

    def test_canonical_json_key_order_gives_identical_contributions(self):
        regions, record = sample()
        old = initial_politics(Row(regions=regions))
        record["regions"][1]["consumption"].update(food_eaten=40,food_unmet=60)
        observed = observe(record,old)
        previous = {i:{"unmet":5,"food_need":100,"food_output":80,"pop_delta":0,"soil_delta":0} for i in observed}
        plan = decide(0,regions,[],{i:goods(10) for i in observed},previous,{},"integrated")
        reordered = deepcopy(observed)
        for state in reordered.values():
            state["groups"] = dict(sorted(state["groups"].items()))
        self.assertEqual(prioritize(plan,observed),prioritize(plan,reordered))

    def test_country_can_defer_or_keep_economic_choice_despite_another_demand(self):
        regions, record = sample()
        states = observe(record,initial_politics(Row(regions=regions)))
        previous = {i:{"unmet":1,"food_need":100,"food_output":90,"pop_delta":0,"soil_delta":0} for i in states}
        plan = decide(0,regions,[],{i:goods(10) for i in states},previous,{},"integrated")
        for state in states.values():
            for g in state["groups"].values():
                g.update(demand="defer",pressure=1000,age=20)
        selected, trace = prioritize(plan,states)
        self.assertEqual((selected["action"],selected["budget"]["food"]),("defer",0))
        self.assertTrue(trace["changed"])
        for state in states.values():
            for g in state["groups"].values():
                g["pressure"] = 100
        self.assertEqual(prioritize(plan,states)[0],plan)
