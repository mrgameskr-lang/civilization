import csv
import gzip
import hashlib
from itertools import combinations, product
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from experiments.describe_borders6a import ARMS, EVENTS, FILES, lifetime_bounds, road_bounds, paired_edges, sample


class BorderDiagnosticsTests(unittest.TestCase):
    def test_annual_bounds_match_every_integer_allocation(self):
        for caps in ((2,), (2,3), (1,3,4)):
            feasible={}
            for loads in product(*(range(c+1) for c in caps)):
                feasible.setdefault(sum(loads),[]).append(sum(c==q for c,q in zip(caps,loads)))
            for total, counts in feasible.items():
                self.assertEqual(road_bounds(caps,total),(min(counts),max(counts)))

    def test_cumulative_counts_exclude_early_checkpoint_and_keep_reverse_direction(self):
        def row(year,a,b,owner,qty):
            return dict(seed=0,arm="D",year=year,source_region=a,target_region=b,source_country=owner,
                        target_country=1-owner,distance=1,shared_capacity_per_year=7,trade_food=qty,
                        trade_ore=0,trade_tools=0,aid_dispatched=0,aid_received=0,aid_handling_food=0,
                        aid_freight_food=0)
        rows=[row(1,0,1,0,3),row(1,1,0,1,4),row(2,0,1,0,9),row(2,1,0,1,3)]
        edges,hubs=paired_edges(rows,2)
        e,=edges[0,"D",0,1]
        self.assertEqual((e["cargo"],e["capacity"],e["ab_cargo"],e["ba_cargo"]),(12,7,9,3))
        self.assertFalse(hubs)
        with self.assertRaises(ValueError):
            paired_edges(rows[:-1],2)

    def test_bounds_cannot_turn_a_two_year_average_into_a_count(self):
        self.assertEqual(lifetime_bounds(5,8,2),(0,1))
        self.assertEqual(lifetime_bounds(5,9,2),(1,1))
        self.assertEqual(lifetime_bounds(5,10,2),(2,2))
        with self.assertRaises(ValueError):
            road_bounds((5,4),10)

    def test_pair_panel_and_events_use_correct_exposure_and_direction(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)
            panels=[[] for _ in FILES]
            for arm in ARMS:
                for src,dst,qty in ((0,1,2),(1,0,3)):
                    panels[0].append(dict(seed=0,arm=arm,year=2,source_region=src,target_region=dst,
                        source_country=src,target_country=dst,distance=1,shared_capacity_per_year=5,
                        trade_food=qty,trade_ore=0,trade_tools=0,aid_dispatched=0,aid_received=0,
                        aid_handling_food=0,aid_freight_food=0))
                for year in (1,2):
                    for a,b in combinations(range(8),2):
                        direct=(a,b)==(0,1)
                        p=dict(seed=0,arm=arm,year=year,a=a,b=b,physical_capacity=5 if direct else 0,
                               observations=int(arm!="A"),relation=10 if direct else 0,
                               agreement_years=int(arm in ("C","D") and direct and year==2))
                        for d,q in (("ab_",2),("ba_",3)):
                            p.update({d+k:0 for k in ("trade_food","trade_ore","trade_tools","aid_dispatched")})
                            p[d+"trade_food"]=q if direct and year==1 else 0
                        p.update({"event_"+e:int(direct and arm=="D" and year==1 and e=="pact_rejected") for e in EVENTS})
                        panels[1].append(p)
                panels[3].append(dict(seed=0,arm=arm,year=2,owner=0,aid_exposed_region_years=0))
            panels[2].append(dict(seed=0,arm="D",year=1,a=0,b=1,kind="pact_rejected"))
            hashes={}
            for filename,records in zip(FILES,panels,strict=True):
                with gzip.open(path/filename,"wt",encoding="utf8",newline="") as stream:
                    writer=csv.DictWriter(stream,fieldnames=records[0].keys())
                    writer.writeheader()
                    writer.writerows(records)
                hashes[filename]=hashlib.sha256((path/filename).read_bytes()).hexdigest()
            meta={"sample":"dev","seeds":1,"horizons":[2],"table_sha256":hashes}
            (path/"execution.json").write_text(json.dumps(meta),encoding="utf8")
            result=sample(path)["arms"]
            c=result["D"]["counts"]
            self.assertEqual((c["all_pair_years"],c["adjacent_pair_years"],c["network_full_years"],
                              c["network_full_one_way_years"],c["pact_years_no_trade"]),(56,2,1,0,1))
            self.assertEqual((c["full_road_years_lower"],c["full_road_years_upper"]),(1,1))
            self.assertIsNone(result["A"]["closing_relations"]["adjacent"])
            self.assertEqual(result["D"]["closing_relations"]["nonadjacent"]["zero"],27)
            self.assertEqual(result["D"]["events"]["pact_rejected"],1)
            (path/FILES[0]).write_bytes(b"edited")
            with self.assertRaisesRegex(ValueError,"hash"):
                sample(path)
