from copy import deepcopy
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from experiments.food_trajectory import FIELDS, _arm, _pairs, _read, _seed, reserve_window, sustained_turns


class FoodTrajectoryTests(unittest.TestCase):
    def test_persistent_onset_recovery_and_censoring(self):
        flags = [False]*2 + [True]*4 + [False] + [True]*5 + [False]*3 + [True] + [False]*5 + [True]*5
        self.assertEqual(sustained_turns(flags), [
            {'state': True, 'first_year': 8, 'confirmed_year': 12},
            {'state': False, 'first_year': 17, 'confirmed_year': 21},
            {'state': True, 'first_year': 22, 'confirmed_year': 26},
        ])
        self.assertEqual(sustained_turns([True]*3 + [None] + [True]*4), [])

    def test_reserve_floor_and_pooled_days(self):
        records = [{'public_open': 0, 'public_close': 2, 'food_need': 365},
                   {'public_open': 2, 'public_close': 1, 'food_need': 730},
                   {'public_open': 1, 'public_close': 3, 'food_need': 365}]
        before = deepcopy(records)
        result = reserve_window(records)
        self.assertEqual(result['positive_years'], 3)
        self.assertEqual(result['one_day_years'], 2)
        self.assertEqual(result['minimum_days'], 0.5)
        self.assertEqual(result['pooled_days'], 1.5)
        self.assertFalse(result['maintained_one_day'])
        self.assertEqual(result['net_stock_change'], 3)
        self.assertEqual(records, before)

    def test_no_demand_is_unmeasured_and_drawing_down_is_distinct(self):
        empty = reserve_window([{'public_open': 0, 'public_close': 0, 'food_need': 0}])
        self.assertIsNone(empty['pooled_days'])
        self.assertIsNone(empty['maintained_one_day'])
        drawn = reserve_window([{'public_open': 3, 'public_close': 1, 'food_need': 365}])
        self.assertTrue(drawn['maintained_one_day'])
        self.assertFalse(drawn['maintained_without_net_drawdown'])

    def test_real_file_format_country_sums_pairing_and_late_count(self):
        def write(path, delta, tamper=False):
            with gzip.open(path, 'wt', encoding='utf8') as stream:
                for y in range(1,201):
                    local = []
                    for owner in range(8):
                        r = dict.fromkeys(FIELDS, 0)
                        deficit = delta if owner == 0 and y >= 151 else 0
                        r.update(owner=owner, food_need=365, food_eaten=365-deficit, food_unmet=deficit,
                                 harvest_private=364, harvest_public=1, harvest_total=365, public_close=int(y>100),
                                 public_open=int(y>101), closing_population=365, region_count=4,
                                 private_harvest_regions=4, private_harvest_no_surplus_regions=3,
                                 no_taxable_surplus_regions=3)
                        local.append(r)
                    world = {k: sum(r[k] for r in local) for k in FIELDS}
                    if tamper and y == 5:
                        world['food_eaten'] += 1
                    stream.write(json.dumps({'year': y, 'world': world, 'countries': local})+'\n')
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / 'annual.jsonl.gz'
            source = {}
            for name, deficit in [('C', 1), ('B', 0)]:
                write(p, deficit)
                world, countries, _ = _read(p)
                source[0, name] = _seed(world, countries)
            arm = _arm(source, [0], 'C')
            self.assertEqual(arm['late_151_200']['countries']['maintained_one_day_windows'], 8)
            self.assertEqual(arm['turning_points']['zero_public_food']['turns_confirmed_after_50_by_seed'], {0: [-101]})
            self.assertEqual(arm['checkpoints'][100]['cumulative']['pooled_ratios']['no_surplus_among_private_harvesting_regions'], .75)
            pair = _pairs(source, [0], 'B')
            self.assertEqual(pair['checkpoints'][200]['deltas']['cumulative_food_unmet']['mean'], 50)
            self.assertEqual(pair['checkpoints'][200]['unmet_share_examples']['largest_increase']['seed'], 0)
            self.assertIsNone(pair['checkpoints'][200]['unmet_share_examples']['first_tie'])
            self.assertEqual(pair['country_unmet_share_151_200']['tied'], 7)
            self.assertEqual(pair['country_examples_151_200']['largest_increase']['owner'], 0)
            write(p, 0, tamper=True)
            with self.assertRaisesRegex(ValueError, 'do not reconcile'):
                _read(p)
