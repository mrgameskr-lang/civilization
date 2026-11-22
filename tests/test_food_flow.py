from copy import deepcopy
import gzip
import json
from pathlib import Path
import unittest

from experiments.food_flow import COLUMNS, PROVENANCE, aggregate, region_rows


def actual(year_index=1):
    path = Path(__file__).resolve().parents[1] / "examples/token-upkeep-v1/case/move_on.jsonl.gz"
    with gzip.open(path,"rt",encoding="utf-8") as stream:
        return list(map(json.loads,stream))[year_index]


def named(rows):
    return [dict(zip(COLUMNS,r,strict=True)) for r in rows]


class FoodFlowTests(unittest.TestCase):
    def test_full_annual_custody_and_production_match_the_original_economy(self):
        record=actual()
        rows=named(region_rows(record))
        self.assertEqual(len(COLUMNS),len(set(COLUMNS)))
        self.assertEqual(set(COLUMNS),set(PROVENANCE))
        self.assertEqual([r["region"] for r in rows],list(range(32)))
        for r,n in zip(rows,record["regions"],strict=True):
            self.assertTrue(all(type(v) is int for v in r.values()))
            self.assertEqual(r["harvest_total"],n["production"]["produced"]["food"])
            self.assertEqual((r["harvest_public"],r["harvest_private"]),(0,r["harvest_total"]))
            self.assertEqual(r["taxable_surplus_food"],max(0,r["tax_private_before"]-r["tax_protected_food"]))
            self.assertEqual(r["private_close"],n["closing"]["stock"]["food"])
            self.assertEqual(r["food_eaten"]+r["food_unmet"],r["population"])
        self.assertEqual(sum(r["private_domestic_food_in"] for r in rows),sum(r["private_domestic_food_out"] for r in rows))
        self.assertEqual(sum(r["private_foreign_food_in"] for r in rows),sum(r["private_foreign_food_out"] for r in rows))

    def test_zero_public_share_receipts_preserve_gross_crop_and_reject_double_booking(self):
        record=actual(); shares=[]
        vaults={q["region"]:q["depot_open"].copy() for q in record["government"]["levies"]}
        for shipment in record["diplomacy"]["physical"]["aid"]["shipments"]:
            vaults[shipment["source"]]["food"]+=shipment["quantity"]+shipment["cost_food"]
            vaults[shipment["target"]]["food"]-=shipment["received"]
        for r in record["regions"]:
            p=r["production"]; a=p["active_farmers"]; crop=p["produced"]["food"]
            shares.append(dict(id=r["id"],owner=r["owner"],food_total=crop,food_public=0,food_private=crop,
                               workers_total=a,workers_public=0,workers_private=a,slots_total=a,slots_public=0,
                               slots_private=a,private_before=p["closing_stock"].copy(),private_after=p["closing_stock"].copy(),
                               depot_before=vaults[r["id"]].copy(),depot_after=vaults[r["id"]].copy()))
        old=region_rows(record)
        record["public_harvest"]={"regions":shares}
        self.assertEqual(region_rows(record),old)
        for field in ("food_private","food_public","workers_total","slots_total","depot_after"):
            broken=deepcopy(record)
            receipt=broken["public_harvest"]["regions"][0]
            if field=="depot_after": receipt[field]["food"]+=1
            else: receipt[field]+=1
            with self.subTest(field=field),self.assertRaises(ValueError):
                region_rows(broken)

    def test_separate_private_and_public_checks_reject_balanced_looking_mutations(self):
        for field in ("crop","climate","private_close","public_close","tax","freight","household_ration","domestic_node"):
            r=actual()
            if field=="crop": r["regions"][0]["production"]["produced"]["food"]+=1
            if field=="climate": r["regions"][0]["climate"]+=1
            if field=="private_close": r["regions"][0]["closing"]["stock"]["food"]+=1
            if field=="public_close": r["government"]["depots"][0]["closing"]["food"]+=1
            if field=="tax": r["government"]["levies"][0]["standing_levy"]["food"]+=1
            if field=="freight": r["border_market"]["trades"][0]["cost_food"]+=1
            if field=="household_ration": r["service"]["regions"][0]["ration_food"]+=1
            if field=="domestic_node": r["domestic"]["nodes"][0]["imports"]["food"]+=1
            with self.subTest(field=field),self.assertRaises(ValueError): region_rows(r)

    def test_world_and_countries_add_flows_count_joint_conditions_and_weight_inputs(self):
        rows=region_rows(actual())
        cells=named(rows); result=aggregate(rows)
        self.assertEqual((result["year"],len(result["countries"]),result["world"]["region_count"]),(2,8,32))
        together=result["world"]
        self.assertEqual(together["private_harvest_no_surplus_regions"],sum(r["harvest_private"]>0 and r["taxable_surplus_food"]==0 for r in cells))
        self.assertEqual(together["harvest_total"],sum(c["harvest_total"] for c in result["countries"]))
        self.assertEqual(together["food_eaten"],sum(r["food_eaten"] for r in cells))
        self.assertEqual(together["productivity_farmer_weighted_sum"],
                         sum(r["productivity"]*r["farm_workers_total"] for r in cells))
        with self.assertRaises(ValueError): aggregate([rows[0],rows[0]])
        with self.assertRaises(ValueError): aggregate([])

    def test_real_same_opening_public_farm_reassigns_crop_and_workers_without_inventing_food(self):
        from civsim.annual_game import create
        from civsim.unit_economy import step_game

        game=create(0)
        step_game(game)
        common=deepcopy(game)
        baseline=step_game(game)
        changed=step_game(common,public_farm=True)
        a=aggregate(region_rows(baseline))["world"]
        c=aggregate(region_rows(changed))["world"]
        self.assertGreater(c["harvest_public"],0)
        self.assertGreater(c["public_farm_workers"],0)
        self.assertEqual((a["harvest_total"],a["farm_workers_total"]),(c["harvest_total"],c["farm_workers_total"]))
        self.assertEqual(a["harvest_private"]-c["harvest_private"],c["harvest_public"])
        self.assertEqual(c["public_farm_workers"],c["public_farm_slots"])
        self.assertEqual(a["private_open"]+a["public_open"],c["private_open"]+c["public_open"])
        receipt=next(r for r in changed["public_harvest"]["regions"] if r["workers_public"]>0)
        for prefix in ("workers","slots"):
            receipt[prefix+"_private"]+=1
            receipt[prefix+"_public"]-=1
        with self.assertRaises(ValueError): region_rows(changed)
