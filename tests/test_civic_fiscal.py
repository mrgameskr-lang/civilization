from copy import deepcopy
from types import SimpleNamespace
import unittest

from civsim.civic_fiscal import audit_civic_collection, collect_civic, respond, withheld_labor
from civsim.fiscal_policy import decide
from civsim.public_works import execute_works


def groups(action="none", demand="none", n=0):
    return {k:{"action":action if k=="farm" else "none","participants":n if k=="farm" else 0,
               "members":1000,"duration":1,"demand":demand if k=="farm" else "none","withheld_workers":0}
            for k in ("farm","industry","consumer")}


class CivicFiscalTests(unittest.TestCase):
    def test_refusal_after_concession_stays_private_with_actual_handling(self):
        r=SimpleNamespace(id=0,owner=0,population=3000,stock={"food":4075,"ore":300,"tools":300})
        depot={0:{"food":0,"ore":0,"tools":0}}
        choice={0:{"owner":0,"mode":"integrated","action":"reserve","quantity":80,"target_region":0}}
        ctx={"regions":[{"id":0,"owner":0,"groups":groups("refusal","defer",500)}],
             "responses":[{"id":0,"concession_region":0,"concession_group":"farm","legal_concession_permille":250}]}
        old=r.stock.copy()
        result=collect_civic([r],depot,choice,ctx)
        row=result[0]
        self.assertEqual(row["baseline_levy"]["food"],123)  # 700 surplus: floor(700/16) + 80.
        self.assertEqual(row["foregone_concession"]["food"],10)
        self.assertEqual(row["refused"]["food"],56)  # 16 of 33 standing + 40 of the 80 supplemental.
        self.assertEqual(row["levied"]["food"],57)
        self.assertEqual((row["extra_levy"]["food"],row["handling_used"]["food"]),(40,2))
        self.assertEqual((depot[0]["food"],old["food"]-r.stock["food"]),(55,57))
        for key in ("baseline_levy","foregone_concession","refused","levied"):
            bad=deepcopy(result)
            bad[0][key]["food"]+=1
            with self.assertRaises(ValueError):
                audit_civic_collection([r],choice,ctx,bad)

    def test_workers_withdrawn_before_construction_and_oversubscription_rejected(self):
        from civsim.model import generate_world
        from civsim.regions import regionalize
        world=regionalize(generate_world(1,8,8,1),2)
        r=world.regions[0]
        r.population=8
        ctx={"regions":[{"id":q.id,"owner":q.owner,"groups":groups()} for q in world.regions]}
        gs=ctx["regions"][0]["groups"]
        for g in gs.values():
            g["members"]=0
        gs["farm"].update(action="strike",members=4,participants=4,withheld_workers=4)
        for g in ctx["regions"][1]["groups"].values():
            g["members"]=0
        held=withheld_labor(world.regions,ctx)
        choice={0:{"action":"soil","target_region":0,"quantity":1,"budget":{"workers":4,"food":0,"ore":2,
                                                                             "tools":2,"admin_units":1}}}
        depots={q.id:{"food":20,"ore":20,"tools":20} for q in world.regions}
        got=execute_works(world.regions,world.roads,depots,{},choice,width=world.width,withheld=held)
        self.assertEqual(got[0]["projects"],[])
        self.assertEqual(got[3][0],0)
        gs["farm"]["withheld_workers"]=5
        with self.assertRaises(ValueError):
            withheld_labor(world.regions,ctx)

    def test_petitions_use_existing_relief_slots_and_rank_only_funded_options(self):
        from civsim.model import generate_world
        from civsim.regions import regionalize
        world=regionalize(generate_world(0,12,8,1),2)
        vault={r.id:{"food":100,"ore":30,"tools":30} for r in world.regions}
        observed={r.id:{"food_need":r.population,"food_output":r.population,"unmet":45,
                        "pop_delta":0,"soil_delta":0} for r in world.regions}
        plan=decide(0,world.regions,world.roads,vault,observed,{},"integrated")
        rows=[{"id":r.id,"owner":0,"groups":groups("petition","relief",64) if r.id==0 else groups()}
              for r in world.regions]
        new, receipt=respond(plan,rows)
        self.assertEqual(receipt["petition_admin_used"],2)
        self.assertEqual(receipt["admin_remaining"]+2, plan["relief_throughput"])
        self.assertIn(receipt["kind"],("maintain","reprioritize"))
        self.assertEqual(new["candidates"],plan["candidates"])
