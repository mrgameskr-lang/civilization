from copy import deepcopy
from types import SimpleNamespace as NS
import unittest

from civsim.regions import Road
from civsim.economy import consume
from civsim.service62 import (apply_service_rations, audit_service, close_service, plan_service,
                              settle_service, start_service)


def stock(food=0,tools=0):
    return {"food":food,"ore":0,"tools":tools}


def places():
    return [NS(id=0,owner=0,seat=0,land=1,population=2400,stock=stock(800)),
            NS(id=1,owner=0,seat=2,land=80,population=2400,stock=stock(0))]


def observations():
    groups={g:{"signals":{"relief":0,"road":0},"members":1600,"support":500} for g in ("farm","industry","consumer")}
    return {"countries":[{"id":0,"population":4800,"prior_need":4800,"prior_crop":7200,
                          "party":"caretaker","stock":stock(800),"depot":stock(200),"shortage_permille":0,"groups":groups}],"pairs":[]}


def vital(p,deaths=0,emigrants=0,immigrants=0):
    return {"opening_population":p,"births":0,"deaths":deaths,"population_before_migration":p-deaths,
            "emigrants":emigrants,"immigrants":immigrants,"closing_population":p-deaths-emigrants+immigrants}


class ServiceTests(unittest.TestCase):
    def test_existing_residents_are_retained_and_recruitment_can_be_held(self):
        reg=places()
        memory=start_service(reg)
        memory[0]=8
        ctx=observations()
        ordinary=plan_service(reg,memory,ctx,"fixed",withheld={0:200})
        held=plan_service(reg,memory,ctx,"fixed",withheld={0:200},recruit=False)
        row,other=ordinary["regions"][0],held["regions"][0]
        self.assertEqual(row["eligible_workers"],1000)
        self.assertEqual(row["enrolled"],11)
        self.assertEqual((other["target"],other["released"],other["enrolled"],other["serving"]),
                         (row["target"],row["released"],0,8))
        self.assertEqual([r.population for r in reg],[2400,2400])
        self.assertEqual(memory,{0:8,1:0})
        self.assertEqual(plan_service(reg,memory,ctx,"off")["regions"][0]["released"],8)

    def test_lagged_evidence_and_domestic_food_cost_change_desired_staff(self):
        reg=places()
        ctx=observations()
        plain=plan_service(reg,start_service(reg),ctx,"adaptive")["countries"][0]
        strained=deepcopy(ctx)
        strained["pairs"]=[{"a":0,"b":1,"adjacent":True,"opening":{"tension":400,"relation":0,"last":[
            {"source":0,"target":1,"import_dependence":500,"agreement_breach":1},
            {"source":1,"target":0,"import_dependence":0,"agreement_breach":0}]}}]
        higher=plan_service(reg,start_service(reg),strained,"adaptive")["countries"][0]
        self.assertEqual(higher["target_rate_permille"]-plain["target_rate_permille"],31)
        strained["countries"][0]["shortage_permille"]=720
        self.assertLess(plan_service(reg,start_service(reg),strained,"adaptive")["countries"][0]["target"],plain["target"])

    def test_foregone_harvest_incumbent_support_and_relation_enter_adaptive_choice(self):
        reg=places()
        ctx=observations()
        ctx["pairs"]=[{"a":0,"b":1,"adjacent":True,"opening":{"tension":0,"relation":0,"last":[
            {"source":0,"target":1,"import_dependence":0,"agreement_breach":0},
            {"source":1,"target":0,"import_dependence":0,"agreement_breach":0}]}}]
        def planned(mode="adaptive"):
            return plan_service(reg,start_service(reg),ctx,mode)["countries"][0]
        before=planned()
        self.assertEqual((before["reference_roster"],before["reference_foregone_food"],
                          before["foregone_share_permille"],before["rate_adjustments"]["opportunity"]),(57,171,30,-7))
        ctx["countries"][0]["prior_crop"]=0
        self.assertGreater(planned()["target"],before["target"])
        base=planned()["target_rate_permille"]
        ctx["countries"][0]["party"]="builders"
        self.assertEqual(planned()["target_rate_permille"],base+4)
        ctx["countries"][0]["party"]="mutualists"
        self.assertEqual(planned()["target_rate_permille"],base-4)
        ctx["countries"][0]["party"]="caretaker"
        for g in ctx["countries"][0]["groups"].values():
            g["support"]=750
        self.assertEqual(planned()["target_rate_permille"],base+2)
        ctx["pairs"][0]["opening"]["relation"]=-200
        self.assertEqual(planned()["target_rate_permille"],base+6)
        ctx["pairs"][0]["opening"]["relation"]=200
        self.assertEqual(planned()["target_rate_permille"],base-2)
        self.assertEqual(planned("fixed")["target_rate_permille"],24)

    def test_real_roundtrip_rations_tools_and_end_of_year_carry(self):
        reg=places()
        ctx=observations()
        memory={0:27,1:27}
        p=plan_service(reg,memory,ctx,"fixed")
        road=Road(0,1,2,10,(0,1,2))
        residual={(0,1):10}
        funds={0:stock(100,5),1:stock(100,10)}
        original=deepcopy(funds)
        before=deepcopy(reg)
        remaining=settle_service(p,reg,funds,[road],residual)
        self.assertEqual(len(p["moves"]),1)
        m=p["moves"][0]
        self.assertEqual((m["home"],m["station"],m["people"],m["road_load"],m["travel_food"]),(0,1,5,10,1))
        self.assertEqual((m["path"],remaining,residual),([0,1,2],{(0,1):0},{(0,1):10}))
        served=sum(r["serving"] for r in p["regions"])
        self.assertEqual(served,sum(r["stationed"] for r in p["regions"]))
        self.assertEqual(p["countries"][0]["available"],served)
        self.assertEqual(p["countries"][0]["readiness_permille"],1000)
        for r in p["regions"]:
            for good in ("food","ore","tools"):
                self.assertEqual(original[r["id"]][good]-funds[r["id"]][good],r["used"][good])
        self.assertEqual(reg[0].stock,before[0].stock)
        apply_service_rations(p,reg)
        self.assertEqual(sum(r.stock["food"]-b.stock["food"] for r,b in zip(reg,before)),served)
        with self.assertRaises(ValueError): apply_service_rations(p,reg)
        vitals={0:vital(2400,240,120),1:vital(2400,0,0,120)}
        closing=close_service(p,vitals)
        self.assertGreater(p["regions"][0]["service_deaths"],0)
        self.assertGreater(p["regions"][0]["service_emigrants"],0)
        self.assertEqual(closing[1],p["regions"][1]["serving"])
        self.assertEqual(sum(closing.values()),served-p["countries"][0]["service_deaths"]-p["countries"][0]["service_emigrants"])
        args=dict(regions=before,roster=memory,diplomacy_ctx=ctx,withheld={},depots=original,
                  roads=[road],residual=residual,vitals=vitals)
        audit_service(p,**args)
        bad=deepcopy(p)
        bad["moves"][0]["road_load"]-=1
        with self.assertRaises(ValueError): audit_service(bad,**args)

    def test_no_supplies_or_closed_road_provides_no_free_capacity(self):
        reg=places()
        p=plan_service(reg,{0:25,1:25},observations(),"fixed")
        roads=[Road(0,1,2,10,(0,1,2))]
        funds={0:stock(),1:stock()}
        self.assertEqual(settle_service(p,reg,funds,roads,{(0,1):0}),{(0,1):0})
        self.assertEqual((p["moves"],p["countries"][0]["available"],p["countries"][0]["readiness_permille"]),([],0,0))
        self.assertGreater(p["countries"][0]["serving"],0)
        self.assertEqual(p["countries"][0]["used"],stock())

    def test_public_personal_rations_replace_part_of_the_one_resident_meal(self):
        reg=places()
        reg[0].stock["food"]=reg[0].population
        p=plan_service(reg,{0:25,1:25},observations(),"fixed")
        funds={0:stock(70,2),1:stock(70,0)}
        settle_service(p,reg,funds,[],{})
        apply_service_rations(p,reg)
        meals={r.id:consume(r) for r in reg}
        self.assertEqual(meals[0]["food_need"],2400)
        self.assertEqual(meals[0]["food_eaten"],2400)
        self.assertEqual(meals[1]["food_eaten"],p["regions"][1]["ration_food"])
        self.assertEqual(p["regions"][1]["available"],0)
