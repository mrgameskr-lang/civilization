from copy import deepcopy
from types import SimpleNamespace
import unittest

from civsim.audit import BalanceError
from civsim.diplomatic_rules import _choices, _close_pair, _empty_flow, _empty_pair, _movements, initial_pairs
from civsim.fiscal_policy import ACTIONS
from civsim.political_rules import GROUPS


def country(i, *, pop=960, unmet=0, depot=0):
    return {"id":i,"population":pop,"prior_unmet":unmet,"prior_need":pop,"prior_pop_delta":0,
            "shortage_permille":1000*unmet//pop,"foreign_export_value":0,"foreign_import_value":0,
            "groups":{k:{"signals":dict.fromkeys(ACTIONS,0),"discontent":0} for k in GROUPS},
            "party":"caretaker","depot":{"food":depot}}


def link(a,b,capacity=100,distance=10):
    return {"owner_a":a,"owner_b":b,"capacity":capacity,"distance":distance}


def contact(m, volume=40, value=1200, good="tools"):
    for f in m["last"]:
        f["goods"][good] = volume
        f.update(trade_value=value,trades=1,trade_freight=4)


def rows(countries, roads, *, arm="D", memories=None, year=1, fork=None):
    if memories is None:
        world = SimpleNamespace(nations=[SimpleNamespace(id=n["id"]) for n in countries])
        memories = initial_pairs(world)
    return _choices(year,arm,memories,countries,roads,fork)


def settle(row, year, denied=0, feasible=0):
    a,b = row["a"],row["b"]
    flows = {(a,b):_empty_flow(a,b),(b,a):_empty_flow(b,a)}
    flows[a,b].update(trade_opportunity=feasible,trade_denied=denied)
    return _close_pair(row,flows,year)


class DiplomaticRulesTests(unittest.TestCase):
    def test_all_pairs_initially_neutral_nonadjacent_do_not_act(self):
        countries = [country(i,unmet=90 if i else 0,depot=100 if not i else 0) for i in range(8)]
        pairs = rows(countries,[])
        self.assertEqual(len(pairs),28)
        for pair in pairs:
            self.assertEqual((pair["opening"]["trust"],pair["opening"]["relation"]),(500,0))
            self.assertFalse(pair["policy"]["agreement_active"])
            for d in pair["policy"]["directions"]:
                self.assertEqual((d["border_capacity"],d["aid_quantity"],d["trade_limit_permille"]),(0,0,1000))

    def test_pact_requires_independent_positive_consent_and_real_contact(self):
        m = _empty_pair(0,1)
        m["last"][0]["goods"]["food"] = 16
        m["last"][0].update(trade_value=320,trades=1)
        cs = [country(0,unmet=60),country(1)]
        row = rows(cs,[link(0,1)],memories={(0,1):m})[0]
        self.assertEqual(row["policy"]["proposers"],[1])
        self.assertFalse(row["policy"]["agreement_started"])
        posted,closing,events = settle(row,1)
        self.assertEqual(posted["directions"][0]["pact_rejections"],1)
        self.assertEqual(closing["totals"][1]["pact_proposals"],1)
        self.assertIn(("pact_rejected",0,1),[(e["kind"],e["source"],e["target"]) for e in events])
        cs[0]=country(0)
        accepted = rows(cs,[link(0,1)],memories={(0,1):m})[0]["policy"]
        self.assertEqual((accepted["agreement_started"],accepted["expires_after"]),(True,5))
        self.assertFalse(rows(cs,[],memories={(0,1):m})[0]["policy"]["agreement_active"])
        self.assertFalse(rows(cs,[link(0,1)],arm="B",memories={(0,1):m})[0]["policy"]["agreement_active"])

    def test_five_year_term_and_expiry_no_breach_without_opportunity(self):
        cs = [country(0),country(1)]
        m = _empty_pair(0,1)
        contact(m)
        for y in range(1,7):
            pair = rows(cs,[link(0,1)],arm="C",memories={(0,1):m},year=y)[0]
            self.assertEqual(pair["policy"]["agreement_active"],y<=5)
            self.assertEqual(pair["policy"]["agreement_expired"],y==6)
            _,m,events = settle(pair,y)
            self.assertEqual((m["breached_total"],m["signed_total"]),(0,1))
            self.assertNotIn("pact_breached",[e["kind"] for e in events])

    def test_actual_industry_signal_incumbent_and_route_change_a_signature(self):
        m = _empty_pair(0,1)
        m["last"][1].update(trade_value=40,trades=1)
        m["last"][1]["goods"]["tools"]=5
        cs = [country(0),country(1)]
        cs[0]["groups"]["industry"]["signals"]["road"] = 1000
        def stance(roads):
            return rows(cs,roads,memories={(0,1):m})[0]["policy"]["directions"][0]
        cs[0]["party"]="builders"
        self.assertEqual(stance([link(0,1,5,3)])["pact_score"],22)
        self.assertFalse(stance([link(0,1,1,3)])["pact_willing"])
        cs[0]["party"]="mutualists"
        self.assertEqual(stance([link(0,1,5,3)])["pact_score"],2)
        cs[0]["groups"]["industry"]["signals"]["road"] = 0
        self.assertFalse(stance([link(0,1,5,3)])["pact_willing"])

    def test_two_consecutive_real_denials_terminate_one_does_not(self):
        cs = [country(0,unmet=80),country(1)]
        m = _empty_pair(0,1)
        m.update(agreement_start=1,agreement_end=5,signed_total=1,year=1)
        for year in (2,3,4):
            m["last"][0]["goods"]["food"] = 20
            m["last"][0].update(trades=1,trade_value=80)
            pair = rows(cs,[link(0,1)],memories={(0,1):m},year=year)[0]
            self.assertEqual(pair["policy"]["directions"][0]["trade_limit_permille"],500)
            denied = 0 if year==2 else 3
            _,m,events = settle(pair,year,denied=denied,feasible=denied)
            self.assertEqual(m["breached_total"],year-2)
            self.assertEqual("pact_terminated" in [e["kind"] for e in events],year==4)
        self.assertEqual((m["agreement_end"],m["cooldown_until"]),(0,6))
        contact(m)
        self.assertFalse(rows(cs,[link(0,1)],memories={(0,1):m},year=5)[0]["policy"]["proposers"])

    def test_distance_capacity_and_double_earmark_limits(self):
        cs = [country(0,depot=100),country(1,unmet=90),country(2,unmet=80)]
        roads = [link(0,1,3,11),link(0,1,5,5),link(0,2,100,10)]
        ds = [r["policy"]["directions"][0] for r in rows(cs,roads) if r["a"]==0]
        first = ds[0]
        self.assertEqual((first["border_capacity"],first["border_distance"],first["aid_ceiling"]),(8,5,8))
        offers = [d for d in ds if d["aid_offer"]]
        self.assertEqual(len(offers),1)
        self.assertTrue(offers[0]["aid_accepted"])
        self.assertLessEqual(offers[0]["aid_quantity"]+offers[0]["aid_freight_estimate"],offers[0]["aid_budget"])
        near = rows(cs[:2],[link(0,1,200,2)])[0]["policy"]["directions"][0]
        far = rows(cs[:2],[link(0,1,200,100)])[0]["policy"]["directions"][0]
        self.assertGreater(near["aid_offer"],far["aid_offer"])
        self.assertGreater(near["aid_score"],far["aid_score"])

    def test_requests_proactive_offers_rejections_and_nonperformance_are_separate(self):
        cs = [country(0,depot=100),country(1,unmet=96),country(2,depot=100)]
        roads = [link(0,1),link(1,2)]
        pairs = rows(cs,roads)
        primary = pairs[0]["policy"]["directions"][0]
        second = pairs[2]["policy"]["directions"][1]
        self.assertTrue(primary["aid_request"] and primary["aid_accepted"])
        self.assertEqual(second["aid_request"],0)
        self.assertTrue(second["aid_offer"] and second["aid_accepted"])
        self.assertEqual(primary["aid_quantity"]+second["aid_quantity"],30)
        _,_,events = settle(pairs[0],1)
        self.assertIn("aid_shortfall",[e["kind"] for e in events])
        self.assertNotIn("aid_delivered",[e["kind"] for e in events])
        m = _empty_pair(0,1)
        m["trust"] = 320
        pair = rows(cs[:2],roads[:1],memories={(0,1):m})[0]
        _,_,events = settle(pair,1)
        self.assertIn("aid_offer_rejected",[e["kind"] for e in events])
        self.assertNotIn("aid_request_rejected",[e["kind"] for e in events])
        cs[0] = country(0)
        pair = rows(cs[:2],roads[:1])[0]
        _,_,events = settle(pair,1)
        self.assertIn("aid_request_rejected",[e["kind"] for e in events])

    def test_sender_and_receiver_decide_separately_and_opening_a_direction_is_local(self):
        cs = [country(0),country(1,unmet=96)]
        m = _empty_pair(0,1)
        m["last"][0]["migrants"] = 6
        cs[0]["prior_pop_delta"] = -10
        cs[0]["groups"]["farm"]["discontent"] = 110
        cs[1]["groups"]["consumer"]["discontent"] = 50
        roads = [link(0,1)]
        def plan(fork=None):
            return rows(cs,roads,memories={(0,1):m},fork=fork)[0]["policy"]["directions"]
        actual = plan()
        self.assertEqual((actual[0]["migration_limit_permille"],actual[0]["migration_accept_permille"]),(750,500))
        other = plan({"kind":"open_migration","source":0,"target":1})
        expected = deepcopy(actual)
        expected[0].update(migration_limit_permille=1000,migration_accept_permille=1000)
        self.assertEqual(other,expected)
        with self.assertRaises(BalanceError):
            plan({"kind":"open_trade","source":1,"target":0})

    def test_signed_fork_keeps_unrelated_decisions_and_original_memory_unchanged(self):
        cs = [country(0),country(1)]
        m = _empty_pair(0,1)
        contact(m)
        before = deepcopy(m)
        options = dict(memories={(0,1):m})
        natural = rows(cs,[link(0,1)],**options)[0]
        alt = rows(cs,[link(0,1)],fork={"kind":"no_new_pact","a":0,"b":1},**options)[0]
        self.assertTrue(natural["policy"]["agreement_started"])
        self.assertFalse(alt["policy"]["agreement_active"])
        self.assertEqual(alt["policy"]["directions"],natural["policy"]["directions"])
        self.assertEqual(m,before)

    def test_current_and_lifetime_dependency_use_national_denominators(self):
        cs = [country(i) for i in range(3)]
        pairs = rows(cs,[link(0,1),link(1,2)],arm="B")
        record = {"diplomacy":{"pairs":pairs,"physical":{"trade_attempts":[],"migration_attempts":[],"aid":{"shipments":[]}}},
                  "regions":[{"id":i,"owner":i,"consumption":{"food_need":100}} for i in range(3)],"moves":[],
                  "border_market":{"trades":[{"seller":0,"buyer":1,"good":"food","quantity":6,"value":24,"cost_food":1},
                                            {"seller":2,"buyer":1,"good":"tools","quantity":4,"value":36,"cost_food":1}]}}
        flows = _movements(record)
        self.assertEqual((flows[1,0]["import_dependence"],flows[1,0]["food_import_share"]),(400,60))
        self.assertEqual((flows[0,1]["export_exposure"],flows[2,1]["export_exposure"]),(1000,1000))
        _,m,_ = _close_pair(pairs[0],flows,1)
        row = deepcopy(pairs[0])
        row["opening"]=m
        record["border_market"]["trades"] = []
        _,m,_ = _close_pair(row,_movements(record),2)
        self.assertEqual((m["totals"][1]["import_dependence"],m["totals"][1]["food_import_share"]),(400,30))
        self.assertEqual(m["last"][1]["import_dependence"],0)
