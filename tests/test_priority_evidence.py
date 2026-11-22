"""Read civilian fiscal receipts, keeping receipts and end-of-year stocks distinct."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import unittest

from experiments.priority_evidence import COLUMNS, PROVENANCE, region_rows


def basket(food=0, ore=0, tools=0):
    return {"food":food, "ore":ore, "tools":tools}


def example():
    homes = [(4,0),(7,0),(15,1)]
    levies = [{"region":i,"owner":owner,"levied":basket(4,1,2),"handling_used":basket(1),
               "deposited":basket(3,1,2),"depot_open":basket(7,2,3),"depot_close":basket(10,3,5)}
              for i,owner in homes]
    bank = [{"region":i,"owner":owner,"opening":basket(30,12,9),"closing":basket(16,9,5),"spoil_food":1}
            for i,owner in homes]
    return {"year":2,"regions":[{"id":i,"owner":n} for i,n in reversed(homes)],
            "government":{"depots":bank,"levies":levies,
                          "works":{"projects":[{"owner":0,"source":4,"target":7,"used":basket(0,6,4)}],
                                   "shipments":[{"owner":0,"source":4,"target":7,"cost_food":2}]},
                          "relief":{"shipments":[{"owner":0,"source":4,"target":7,"quantity":5,"cost_food":1},
                                                 {"owner":0,"source":7,"target":7,"quantity":2,"cost_food":0}]}},
            "supply":{"shipments":[{"source":4,"target":7,"owner":0,"good":"tools","quantity":3,"cost_food":1}]},
            "diplomacy":{"physical":{"aid":{"shipments":[{"source":7,"target":15,"donor":0,"recipient":1,
                "quantity":6,"received":5,"handling_food":1,"cost_food":2}]}}}}


def keyed(record,**options):
    rows = [dict(zip(COLUMNS,row,strict=True)) for row in region_rows(record,**options)]
    return {row["region"]:row for row in rows}


class FiscalEvidenceTests(unittest.TestCase):
    def test_projects_relief_tax_aid_and_transfers_use_the_actual_source_and_receiver(self):
        raw=example(); original=deepcopy(raw)
        rows=keyed(raw)
        self.assertEqual(list(rows),[4,7,15])
        self.assertEqual((rows[4]["works_used_ore"],rows[7]["works_used_ore"],rows[4]["works_freight_food"]),(6,0,2))
        self.assertEqual((rows[4]["relief_sent_food"],rows[7]["relief_sent_food"],
                          rows[7]["relief_received_food"],rows[4]["relief_freight_food"]),(5,2,7,1))
        self.assertEqual((rows[7]["aid_sent_food"],rows[15]["aid_received_food"],
                          rows[7]["aid_handling_food"],rows[7]["aid_freight_food"]),(6,5,1,2))
        self.assertEqual((rows[4]["levied_food"],rows[4]["levy_deposited_food"],rows[4]["levy_handling_food"]),(4,3,1))
        self.assertEqual((rows[4]["depot_transfer_sent_tools"],rows[7]["depot_transfer_received_tools"],
                          rows[4]["depot_transfer_freight_food"]),(3,3,1))
        self.assertEqual((rows[7]["depot_open_food"],rows[7]["depot_close_food"],rows[7]["depot_spoiled_food"]),(30,16,1))
        self.assertEqual(set(COLUMNS),set(PROVENANCE))
        self.assertEqual(raw,original)

    def test_only_observed_next_opening_is_exposed(self):
        r=example()
        self.assertTrue(all(row["next_depot_open_food"] is None for row in keyed(r).values()))
        n=deepcopy(r); n["year"]+=1
        for depot in n["government"]["depots"]:
            depot["opening"]=depot["closing"].copy()
        self.assertTrue(all(row["next_depot_open_tools"]==5 for row in keyed(r,next_record=n).values()))
        bad=deepcopy(n); bad["government"]["depots"][0]["opening"]["food"]+=1
        with self.assertRaises(ValueError): region_rows(r,next_record=bad)
        with self.assertRaises(ValueError): region_rows(r,next_record=r)

    def test_an_empty_observed_source_has_zero_flows_but_absent_optional_source_is_unknown(self):
        r=example()
        r["diplomacy"]["physical"]["aid"]["shipments"]=[]
        self.assertEqual(keyed(r)[7]["aid_sent_food"],0)
        del r["diplomacy"]; del r["supply"]
        self.assertIsNone(keyed(r)[7]["aid_sent_food"])
        self.assertIsNone(keyed(r)[4]["depot_transfer_sent_ore"])
        self.assertEqual(keyed(r)[4]["relief_sent_food"],5)

    def test_mismatched_custody_and_mutated_receipts_are_rejected(self):
        for fault in ("levy","aid","foreign_relief","duplicate","coverage","negative","missing_table"):
            r=example(); g=r["government"]
            if fault=="levy": g["levies"][0]["depot_close"]["ore"]+=1
            if fault=="aid": r["diplomacy"]["physical"]["aid"]["shipments"][0]["received"]+=1
            if fault=="foreign_relief": g["relief"]["shipments"][0]["target"]=15
            if fault=="duplicate": g["depots"].append(deepcopy(g["depots"][0]))
            if fault=="coverage": g["levies"].pop()
            if fault=="negative": g["works"]["projects"][0]["used"]["food"]=-1
            if fault=="missing_table": del g["works"]["shipments"]
            with self.subTest(fault=fault),self.assertRaises(ValueError): region_rows(r)

    def test_published_civilian_country_totals_equal_sum_of_region_receipts(self):
        base=Path(__file__).resolve().parents[1] / "examples/annual-unit-v1/case/hold-years2-3.jsonl.gz"
        with gzip.open(base,"rt",encoding="utf-8") as stream:
            first,second=map(json.loads,stream)
        rows=keyed(first,next_record=second)
        self.assertEqual(len(rows),32)
        for country in first["government"]["accounts"]:
            group=[row for row in rows.values() if row["owner"]==country["id"]]
            total=country["totals"]
            for key,label in (("levied_food","levied_food"),("relief_sent_food","relief_food"),
                              ("works_used_tools","works_tools"),("depot_spoiled_food","public_spoil_food")):
                self.assertEqual(sum(row[key] for row in group),total[label])
            self.assertEqual(sum(row["next_depot_open_food"] for row in group),country["public_close"]["food"])
