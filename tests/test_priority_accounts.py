"""Compact public accounts, with equal closing stocks under two spending orders."""
from contextlib import contextmanager
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from experiments.check_priority_accounts import FIELDS, check_file


def records(arm):
    years=[]
    for year in (1,2):
        by_region=[]
        for i in (0,1):
            r=dict.fromkeys(FIELDS,0)
            r.update(region=i,owner=i,year=year)
            for g,q in (("food",10),("ore",2),("tools",4)):
                r["depot_open_"+g] = q if year==1 else years[0][i]["depot_close_"+g]
            if year==1 and i==0:
                r.update(aid_sent_food=3,aid_freight_food=1,aid_handling_food=1,levied_food=4,
                         levy_deposited_food=3,levy_handling_food=1,relief_sent_food=2,
                         relief_received_food=2,relief_freight_food=1,paid=1)
            if year==1 and i==1:
                r.update(aid_received_food=2,depot_spoiled_food=1)
            before=r["depot_open_food"]+r["levy_deposited_food"]+r["aid_received_food"]-r["aid_sent_food"]-r["aid_freight_food"]
            r["relief_open_food"] = before - (0 if arm=="relief_first" else r["paid"])
            r["relief_close_food"] = r["relief_open_food"]-r["relief_sent_food"]-r["relief_freight_food"]
            r["depot_close_food"] = r["relief_close_food"]-r["depot_spoiled_food"]-(r["paid"] if arm=="relief_first" else 0)
            r["depot_close_ore"]=r["depot_open_ore"]
            r["depot_close_tools"]=r["depot_open_tools"]-r["paid"]
            for g in ("food","ore","tools"):
                r["next_depot_open_"+g]=r["depot_close_"+g] if year==1 else None
            by_region.append(r)
        years.append(by_region)
    return years


@contextmanager
def archive(arm, years):
    with TemporaryDirectory() as d:
        p=Path(d)/"test.jsonl.gz"
        # Unrelated non-fiscal data are ignored even if their types are arbitrary.
        cols=["unused_extra",*FIELDS]
        with gzip.open(p,"wt",encoding="utf-8") as f:
            f.write(json.dumps({"schema":"regional-budget/1","seed":7,"arm":arm,"columns":cols})+"\n")
            for data in years:
                f.write(json.dumps([[{"ignored":True},*[r[c] for c in FIELDS]] for r in data])+"\n")
        yield p


class CompactAccountTests(unittest.TestCase):
    def test_both_spending_orders_reconcile_foreign_aid_loss_and_successive_openings(self):
        for arm in ("move_on","relief_first"):
            with self.subTest(arm=arm),archive(arm,records(arm)) as path:
                r=check_file(path,7,arm,years=2,region_count=2,country_count=2)
                self.assertEqual((r["region_years"],r["stock_balances"],r["linked_region_openings"]),(4,12,2))
                self.assertEqual(r["terminal_unobserved_region_openings"],2)

    def test_wrong_priorities_extra_charges_or_unfunded_civil_postings_fail(self):
        for field in ("relief_open_food","relief_close_food","aid_handling_food","aid_received_food",
                      "levy_handling_food","paid","works_used_ore","movement_food","old_public_tools",
                      "relief_received_food","depot_transfer_received_tools","next_depot_open_food"):
            with self.subTest(field=field):
                data=records("move_on")
                data[0][0][field]+=1
                with archive("move_on",data) as path,self.assertRaises(ValueError):
                    check_file(path,7,"move_on",years=2,region_count=2,country_count=2)
        with archive("relief_first",records("move_on")) as path,self.assertRaises(ValueError):
            check_file(path,7,"relief_first",years=2,region_count=2,country_count=2)

    def test_incomplete_duplicated_or_disconnected_years_are_rejected(self):
        for fault in ("row","duplicate","year","extra","terminal","truncated","owner","discontinuous","bool"):
            data=records("move_on")
            if fault=="row": data[1].pop()
            if fault=="duplicate": data[1][1]["region"]=0
            if fault=="year": data[1][1]["year"]=1
            if fault=="extra": data.append(data[1])
            if fault=="terminal": data[1][0]["next_depot_open_food"]=6
            if fault=="truncated": data.pop()
            if fault=="owner": data[1][0]["owner"]=1
            if fault=="discontinuous": data[1][0]["depot_open_ore"]+=1; data[1][0]["depot_close_ore"]+=1
            if fault=="bool": data[1][0]["paid"]=False
            with self.subTest(fault=fault),archive("move_on",data) as path,self.assertRaises(ValueError):
                check_file(path,7,"move_on",years=2,region_count=2,country_count=2)

    def test_worldwide_aid_net_does_not_allow_charging_a_non_dispatching_region(self):
        data=records("move_on")
        data[0][0]["aid_handling_food"]=0
        data[0][1]["aid_handling_food"]=1
        with archive("move_on",data) as path,self.assertRaisesRegex(ValueError,"matching dispatch"):
            check_file(path,7,"move_on",years=2,region_count=2,country_count=2)
