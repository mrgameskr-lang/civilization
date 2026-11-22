from copy import deepcopy
import json
import unittest

from civsim.emergency_relief import audit_emergency_relief, execute_emergency_relief
from civsim.public_works import execute_relief
from civsim.regions import Road
from tests.test_logistics4 import node


def setup(private=(160, 160, 145), vault=(0, 0, 0), budgets=12, cap=10, ordinary=0, owners=(0, 0, 0)):
    regions = [node(i, 160, q, owner=owners[i]) for i, q in enumerate(private)]
    depots = {i: {"food": q, "ore": 2, "tools": 3} for i, q in enumerate(vault)}
    roads = [Road(i, i+1, 1, cap, (i,i+1)) for i in (0,1) if owners[i] == owners[i+1]]
    cap_by_road = {(r.a,r.b): cap for r in roads}
    decisions = {}
    if ordinary:
        decisions[owners[2]] = {"action":"relief","target":2,"quantity":ordinary,
                                "budget":{"food":100,"ore":0,"tools":0,"workers":0,"admin_units":1}}
    prior, left = execute_relief(regions, roads, depots, decisions, cap_by_road,
                                 dict.fromkeys(owners, budgets), width=3)
    return regions, roads, depots, left, prior, dict.fromkeys(range(3), 0)


class EmergencyReliefTests(unittest.TestCase):
    def test_ordinary_relief_promised_food_and_administration_are_used_only_once(self):
        args = setup(vault=(10, 0, 5), budgets=7, ordinary=2)
        args[-1][2] = 9
        before = deepcopy(args)
        tr, free = execute_emergency_relief(*args, width=3)
        app = next(x for x in tr["applications"] if x["region"] == 2)
        self.assertEqual((app["requested"], app["ordinary_received"], app["handling_remaining"],
                          app["admin_available"], app["approved"], app["received"]), (4, 2, 8, 5, 4, 4))
        self.assertEqual([(x["path"],x["quantity"],x["cost_food"]) for x in tr["shipments"]],
                         [([2],3,0),([0,1,2],1,2)])
        self.assertEqual((args[0][2].stock["food"],args[2][0]["food"], free), (151,7,{(0,1):9,(1,2):9}))
        self.assertEqual(tr["admin"],[{"owner":0,"limit":7,"ordinary_used":2,"remaining_open":5,
                                       "used":4,"remaining":1}])
        audit_emergency_relief(*before, json.loads(json.dumps(tr)), width=3)
        self.assertEqual(args[-3:], before[-3:])

    def test_receiving_handling_and_national_admin_limits_and_ties(self):
        args = setup(private=(160,140,140), vault=(0,20,20), budgets=12)
        tr, _ = execute_emergency_relief(*args, width=3)
        app = {r["region"]:r for r in tr["applications"]}
        self.assertEqual([r["region"] for r in tr["applications"]], [1,2,0])
        self.assertEqual((app[1]["received"],app[2]["received"]), (10,2))
        self.assertEqual((app[2]["unfilled"]["handling"],app[2]["unfilled"]["admin"]), (10,8))
        self.assertEqual(tr["cost_food"],0)
        args = setup(private=(160,160,145), vault=(0,0,50), ordinary=10)
        tr,_ = execute_emergency_relief(*args,width=3)
        self.assertEqual(tr["delivered"],0)
        self.assertEqual(tr["applications"][0]["unfilled"]["handling"],5)

    def test_distinguishes_short_stock_closed_road_unaffordable_freight_and_foreign_stock(self):
        cases = [
            ("stock",{},0), ("road",{"vault":(20,0,0),"cap":0},0),
            ("freight",{"vault":(2,0,0)},0),
            ("stock",{"vault":(20,0,0),"owners":(1,0,0)},0),
            ("road",{"vault":(20,0,0),"cap":1},1),
        ]
        for why, options, qty in cases:
            with self.subTest(why=why, options=options):
                args = setup(**options)
                tr, free = execute_emergency_relief(*args, width=3)
                app = next(r for r in tr["applications"] if r["region"]==2)
                self.assertEqual((tr["delivered"], app["unfilled"][why]),(qty,10-qty))
                self.assertEqual(app["requested"], app["received"]+sum(app["unfilled"].values()))
                if qty:
                    self.assertEqual(free,{(0,1):0,(1,2):0})

    def test_receipt_tamper_rejected_and_bad_opening_is_atomic(self):
        args = setup(vault=(20,0,0))
        opening = deepcopy(args)
        trace, _ = execute_emergency_relief(*args,width=3)
        for field in ("legs","cost_food","tile_path","quantity","owner"):
            bad=deepcopy(trace)
            bad["shipments"][0][field] = []
            with self.subTest(field=field), self.assertRaises(ValueError):
                audit_emergency_relief(*opening,bad,width=3)
        for section, field in (("applications","approved"),("applications","household_rations"),
                               ("admin","ordinary_used"),("roads","capacity"),("nodes","private_food_open")):
            bad=deepcopy(trace)
            bad[section][0][field]+=1
            with self.subTest(section=section, field=field), self.assertRaises(ValueError):
                audit_emergency_relief(*opening,bad,width=3)
        for field in ("roads","private","admin","paid"):
            copy=deepcopy(opening)
            if field=="roads": copy[3][0,1]=1
            if field=="private": copy[0][0].stock["food"]+=1
            if field=="admin": copy[4]["admin"][0]["used"]+=1
            if field=="paid": copy[-1][0]=True
            frozen=deepcopy(copy)
            with self.subTest(field=field), self.assertRaises(ValueError):
                execute_emergency_relief(*copy,width=3)
            self.assertEqual(copy,frozen)

    def test_uses_actual_postpayment_depot_and_never_deducts_committed_household_rations(self):
        args=setup(private=(160,160,150),vault=(0,0,18))
        args[2][2]["food"]=3
        args[-1][2]=5
        tr,_=execute_emergency_relief(*args,width=3)
        self.assertEqual((tr["applications"][0]["requested"],tr["delivered"],args[0][2].stock["food"]),(5,3,153))
        full=setup(private=(160,160,150),vault=(0,0,18))
        full[-1][2]=10
        t,_=execute_emergency_relief(*full,width=3)
        self.assertEqual(t["delivered"],0)
        self.assertEqual(full[2][2]["food"],18)

    def test_shared_initial_economic_state_preserves_harvest_and_reaches_household_stocks(self):
        from civsim.annual_game import create
        from civsim.unit_economy import step_game
        from experiments.food_reserve_study import ORDER, SELECTION

        sim = create(0)
        step_game(sim)
        baseline = step_game(deepcopy(sim), ORDER, upkeep=SELECTION, public_farm=True)
        trial = step_game(deepcopy(sim), ORDER, upkeep=SELECTION, public_farm=True, reserve_policy="emergency")
        self.assertEqual(baseline["public_harvest"], trial["public_harvest"])
        self.assertEqual(baseline["government"]["relief"], trial["government"]["relief"])
        self.assertNotIn("emergency_relief", baseline)
        extra = trial["emergency_relief"]
        self.assertGreater(extra["delivered"], 0)
        domestic = {r["id"]:r for r in trial["domestic"]["nodes"]}
        for r in extra["nodes"]:
            self.assertEqual(r["private_food_close"], domestic[r["id"]]["opening"]["food"])
        self.assertEqual(extra["delivered"], sum(app["received"] for app in extra["applications"]))
