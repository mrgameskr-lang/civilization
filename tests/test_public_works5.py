import unittest
from copy import deepcopy

from civsim.public_works import audit_relief, audit_works, execute_relief, execute_works, residual_roads
from civsim.regions import Road
from tests.test_logistics4 import node


def fixture(capacity=12):
    regions = [node(i, 60, 0) for i in range(3)]
    for r in regions:
        r.soil = 750
        r.farmland = 48
    roads = [Road(a, a+1, 1, capacity, (a,a+1)) for a in (0,1)]
    depots = {i: {"food": 0, "ore": 0, "tools": 0} for i in range(3)}
    return regions, roads, depots


def order(action, target=None, quantity=1):
    return {0: {"action": action, "target": target, "quantity": quantity,
                "budget": {"food":100, "ore":20, "tools":20, "workers":10, "admin_units":1}}}


class PublicWorksTests(unittest.TestCase):
    def test_build_transports_both_inputs_locks_host_labor_and_activates_next_year(self):
        regions, roads, depots = fixture()
        depots[0].update(food=20, ore=7, tools=5)
        before = deepcopy(depots)
        decision = order("road", (0,1))
        t, units, free, workers = execute_works(regions, roads, depots, {}, decision, width=3)
        self.assertEqual([(s["good"],s["quantity"],s["tile_path"]) for s in t["shipments"]],
                         [("ore",6,[0,1]),("tools",4,[0,1])])
        self.assertEqual((units[0,1],free[0,1],workers[1]), (1,2,6))
        self.assertEqual(depots[0], {"food":18,"ore":1,"tools":1})
        self.assertEqual(depots[1], {"food":0,"ore":0,"tools":0})
        self.assertEqual(t["cost_food"],2)
        for field in ("tile_path","quantity","cost_food"):
            bad=deepcopy(t)
            if field=="tile_path":
                bad["shipments"][0][field]=[0,2,1]
            else:
                bad["shipments"][0][field]+=1
            with self.subTest(field=field), self.assertRaises(ValueError):
                audit_works(regions,roads,before,{},decision,bad,width=3)
        t2, units2,free2,workers2=execute_works(regions,roads,depots,units,order("defer"),width=3)
        self.assertEqual((t2["roads"][0]["capacity"],free2[0,1],workers2[1],units2[0,1]),(60,58,1,1))
        t3, units3,*_=execute_works(regions,roads,depots,units2,order("defer"),width=3)
        self.assertEqual((t3["roads"][0]["decayed"],units3[0,1]),(1,0))

    def test_no_partial_kit_or_self_financing_and_soil_follows_land_area(self):
        regions,roads,depots=fixture(9)
        depots[0].update(food=100,ore=10,tools=10)
        before=deepcopy(depots)
        t,_,free,_=execute_works(regions,roads,depots,{},order("road",(0,1)),width=3)
        self.assertEqual((t["projects"],depots,free[0,1]),([],before,9))
        t,_,_,workers=execute_works(regions,roads,depots,{},order("soil",0),width=3)
        self.assertEqual((regions[0].soil,workers[0],t["projects"][0]["treated_tiles"]),(756,4,12))
        self.assertEqual(depots[0],{"food":100,"ore":8,"tools":8})
        regions[0].soil=1149
        execute_works(regions,roads,depots,{},order("soil",0),width=3)
        self.assertEqual(regions[0].soil,1150)

    def test_relief_local_then_multileg_charges_every_leg_and_shares_residuals(self):
        regions,roads,depots=fixture()
        depots[2]["food"]=2
        depots[0]["food"]=15
        pre_nodes,pre_depots=deepcopy(regions),deepcopy(depots)
        limits={(0,1):5,(1,2):8}
        admin={0:6}
        decision=order("relief",2,30)
        t,free=execute_relief(regions,roads,depots,decision,limits,admin,width=3)
        self.assertEqual([(s["path"],s["quantity"],s["cost_food"]) for s in t["shipments"]],
                         [([2],2,0),([0,1,2],4,2)])
        self.assertEqual((regions[2].stock["food"],depots[0]["food"],depots[2]["food"]),(6,9,0))
        self.assertEqual((free[0,1],free[1,2]),(1,4))
        self.assertEqual([r.capacity for r in residual_roads(roads,free)],[1,4])
        for field in ("cost_food","path","tile_path","legs"):
            bad=deepcopy(t)
            bad["shipments"][1][field]=[] if field!="cost_food" else 0
            with self.subTest(field=field), self.assertRaises(ValueError):
                audit_relief(pre_nodes,roads,pre_depots,decision,limits,admin,bad,width=3)
        bad=deepcopy(t)
        bad["nodes"][0]["depot_close"]["food"]+=1
        with self.assertRaises(ValueError):
            audit_relief(pre_nodes,roads,pre_depots,decision,limits,admin,bad,width=3)

    def test_relief_never_delivers_unfunded_rations_or_crosses_a_national_border(self):
        regions,roads,depots=fixture()
        depots[0]["food"]=4
        t,_=execute_relief(regions,roads,depots,order("relief",2,90),
                           {(0,1):12,(1,2):12},{0:100},width=3)
        self.assertEqual((t["delivered"],t["cost_food"],depots[0]["food"]),(2,2,0))
        regions[2].owner=1
        before=deepcopy(depots)
        with self.assertRaises(ValueError):
            execute_relief(regions,roads,depots,order("relief",2,90),
                           {(0,1):12,(1,2):12},{0:100,1:100},width=3)
        self.assertEqual(depots,before)

    def test_reversed_source_orientation_and_no_extra_project_with_missing_labor_or_admin(self):
        regions,roads,depots=fixture()
        depots[1].update(food=8,ore=8,tools=8)
        request=order("road",(0,1))
        request[0]["budget"]["admin_units"]=0
        t,units,_,_=execute_works(regions,roads,depots,{},request,width=3)
        self.assertEqual(t["projects"],[])
        request[0]["budget"]["admin_units"]=1
        regions[0].population=8
        t,units,_,_=execute_works(regions,roads,depots,units,request,width=3)
        self.assertEqual(t["projects"],[])
        regions[0].population=12
        t,units,_,w=execute_works(regions,roads,depots,units,request,width=3)
        self.assertEqual((w[0],units[0,1],t["shipments"][0]["tile_path"]),(6,1,[1,0]))

    def test_public_and_private_stocks_share_one_freight_and_material_balance(self):
        from civsim.logistics import ship

        regions,roads,depots=fixture(18)
        depots[0].update(food=15,ore=16,tools=14)
        regions[0].stock["food"]=120
        def totals():
            return {g:sum(d[g] for d in depots.values())+sum(r.stock[g] for r in regions)
                    for g in ("food","ore","tools")}
        before=totals()
        works,units,free,_=execute_works(regions,roads,depots,{},order("road",(0,1)),width=3)
        relief,free=execute_relief(regions,roads,depots,order("relief",2,10),free,{0:4},width=3)
        private=ship(regions,residual_roads(roads,free),width=3)
        self.assertEqual(before["food"]-totals()["food"], works["cost_food"]+relief["cost_food"]+private["cost_food"])
        self.assertEqual((before["ore"]-totals()["ore"],before["tools"]-totals()["tools"]),(6,4))
        public_used=18-free[0,1]
        private_used=next(e["used"] for e in private["roads"] if e["a"]==0 and e["b"]==1)
        self.assertEqual(public_used+private_used,18)
        self.assertEqual(units[0,1],1)

    def test_gross_budget_includes_freight_and_audit_rejects_fragmented_overspending(self):
        regions,roads,depots=fixture()
        depots[0]["food"]=90
        request=order("relief",2,30)
        request[0]["budget"]["food"]=5
        capacities={(0,1):12,(1,2):12}
        before=deepcopy(depots),deepcopy(regions)
        t,_=execute_relief(regions,roads,depots,request,capacities,{0:30},width=3)
        self.assertEqual((t["delivered"],t["cost_food"]),(3,2))
        with self.assertRaises(ValueError):
            audit_relief(before[1],roads,before[0],request,capacities,{0:2},t,width=3)
        t["shipments"].append(deepcopy(t["shipments"][0]))
        with self.assertRaises(ValueError):
            audit_relief(before[1],roads,before[0],request,capacities,{0:30},t,width=3)
