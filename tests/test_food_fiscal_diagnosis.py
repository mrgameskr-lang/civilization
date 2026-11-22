import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from experiments.food_fiscal_diagnosis import (
    _baseline_tax, _empty_tax, fiscal_flows, tax_reason, summarize_band,
    FLOW_KEYS, TAX_AMOUNTS, TAX_KEYS,
)


class FiscalDiagnosisTests(unittest.TestCase):
    def test_world_uses_gross_levy_and_counts_aid_loss_freight_and_levy_handling_once(self):
        r=dict.fromkeys(FLOW_KEYS,0)
        r.update(public_open=10,harvest_public=12,levied_food=6,levy_deposited_food=5,levy_handling_food=1,
                 relief_sent_food=2,relief_received_food=2,household_public_issue_food=2,aid_sent_food=5,
                 aid_received_food=4,aid_handling_food=1,aid_freight_food=2,public_freight_food=2,
                 depot_transfer_sent_food=9,depot_transfer_received_food=9,depot_spoiled_food=2,public_close=18)
        f=fiscal_flows(r)
        self.assertEqual((f["gross_inflow"],f["total_outflow"],f["net_stock_change"]),(18,10,8))
        for k in ("public_close","levy_handling_food","aid_handling_food","public_freight_food","depot_transfer_received_food"):
            with self.subTest(k=k),self.assertRaises(ValueError):
                fiscal_flows({**r,k:r[k]+1})

    def test_tax_receipts_separate_floor_room_rounding_and_uncollected_legal_assessments(self):
        def row(surplus,room,assessed=0,cut=0,refused=0,handling=0,population=640):
            t=dict.fromkeys(TAX_KEYS,0)
            t.update(tax_private_before=100+surplus,tax_protected_food=100,taxable_surplus_food=surplus,
                     population=population,tax_warehouse_space=room,tax_assessed_food=assessed,
                     tax_concession_food=cut,tax_refused_food=refused,levied_food=assessed-cut-refused,
                     levy_handling_food=handling,levy_deposited_food=assessed-cut-refused-handling)
            return t
        cases=[
            (row(0,0),"at_or_below_protected_floor"),(row(10,0),"no_warehouse_space"),
            (row(15,3),"standing_integer_ceiling_zero"),(row(50,3,population=63),"standing_integer_ceiling_zero"),
            (row(18,3),"other_zero_assessment"),(row(30,3,2,cut=2),"fully_conceded"),
            (row(30,3,2,refused=2),"fully_refused"),(row(30,3,2,cut=1,refused=1),"conceded_and_refused"),
            (row(30,3,1,handling=1),"entire_collection_spent_on_handling"),(row(30,3,2),"positive_net_deposit"),
        ]
        for record,want in cases:
            with self.subTest(want=want): self.assertEqual(tax_reason(record),want)
        with self.assertRaises(ValueError): tax_reason({**cases[-1][0],"levied_food":3})

    def test_flow_rates_use_world_years_while_boundary_stocks_use_worlds(self):
        values=dict.fromkeys(FLOW_KEYS,0)
        values.update(levied_food=2,levy_deposited_food=2,public_open=3,public_close=5)
        a=fiscal_flows(values)
        b=fiscal_flows({**values,"public_open":5,"public_close":7})
        result=summarize_band([([a,b],3,7),([a,b],3,7)],1,2)
        self.assertEqual((result["worlds"],result["world_years"]),(2,4))
        self.assertEqual(result["totals"]["levied_food"],8)
        self.assertEqual(result["per_world_year"]["levied_food"],2)
        self.assertEqual(result["boundary_stocks"],{"opening_sum":6,"closing_sum":14,
                                                    "opening_per_world":3,"closing_per_world":7})
        with self.assertRaises(ValueError): summarize_band([([a,b],3,6)],1,2)

    def test_cross_tab_preserves_zero_harvest_positive_collection_and_rejects_coverage_errors(self):
        columns = ["year", "region", "owner", "harvest_total", *TAX_KEYS]
        template = dict.fromkeys(columns, 0)
        template.update(year=1, population=64, tax_private_before=80, tax_protected_food=64,
                        taxable_surplus_food=16, tax_warehouse_space=3, tax_assessed_food=1,
                        levied_food=1, levy_deposited_food=1)
        rows = [[{**template, "region": i, "owner": i // 4}[k] for k in columns] for i in range(32)]
        world = {k: 32 * template[k] for k in (*TAX_AMOUNTS, "harvest_total")}
        header = {"schema": "food-flow/1", "arm": "A", "seed": 0, "columns": columns}
        with TemporaryDirectory() as directory:
            path = Path(directory) / "seed-00-A-regions.jsonl.gz"

            def census(pages, totals):
                raw = "".join(json.dumps(page) + "\n" for page in [header, *pages])
                path.write_bytes(gzip.compress(raw.encode()))
                pooled = [_empty_tax()]
                _baseline_tax(path, {}, 0, [(totals, {})], pooled)
                return pooled[0]

            result = census([rows], world)
            self.assertEqual(result["classes"]["zero_harvest"], 32)
            self.assertEqual(result["reasons_by_harvest"]["no_harvest"]["positive_net_deposit"], 32)
            for pages, totals in (([], world), ([rows + [rows[0]]], world), ([rows[:-1]], world),
                                  ([rows, rows], world), ([rows], {**world, "levied_food": 0})):
                with self.subTest(pages=len(pages), totals=totals), self.assertRaises(ValueError):
                    census(pages, totals)
