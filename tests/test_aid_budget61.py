from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from civsim.aid_budget61 import BudgetFlows, audit_budget_payments, audit_fiscal61
from civsim.border import border_market, validate_border_paths
from civsim.regions import Road


ARCHIVE=Path(__file__).resolve().parents[1]/"examples"/"phase6a"/"seed0-diplomacy"


def context(quantities, budget, *, capped=True, suppress=None):
    pairs=[]
    for a,b in ((0,1),(0,2),(1,2)):
        directions=[]
        for i,j in ((a,b),(b,a)):
            qty=quantities.get((i,j),0)
            directions.append(dict(source=i,target=j,aid_budget=budget.get(i,0),aid_quantity=qty,
                                   aid_accepted=qty>=2,trade_limit_permille=1000,
                                   migration_limit_permille=1000,migration_accept_permille=1000))
        pairs.append({"policy":{"directions":directions,"agreement_active":False}})
    return {"arm":"D","pairs":pairs,"phase61":{"arm":"F" if capped else "B","aid":True,
            "capped":capped,"export":capped,"migration":capped,"suppress_aid":suppress}}


def setup_case(ctx, funds=(100,0,0), space=100, edges=None):
    width=64
    seats={0:0,1:1,2:128}
    if edges is None:
        edges=[Road(0,1,1,20,(0,1)), Road(0,2,2,20,(0,64,128)), Road(1,2,3,20,(1,65,129,128))]
    members={i:set() for i in seats}
    for road in edges:
        seats[road.a],seats[road.b]=road.path[0],road.path[-1]
        cut=len(road.path)//2
        members[road.a].update(road.path[:cut])
        members[road.b].update(road.path[cut:])
    nodes=[SimpleNamespace(id=i,owner=i,population=space*4,seat=s,members=members[i]|{s}) for i,s in seats.items()]
    validate_border_paths(nodes,edges,width)
    vault={i:dict(food=food,ore=0,tools=0) for i,food in enumerate(funds)}
    book=BudgetFlows(ctx,nodes,edges,width)
    book.send_aid(vault)
    return book,vault


class AidBudgetTests(unittest.TestCase):
    def test_old_control_and_new_fiscal_and_physical_accounts_audit_after_json_roundtrip(self):
        from civsim.diplomacy61 import start61,step61
        from civsim.model import generate_world
        from civsim.regions import regionalize
        with (ARCHIVE/"years.jsonl").open(encoding="utf8") as source:
            historical=json.loads(next(source))
        audit_fiscal61(historical)
        world=regionalize(generate_world(0))
        sim=start61(world)
        previous=None
        for year in range(1,5):
            record=step61(sim,year,"F")
            saved=json.loads(json.dumps(record))
            audit_fiscal61(saved,geography=world,previous_record=previous)
            if year==4:
                bad_previous=deepcopy(previous)
                bad_previous["government"]["depots"][0]["closing"]["food"]+=1
                with self.assertRaises(ValueError):
                    audit_fiscal61(saved,geography=world,previous_record=bad_previous)
            previous=saved
        for key in ("national", "warehouse", "cash", "allocation", "sender", "geometry"):
            damaged=deepcopy(saved)
            aid=damaged["diplomacy"]["physical"]["aid"]
            if key=="national":
                damaged["countries"][0]["closing"]["stock"]["food"]+=1
            elif key=="warehouse":
                damaged["government"]["depots"][0]["closing"]["food"]+=1
            elif key=="cash":
                damaged["regions"][0]["closing"]["cash"]+=1
            elif key=="allocation":
                aid["attempts"][-1]["storage_space"]+=100
            elif key=="sender":
                aid["donors"][2]["actual_debit"]+=1
            else:
                aid["shipments"][0]["path"].reverse()
            with self.subTest(key=key),self.assertRaises(ValueError):
                audit_fiscal61(damaged,geography=world)

    def test_archived_first_discrepancy_and_same_opening_capped_tickets(self):
        with (ARCHIVE/"years.jsonl").open(encoding="utf8") as source:
            record=next(r for line in source if (r:=json.loads(line))["year"]==4)
        ctx=record["diplomacy"]
        nodes=[SimpleNamespace(**r["opening"]) for r in record["regions"]]
        borders=[Road(r["a"],r["b"],r["distance"],r["capacity"],tuple(r["path"])) for r in ctx["physical"]["roads"]]
        vault={r["id"]:r["depot_close"] for r in record["government"]["works"]["nodes"]}
        for capped,expected in ((False,(187,180,19,206)),(True,(174,167,17,191))):
            flags=context({}, {},capped=capped)["phase61"]
            trial=BudgetFlows({**ctx,"phase61":flags},nodes,borders,ctx["physical"]["width"])
            trial.send_aid(deepcopy(vault))
            aid=trial.trace()["aid"]
            tickets=[t for t in aid["shipments"] if t["donor"]==2]
            q,net,fee=(sum(t[k] for t in tickets) for k in ("quantity","received","cost_food"))
            self.assertEqual((q,net,fee,q+fee),expected)
            self.assertEqual([(s["source"],s["target"],s["quantity"],s["cost_food"]) for s in tickets],
                             [(9,15,50,1),(10,14,50,6),(8,12,74 if capped else 87,10 if capped else 12)])
            self.assertEqual(next(d for d in aid["donors"] if d["donor"]==2)["planned_budget"],191)
            if not capped:
                self.assertEqual(tickets,[s for s in ctx["physical"]["aid"]["shipments"] if s["donor"]==2])

    def test_national_budget_is_shared_across_recipients_and_fees_are_rounded_per_ticket(self):
        ctx=context({(0,1):5,(0,2):10},{0:10})
        book,vault=setup_case(ctx)
        self.assertEqual([(t["target"],t["quantity"],t["cost_food"]) for t in book.aid["shipments"]],[(1,5,1),(2,3,1)])
        self.assertEqual((vault[0]["food"],vault[1]["food"],vault[2]["food"]),(90,4,2))
        self.assertEqual(book.aid["attempts"][1]["budget_displaced"],7)
        self.assertEqual(book.aid["donors"][0]["remaining_budget"],0)
        self.assertEqual(book.aid["directions"][1]["shortfall_reasons"],["budget"])
        audit_budget_payments(ctx,book.aid)
        for what in ("budget","fee","remaining","reason"):
            forged=deepcopy(book.aid)
            if what=="budget":
                forged["donors"][0]["planned_budget"]+=1
            elif what=="fee":
                forged["shipments"][0]["cost_food"]-=1
            elif what=="remaining":
                forged["attempts"][1]["before_budget"]+=1
            else:
                forged["directions"][1]["shortfall_reasons"]=[]
            with self.subTest(what=what),self.assertRaises(ValueError):
                audit_budget_payments(ctx,forged)

    def test_binding_ties_lot_suppression_long_route_and_no_reexport(self):
        ctx=context({(0,1):10,(1,2):10},{0:3,1:20})
        roads=[Road(0,1,50,2,tuple(range(51))),Road(1,2,1,10,(50,51))]
        book,_=setup_case(ctx,(3,0,0),space=1,edges=roads)
        attempt=book.aid["attempts"][0]
        self.assertEqual(set(attempt["binding"]),{"road","stock","storage","budget"})
        self.assertEqual((attempt["quantity"],attempt["budget_displaced"]),(2,0))
        self.assertEqual(len(book.aid["shipments"]),1)
        self.assertIn("stock", book.aid["directions"][1]["shortfall_reasons"])
        blocked,_=setup_case(context({(0,1):10},{0:2}),edges=roads)
        self.assertFalse(blocked.aid["shipments"])
        self.assertIn("minimum_lot", blocked.aid["directions"][0]["shortfall_reasons"])
        skip,_=setup_case(context({(0,1):10,(0,2):10},{0:10},suppress=[0,1]))
        self.assertEqual(skip.aid["directions"][0]["shortfall_reasons"],["suppressed"])
        self.assertTrue(all(t["target"]==2 for t in skip.aid["shipments"]))

    def test_private_sale_pays_cash_and_only_uses_residual_of_both_public_directions(self):
        road=Road(0,1,1,12,(0,1))
        book,_=setup_case(context({(0,1):6,(1,0):3},{0:8,1:4}),funds=(15,10,0),edges=[road])
        nodes=list(book.nodes.values())
        for r in nodes:
            r.stock={"food":900 if r.id==0 else 0,"ore":20,"tools":10}
            r.cash=1000
        market=border_market(nodes,[road],access=book)
        physical=book.trace()["roads"][0]
        self.assertEqual((physical["aid_cargo"],physical["private_cargo"],physical["unused"]),(9,3,0))
        t,=market["trades"]
        self.assertEqual(t["quantity"],3)
        self.assertEqual((nodes[0].cash,nodes[1].cash),(1000+t["value"],1000-t["value"]))
