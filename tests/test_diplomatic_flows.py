from copy import deepcopy
import json
from types import SimpleNamespace
import unittest

from civsim.border import border_market, move_people
from civsim.diplomatic_flows import ForeignFlows, _audit_aid, _network
from civsim.regions import Road


def places():
    return [SimpleNamespace(id=i,owner=i,seat=i,members=(i,),population=100,land=4,
                            stock=dict(food=140 if i==1 else 60,ore=5,tools=2),cash=2000) for i in range(3)]


EDGES = [Road(0,1,1,50,(0,1)), Road(1,2,1,50,(1,2))]


def context(arm, preferred=(), change=None):
    pairs=[]
    for a,b in ((0,1),(0,2),(1,2)):
        directions=[]
        for i,j in ((a,b),(b,a)):
            row=dict(source=i,target=j,trade_limit_permille=1000,migration_limit_permille=1000,
                     migration_accept_permille=1000,aid_accepted=False,aid_quantity=0)
            row.update((change or {}).get((i,j),{}))
            directions.append(row)
        pairs.append(dict(policy=dict(agreement_active=(a,b) in preferred,directions=directions)))
    return dict(arm=arm,pairs=pairs)


class ForeignFlowsTests(unittest.TestCase):
    def test_same_physical_offers_reordered_only_for_active_agreement(self):
        for arm,preferred,target in (("B",(),0),("C",(),0),("C",((1,2),),2)):
            regions=places()
            access=ForeignFlows(context(arm,preferred),regions,EDGES,3)
            market=border_market(regions,EDGES,access=access)
            self.assertEqual(market["trades"][0]["buyer"],target)
            self.assertEqual(sum(r.cash for r in regions),6000)
            self.assertEqual(sum(r.stock["food"] for r in regions),260-sum(t["cost_food"] for t in market["trades"]))
            self.assertEqual(sum(t["quantity"] for t in market["trades"]),27)

    def test_aid_shares_stock_and_road_with_commercial_cargo(self):
        regions=places()
        borders=[Road(0,1,1,12,(0,1)), EDGES[1]]
        ctx=context("D",change={(1,0):dict(aid_accepted=True,aid_quantity=10)})
        vault={r.id:dict(food=10 if r.id==1 else 0,ore=0,tools=0) for r in regions}
        access=ForeignFlows(ctx,regions,borders,3)
        access.send_aid(vault)
        self.assertEqual((vault[0]["food"],vault[1]["food"]),(8,0))
        trade=border_market(regions,borders,access=access)
        physical=access.trace()
        aid,=physical["aid"]["shipments"]
        self.assertEqual((aid["quantity"],aid["received"],aid["cost_food"],aid["handling_food"],aid["path"]),
                         (9,8,1,1,[1,0]))
        self.assertEqual(sum(t["quantity"] for t in trade["trades"] if t["buyer"]==0),3)
        self.assertEqual((physical["roads"][0]["aid_cargo"],physical["roads"][0]["unused"]),(9,0))

    def test_receipt_cannot_be_reexported_or_teleported_from_inland_depot(self):
        regions=places()
        ctx=context("D",change={(0,1):dict(aid_accepted=True,aid_quantity=10),
                                (1,2):dict(aid_accepted=True,aid_quantity=10),
                                (0,2):dict(aid_accepted=True,aid_quantity=10)})
        vault={r.id:dict(food=20 if r.id==0 else 0,ore=0,tools=0) for r in regions}
        flows=ForeignFlows(ctx,regions,EDGES,3)
        flows.send_aid(vault)
        self.assertEqual([s["target"] for s in flows.trace()["aid"]["shipments"]],[1])
        self.assertEqual(vault[2]["food"],0)

    def test_one_way_export_and_entry_limits_leave_other_opportunities_open(self):
        regions=places()
        ctx=context("D",change={(1,0):dict(trade_limit_permille=0),
                                (0,1):dict(migration_accept_permille=0)})
        flows=ForeignFlows(ctx,regions,EDGES,3)
        market=border_market(regions,EDGES,access=flows)
        self.assertEqual({t["buyer"] for t in market["trades"]},{2})
        self.assertGreater(flows.trace()["trade_attempts"][0]["denied"],0)
        regions[1].stock["food"]=50
        meals={r.id:dict(food_need=100,food_eaten=100 if r.id==1 else 0) for r in regions}
        vital,moves=move_people(regions,meals,EDGES,access=flows)
        self.assertEqual({(m["source"],m["target"]) for m in moves},{(2,1)})
        attempts=flows.trace()["migration_attempts"]
        self.assertTrue(any(t["source"]==0 and t["denied_entry"]>0 for t in attempts))
        self.assertEqual(sum(r.population for r in regions),sum(d["population_before_migration"] for d in vital.values()))

    def test_export_cap_applies_to_all_goods_on_one_direction(self):
        regions=places()
        a,b=regions[:2]
        b.stock.update(food=116,ore=500,tools=100)
        a.stock.update(ore=0,tools=0)
        flows=ForeignFlows(context("D",change={(1,0):dict(trade_limit_permille=100)}),regions,EDGES,3)
        trade=border_market(regions,EDGES,access=flows)
        sales=[t for t in trade["trades"] if (t["seller"],t["buyer"])==(1,0)]
        self.assertEqual([(s["good"],s["quantity"]) for s in sales],[("food",3),("ore",2)])
        self.assertTrue(any(t["good"]=="tools" and t["denied"]>0 for t in flows.trade_attempts))

    def test_entry_and_exit_quotas_are_separate_and_cannot_be_reused_on_second_exit(self):
        regions=places()
        regions[2].owner=0
        flows=ForeignFlows(context("D",change={(1,0):dict(migration_limit_permille=500,
                                                          migration_accept_permille=500)}), regions,EDGES,3)
        donor={"requested_departures":10}
        self.assertEqual(flows.migrate(1,0,10,donor,{"host_capacity":2}),1)
        self.assertEqual(flows.migrate(1,2,9,donor,{"host_capacity":20}),4)
        self.assertEqual([(m["denied_exit"],m["denied_entry"]) for m in flows.migration_attempts],[(5,4),(5,0)])
        self.assertEqual(flows.migrate(0,2,9,donor,{"host_capacity":20}),9)

    def test_independent_accounting_rejects_cargo_loss_fee_path_and_funding_mutations(self):
        regions=places()
        nodes={r.id:r for r in regions}
        ctx=context("D",change={(1,0):dict(aid_accepted=True,aid_quantity=10)})
        vault={r.id:dict(food=20 if r.id==1 else 0,ore=0,tools=0) for r in regions}
        before=deepcopy(vault)
        access=ForeignFlows(ctx,regions,EDGES,3)
        access.send_aid(vault)
        ctx["physical"]=access.trace()
        record={"diplomacy":ctx,"government":{"levies":[{"region":i,"depot_open":v} for i,v in vault.items()]}}
        _audit_aid(record,nodes,EDGES,before)
        for key,value in (("received",10),("cost_food",0),("handling_food",0),("quantity",20),("path",[0,1])):
            forged=deepcopy(record)
            forged["diplomacy"]["physical"]["aid"]["shipments"][0][key]=value
            with self.subTest(key=key), self.assertRaises(ValueError):
                _audit_aid(forged,nodes,EDGES,before)
        bad=deepcopy(ctx["physical"])
        bad["roads"][0]["path"]=[0,3,1]
        with self.assertRaises(ValueError):
            _network(bad,nodes)
        before[1]["food"]=0
        with self.assertRaises(ValueError):
            _audit_aid(record,nodes,EDGES,before)

    def test_one_unit_food_is_not_dispatched_and_receiver_storage_is_respected(self):
        for initial,recipient,quantity in ((1,0,0),(10,25,0),(20,24,2)):
            regions=places()
            vault={r.id:dict(food=initial if r.id==1 else recipient,ore=0,tools=0) for r in regions}
            flow=ForeignFlows(context("D",change={(1,0):dict(aid_accepted=True,aid_quantity=12)}),regions,EDGES,3)
            flow.send_aid(vault)
            with self.subTest(initial=initial,recipient=recipient):
                self.assertEqual(flow.aid["directions"][0]["dispatched"],quantity)
                self.assertLessEqual(vault[0]["food"],25)

    def test_natural_aid_audit_survives_json_and_rejects_forged_physical_accounts(self):
        from civsim.diplomacy import start_diplomacy, step_diplomacy
        from civsim.diplomatic_flows import audit_foreign_flows
        from civsim.government_audit import audit_fiscal_year
        from civsim.model import generate_world
        from civsim.regions import regionalize
        world=regionalize(generate_world(0))
        sim=start_diplomacy(world)
        previous=None
        for year in range(1,21):
            row=step_diplomacy(sim,year,"D")
            if row["diplomacy"]["physical"]["aid"]["shipments"]:
                break
            previous=row
        decoded=json.loads(json.dumps(row))
        self.assertTrue(decoded["diplomacy"]["physical"]["aid"]["shipments"])
        audit_fiscal_year(decoded,previous_record=previous,geography=world)
        for corruption in ("direction","private_public","cash","population","route"):
            bad=deepcopy(decoded)
            if corruption=="direction":
                bad["diplomacy"]["physical"]["trade_attempts"][0]["denied"]+=1
            elif corruption=="private_public":
                bad["government"]["levies"][0]["depot_open"]["food"]+=1
            elif corruption=="cash":
                bad["regions"][0]["closing"]["cash"]+=1
            elif corruption=="population":
                bad["regions"][0]["closing"]["population"]+=1
            else:
                bad["diplomacy"]["physical"]["roads"][0]["path"].reverse()
            with self.subTest(corruption=corruption), self.assertRaises(ValueError):
                audit_foreign_flows(bad,previous,geography=world)
