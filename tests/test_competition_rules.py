from copy import deepcopy
from types import SimpleNamespace
import unittest

from civsim.competition_rules import FACTIONS, cabinet_plan, differentiated_observe, elect, initial_cabinets
from civsim.fiscal_policy import ACTIONS, decide
from civsim.political_rules import initial_politics, prioritize
from tests.test_political_rules import goods, sample


def fixture():
    regions,record = sample()
    for r in record["regions"]:
        p = r["production"]
        p.update(farmland=5,tool_need=5,closing_stock=goods(100,30,10),factory_capacity=20,mining_capacity=20,
                 investment={"tool_target":10,"sector_used":goods(0,0,5)})
        r["closing"].update(stock=goods(10))
    record["government"]["roads"] = [{"a":0,"b":1,"base":10,"capacity":10,"unused":0,"opening_units":0,
                                      "works_use":0,"relief_use":0}]
    return SimpleNamespace(regions=regions), record


def single_issue(world, issue, *, support=500):
    states = initial_politics(world)
    for state in states.values():
        state.update(year=4,unclassified=0,membership_known=True)
        g = state["groups"]["consumer"]
        g.update(members=state["population"],demand=issue,pressure=1000,support=support)
        g["signals"][issue]=1000
    return states


class CompetitionRulesTests(unittest.TestCase):
    def test_physical_bottlenecks_and_different_groups_in_same_region(self):
        w,r = fixture()
        n = r["regions"][0]
        n["consumption"].update(food_unmet=20,food_eaten=80)
        n["closing"]["soil"]=750
        n["production"].update(produced=goods(45,0,0),closing_stock=goods(45,0,0))
        n["production"]["investment"]["tool_target"]=20
        state=differentiated_observe(r,initial_politics(w))[0]
        self.assertEqual(state["evidence"]["factory_input_gap"],1000)
        self.assertEqual(state["groups"]["industry"]["demand"],"road")
        self.assertEqual(state["groups"]["farm"]["demand"],"soil")
        self.assertEqual(state["groups"]["consumer"]["demand"],"relief")
        self.assertEqual(set(state["groups"]["farm"]["signals"]),set(ACTIONS))
        n["production"].update(closing_stock=goods(45,0,20),mining_capacity=0)
        self.assertEqual(differentiated_observe(r,initial_politics(w))[0]["evidence"]["factory_input_gap"],0)

    def test_exhaustion_without_an_input_or_stock_shortfall_gives_no_road_claim(self):
        w,r = fixture()
        r["regions"][0]["production"].update(mining_capacity=40,produced=goods(100,0,10))
        state = differentiated_observe(r,initial_politics(w))[0]
        self.assertEqual(state["evidence"]["mine_depletion"],1000)
        self.assertEqual(state["groups"]["industry"]["signals"]["road"],0)

    def test_lagged_harvest_change_and_reserve_track_paid_outcomes(self):
        w,r=fixture()
        old=differentiated_observe(r,initial_politics(w))
        r["year"]=2
        r["regions"][0]["production"]["produced"]["food"]=50
        r["regions"][0]["closing"]["stock"]["food"]=0
        n=differentiated_observe(r,old)[0]
        self.assertEqual(n["evidence"]["yield_decline"],500)
        self.assertEqual(n["groups"]["consumer"]["signals"]["reserve"],500)
        self.assertEqual(n["groups"]["farm"]["history"][-1]["year"],2)

    def test_election_calendar_seats_retention_turnover_and_no_participation(self):
        w,_=fixture()
        c=initial_cabinets(w)
        states=single_issue(w,"soil")
        for y in range(1,5):
            c,tr=elect(y,states,c)
            self.assertEqual(c[0]["incumbent"],"caretaker")
        c,tr=elect(5,states,c)
        self.assertEqual(c[0]["incumbent"],"stewards")
        self.assertTrue(tr[0]["installation"])
        self.assertFalse(tr[0]["turnover"])
        self.assertEqual(sum(tr[0]["seats"].values()),21)
        self.assertEqual(sum(tr[0]["vote_points"].values()),tr[0]["participation_points"])
        road=single_issue(w,"road")
        interim,forecast=elect(6,road,c)
        self.assertEqual((interim[0]["incumbent"],forecast[0]["leading_faction"]),("stewards","builders"))
        new,tr=elect(9,road,interim)
        self.assertTrue(tr[0]["turnover"])
        self.assertEqual(new[0]["incumbent"],"builders")
        empty,trace=elect(13,initial_politics(w),new)
        self.assertEqual(empty[0]["incumbent"],"builders")
        self.assertEqual(empty[0]["seats"],new[0]["seats"])
        self.assertEqual(trace[0]["participation_points"],0)

    def test_incumbent_performance_changes_a_close_vote(self):
        w,_=fixture()
        c=initial_cabinets(w)
        c[0]["incumbent"]="builders"
        states=single_issue(w,"soil")
        for s in states.values():
            g=s["groups"]["consumer"]
            g["signals"]["road"]=960
            g["support"]=900
        _,good=elect(9,states,c)
        for s in states.values(): s["groups"]["consumer"]["support"]=100
        _,bad=elect(9,states,c)
        self.assertGreater(good[0]["vote_points"]["builders"],bad[0]["vote_points"]["builders"])

    def test_only_d_can_pay_a_capped_real_loss_with_a_graded_mandate(self):
        w,_=fixture()
        for r in w.regions: r.population=2000
        states=single_issue(w,"soil")
        c=initial_cabinets(w)[0]
        previous={i:{"food_need":2000,"food_output":2000,"unmet":0,"pop_delta":0,"soil_delta":0} for i in states}
        w.regions[0].soil=800
        plan=decide(0,w.regions,[],{i:goods(0,2,2) for i in states},previous,{},"integrated")
        soil=next(q for q in plan["candidates"] if q["action"]=="soil" and q["target_region"]==0)
        soil.update(benefit_value=40,cost_value=64,score=-24)
        self.assertEqual(cabinet_plan(plan,states,c,True)[0],prioritize(plan,states)[0])
        c["incumbent"]="stewards"
        self.assertEqual(cabinet_plan(plan,states,c,False)[0]["action"],"defer")
        choice,trace=cabinet_plan(plan,states,c,True)
        self.assertEqual(choice["action"],"soil")
        self.assertEqual(choice["budget"],soil["budget"])
        self.assertTrue(trace["exception_used"])
        for updates in ({"constraints":["unpaid"]},{"score":-500},{"benefit_value":0},{"quantity":0}):
            altered=deepcopy(plan)
            q=next(q for q in altered["candidates"] if q["action"]=="soil" and q["target_region"]==0)
            q.update(updates)
            self.assertEqual(cabinet_plan(altered,states,c,True)[0]["action"],"defer")
