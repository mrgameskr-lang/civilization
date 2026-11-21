import csv
import gzip
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from experiments.depot_effects62 import congestion, reason_counts, summarize, summarize_fork
from experiments.phase6b import run_study


def archive(path, header, records):
    with gzip.open(path,'wt',encoding='utf8',newline='') as f:
        w=csv.writer(f)
        w.writerow(header.split())
        w.writerows(records)


class DepotEffectsTests(unittest.TestCase):
    def test_shortfalls_count_exact_combinations_and_track_approval_changes(self):
        with TemporaryDirectory() as temp:
            p=Path(temp,'foreign.gz')
            archive(p,'seed arm year source target authorized sent received unshipped shortfall_reasons',
                    [(0,'A',1,1,2,10,3,2,7,'stock'),(0,'A',2,2,1,4,0,0,4,'road|stock'),
                     (0,'B',1,1,2,0,0,0,0,''),(0,'B',2,2,1,4,3,2,1,'minimum_lot')])
            reasons,matched=reason_counts(p,(1,2))
            self.assertEqual(sum(r['units'] for r in reasons[2]['A'].values()),11)
            self.assertEqual(matched[1]['B_fewer_unshipped'],1)
            self.assertEqual(matched[1]['B_more_sent'],0)
            self.assertEqual(matched[1]['B_no_authorization'],1)

    def test_edge_excess_does_not_imply_world_excess(self):
        with TemporaryDirectory() as temp:
            p=Path(temp,'roads.gz')
            archive(p,'seed arm year owner a b private_use supply_use',[
                (0,'A',1,0,0,1,9,0),(0,'A',1,1,2,3,3,0),(0,'B',1,0,0,1,4,2),(0,'B',1,1,2,3,3,8)])
            res=congestion(p,(1,))[1]
            self.assertEqual(res['counts']['road_year']['drop_exceeds_new_public'],1)
            self.assertEqual(res['largest']['country_year']['excess'],3)
            self.assertEqual(res['counts']['world_year']['drop_exceeds_new_public'],0)

    def test_accounts_in_actual_generated_three_year_panel(self):
        with TemporaryDirectory() as temp:
            study=Path(temp,'study')
            run_study(study,sample='dev',seeds=1,horizons=(1,3),workers=1)
            data=summarize(study)['checkpoints']['3']
            self.assertEqual(data['A']['depot_edge_cargo'],0)
            self.assertGreater(data['B']['depot_edge_cargo'],0)
            self.assertEqual(sum(r['regions'] for r in data['regions_by_B_aid_receipt'].values()),32)
            self.assertEqual(data['paired_road_congestion']['counts']['world_year']['observations'],3)
            with (study/'runs.csv').open('ab') as f: f.write(b'\n')
            with self.assertRaisesRegex(ValueError,'digest'): summarize(study)

    def test_natural_single_year_intervention_on_an_actual_route(self):
        r=summarize_fork(1,5)
        e=next(x for x in r['roads'] if tuple(x['edge'])==(0,2))
        self.assertEqual((e['public'],e['private_on'],e['private_held']),(8,268,282))
        self.assertEqual((r['delta']['food_eaten'],r['delta']['food_need']),(-64,0))
        self.assertEqual(sum(x['eaten_on']-x['eaten_held'] for x in r['regions']),-64)
