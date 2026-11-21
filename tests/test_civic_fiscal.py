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
        # Duplicate the correct aggregate in a second occupation or transfer a loss between phases.
        for kind in ("duplicate", "wrong_phase", "hidden_fee", "phantom_good"):
            bad=deepcopy(result)
            if kind == "duplicate":
                bad[0]["civic_tax"]["by_group"]["consumer"]["paid"]["food"]=57
            elif kind == "wrong_phase":
                bad[0]["standing_levy"]["food"]+=1
                bad[0]["extra_levy"]["food"]-=1
            elif kind == "hidden_fee":
                bad[0]["handling_used"]["food"]=1
                bad[0]["deposited"]["food"]+=1
                bad[0]["depot_close"]["food"]+=1
            else:
                bad[0]["depot_close"]["extra_food"]=1
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                audit_civic_collection([r],choice,ctx,bad)

    def test_compromise_forfeits_reserve_and_pays_only_for_completed_soil_work(self):
        from civsim.model import generate_world
        from civsim.regions import regionalize
        world=regionalize(generate_world(1,8,8,1),2)
        r=world.regions[0]
        r.soil=900
        r.population=3000
        r.stock={"food":4075,"ore":300,"tools":300}
        cash={q.id:{"food":0,"ore":6,"tools":6} for q in world.regions}
        def option(action, score, quantity, budget):
            return {"action":action,"score":score,"quantity":quantity,"permitted":True,"constraints":[],
                    "target_region":0,"target_edge":None,"population_loss":0,"budget":budget}
        reserve=option("reserve",50,80,{"food":80,"ore":0,"tools":0,"workers":0,"admin_units":1})
        soil=option("soil",20,1,{"food":0,"ore":2,"tools":2,"workers":4,"admin_units":1})
        plan={**reserve,"owner":0,"mode":"integrated","selected_score":50,"relief_throughput":20,
              "candidates":[reserve,soil]}
        rows=[{"id":q.id,"owner":q.owner,"groups":groups("refusal","soil",500) if q.id==0 else groups()}
              for q in world.regions]
        actual,reply=respond(plan,rows)
        self.assertEqual((reply["kind"],reply["legal_concession_permille"]),("compromise",125))
        self.assertEqual((reply["before"]["action"],reply["before"]["quantity"],reply["after"]["action"]),
                         ("reserve",80,"soil"))
        with self.subTest("a later staffing constraint can prevent any expenditure"):
            scarce=deepcopy(world)
            vault=deepcopy(cash)
            receipt,_,_,reserved=execute_works(scarce.regions,scarce.roads,vault,{}, {0:actual},
                width=scarce.width,withheld={q.id:q.population//2 for q in scarce.regions})
            self.assertFalse(receipt["projects"])
            self.assertEqual((reserved[0],scarce.regions[0].soil,vault[0]),(0,900,cash[0]))
        receipt,_,_,reserved=execute_works(world.regions,world.roads,cash,{}, {0:actual},width=world.width)
        project,=receipt["projects"]
        self.assertEqual((project["used"],reserved[0],cash[0]),({"food":0,"ore":2,"tools":2},4,
                                                                {"food":0,"ore":4,"tools":4}))
        self.assertEqual(r.soil-900,project["soil_gain"])
        self.assertGreater(project["soil_gain"],0)
        ledger=collect_civic(world.regions,cash,{0:actual},{"regions":rows,"responses":[reply]})
        self.assertEqual((ledger[0]["baseline_levy"]["food"],ledger[0]["foregone_concession"]["food"],
                          ledger[0]["refused"]["food"],ledger[0]["levied"]["food"]),(43,5,19,19))
        self.assertEqual(ledger[0]["extra_levy"]["food"],0)
        self.assertEqual(r.stock["food"],4075-19)

    def test_unassessed_group_can_win_a_concession_without_revenue_loss(self):
        r=SimpleNamespace(id=0,owner=0,population=3000,stock={"food":4075,"ore":300,"tools":300})
        depot={0:dict.fromkeys(r.stock,0)}
        choice={0:{"owner":0,"mode":"integrated","action":"defer","quantity":0,"target_region":None}}
        gs=groups()
        gs["consumer"].update(action="refusal",participants=1000)
        ctx={"regions":[{"id":0,"owner":0,"groups":gs}],"responses":[
            {"id":0,"concession_region":0,"concession_group":"consumer","legal_concession_permille":250}]}
        receipt,=collect_civic([r],depot,choice,ctx)
        self.assertEqual(receipt["foregone_concession"],dict.fromkeys(r.stock,0))
        self.assertEqual(receipt["refused"],dict.fromkeys(r.stock,0))
        self.assertGreater(receipt["baseline_levy"]["food"],0)

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
