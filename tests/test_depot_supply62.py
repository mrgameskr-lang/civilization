import json
import unittest
from copy import deepcopy
from types import SimpleNamespace

from civsim.aid_budget61 import BudgetFlows
from civsim.depot_supply62 import audit_depot_supply, execute_depot_supply
from civsim.logistics import ship
from civsim.public_works import residual_roads
from civsim.regions import Road


def stock(food=0, ore=0, tools=0):
    return dict(food=food, ore=ore, tools=tools)


class DepotSupplyTests(unittest.TestCase):
    def setUp(self):
        self.regions = [SimpleNamespace(id=i, owner=int(i==3), seat=i, members=(i,),
                        population=400, stock=stock(20, 1, 3)) for i in range(4)]
        self.roads = [Road(0, 1, 1, 50, (0, 1)), Road(1, 2, 1, 50, (1, 2))]
        self.borders = [Road(2, 3, 1, 50, (2, 3))]
        self.remaining = {(r.a, r.b):r.capacity for r in self.roads}
        self.open = {0:stock(80, 9, 7), 1:stock(), 2:stock(), 3:stock()}
        d = dict(source=0,target=1,aid_budget=25,aid_quantity=14,aid_accepted=True)
        old = dict(source=0,target=1,aid_quantity=0,aid_sent=0,aid_request=0)
        self.ctx = {'pairs':[{'policy':{'directions':[d]}, 'opening':{'last':[old]}}]}
        self.prev = {}

    def run_supply(self, emergency=True, forward=False):
        warehouses=deepcopy(self.open)
        trace, residual=execute_depot_supply(self.regions,self.roads,self.borders,warehouses,
            self.remaining,self.ctx,self.prev,width=4,emergency=emergency,forward=forward)
        self.check(json.loads(json.dumps(trace)),emergency,forward)
        self.assertEqual(warehouses,{n['id']:n['closing'] for n in trace['nodes']})
        return trace,residual,warehouses

    def check(self,trace,emergency,forward):
        audit_depot_supply(self.regions,self.roads,self.borders,self.open,self.remaining,
            self.ctx,self.prev,trace,width=4,emergency=emergency,forward=forward)

    def test_approved_aid_moves_gross_food_to_border_with_rounded_fees_on_each_leg(self):
        before=deepcopy(self.regions)
        t,left,stores=self.run_supply()
        self.assertEqual(len(t['shipments']),1)
        trip=t['shipments'][0]
        self.assertEqual((trip['quantity'],trip['purpose'],trip['recipient']),(15,'emergency_aid',1))
        self.assertEqual((trip['tile_path'],trip['cost_food']),([0,1,2],2))
        self.assertEqual((stores[0]['food'],stores[1]['food'],stores[2]['food'],stores[3]['food']),(63,0,15,0))
        self.assertEqual(left,{(0,1):35,(1,2):35})
        self.assertEqual(t['countries'][0]['aid_freight_food'],2)
        self.assertEqual(self.regions,before)

    def test_actual_budget_keeps_room_for_external_gross_and_fees(self):
        self.ctx['pairs'][0]['policy']['directions'][0]['aid_budget']=12
        t,_,stores=self.run_supply()
        self.assertEqual(stores[2]['food'],10)
        self.assertEqual(t['countries'][0]['aid_freight_food'],2)

    def test_no_staging_for_already_funded_full_receiving_warehouse_or_closed_roads(self):
        self.open[2]['food']=16
        self.assertFalse(self.run_supply()[0]['shipments'])
        self.open[2]['food']=0
        self.open[3]['food']=100
        self.assertFalse(self.run_supply()[0]['shipments'])
        self.open[3]['food']=0
        self.remaining[0,1]=0
        self.assertFalse(self.run_supply()[0]['shipments'])

    def test_forward_uses_last_year_and_real_domestic_ore_tools_freight(self):
        self.ctx['pairs'][0]['policy']['directions'][0].update(aid_quantity=0,aid_accepted=False)
        self.assertFalse(self.run_supply(False,True)[0]['shipments'])
        self.ctx['pairs'][0]['opening']['last'][0]['aid_request']=20
        self.prev={1:{'unmet':9,'soil_delta':-3,'food_need':400}}
        t,_,stores=self.run_supply(False,True)
        self.assertTrue(any(s['purpose']=='forward_aid' and s['target']==2 for s in t['shipments']))
        self.assertEqual({s['good'] for s in t['shipments'] if s['purpose']=='domestic_reserve'},set(stock()))
        self.assertGreater(t['countries'][0]['domestic_freight_food'],0)
        self.assertEqual(sum(d['food'] for d in stores.values())+t['cost_food'],80)
        for good in ('ore','tools'):
            self.assertEqual(sum(d[good] for d in stores.values()),self.open[0][good])

    def test_nonfood_requires_funded_provisions_and_receiving_space(self):
        self.open[0]['food']=0
        self.prev={1:{'unmet':9,'soil_delta':-3,'food_need':400}}
        self.assertFalse(self.run_supply(False,True)[0]['shipments'])
        self.open[0]['food']=30
        self.open[1].update(ore=12,tools=12)
        self.assertFalse(any(s['good']!='food' for s in self.run_supply(False,True)[0]['shipments']))

    def test_disabled_and_mutations_rejected(self):
        self.assertFalse(self.run_supply(False,False)[0]['shipments'])
        t,_,_=self.run_supply()
        for key,value in [('tile_path',[0,2]),('cost_food',1),('purpose','forward_aid'),('quantity',45),
                          ('target',3),('recipient',0)]:
            bad=deepcopy(t)
            bad['shipments'][0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError): self.check(bad,True,False)
        bad=deepcopy(t)
        bad['countries'][0]['aid_freight_food']+=1
        with self.assertRaises(ValueError): self.check(bad,True,False)

    def test_shared_road_is_spent_once_public_freight_not_reexported(self):
        self.remaining[0,1]=8
        self.ctx['pairs'][0]['opening']['last'][0]['aid_request']=20
        self.prev={1:{'unmet':9,'soil_delta':-3,'food_need':400}}
        trace,left,_=self.run_supply(True,True)
        self.assertEqual(left[0,1],0)
        self.assertEqual(sum(s['quantity'] for s in trace['shipments'] if 0 in s['path']),8)
        self.assertTrue(all(s['source']==0 for s in trace['shipments']))

    def test_real_foreign_checkout_debits_and_domestic_residual_or_private_rations(self):
        self.ctx.update(arm='D',phase61={'aid':True,'capped':True,'suppress_aid':None})
        policy=self.ctx['pairs'][0]['policy']
        policy['agreement_active']=False
        policy['directions'][0].update(aid_budget=12,trade_limit_permille=1000,
            migration_limit_permille=1000,migration_accept_permille=1000)
        t,left,stores=self.run_supply()
        flows=BudgetFlows(self.ctx,self.regions,self.borders,4)
        prepaid=t['countries'][0]['aid_freight_food']
        flows.budgets[0]-=prepaid
        flows.send_aid(stores)
        foreign=flows.trace()['aid']['shipments'][0]
        self.assertEqual((prepaid,foreign['quantity'],foreign['cost_food'],foreign['handling_food']),(2,9,1,1))
        self.assertEqual((stores[2]['food'],stores[3]['food']),(0,8))
        self.regions[0].stock['food']=700
        plain=ship(deepcopy(self.regions),residual_roads(self.roads,self.remaining),width=4)
        shared=ship(deepcopy(self.regions),residual_roads(self.roads,left),width=4)
        self.assertEqual(plain['delivered']['food']-shared['delivered']['food'],10)

    def test_forward_and_emergency_share_a_single_national_allowance(self):
        self.ctx['pairs'][0]['policy']['directions'][0].update(aid_quantity=3,aid_budget=12)
        self.ctx['pairs'][0]['opening']['last'][0]['aid_request']=20
        trace,_,stores=self.run_supply(True,True)
        a,b=trace['shipments']
        self.assertEqual([s['purpose'] for s in (a,b)],['emergency_aid','forward_aid'])
        self.assertEqual(a['aid_freight_allowance_after'],b['aid_freight_allowance_before'])
        self.assertEqual(trace['countries'][0]['aid_freight_food'],a['cost_food']+b['cost_food'])
        self.assertEqual((stores[2]['food'],trace['countries'][0]['aid_freight_food']),(10,4))

    def test_foreign_or_discontinuous_domestic_path_rejects_without_mutation(self):
        stock_before=deepcopy(self.open)
        for roads in ([Road(0,1,1,50,(0,2))], [*self.roads,*self.borders]):
            with self.subTest(roads=roads),self.assertRaises(ValueError):
                execute_depot_supply(self.regions,roads,self.borders,self.open,self.remaining,
                    self.ctx,self.prev,width=4,emergency=True,forward=True)
        self.assertEqual(self.open,stock_before)

    def test_forecast_checks_other_border_depots_before_repositioning(self):
        # Source 1 and foreign destination 4 are vertically adjacent on the next row.
        self.regions.append(SimpleNamespace(id=4,owner=1,seat=5,members=(5,),population=400,stock=stock()))
        self.borders.append(Road(1,4,1,50,(1,5)))
        self.open[4]=stock()
        self.open[1]=stock(25)
        self.assertFalse(self.run_supply()[0]['shipments'])

    def test_request_and_allowance_tamper(self):
        t,_,_=self.run_supply()
        for field in ('aid_freight_allowance_before','request_id','source_credit_before'):
            bad=deepcopy(t)
            bad['shipments'][0][field]=100
            with self.subTest(field=field),self.assertRaises(ValueError): self.check(bad,True,False)
        bad=deepcopy(t)
        bad['requests'][0]['evidence']['approved']+=2
        with self.assertRaises(ValueError): self.check(bad,True,False)
