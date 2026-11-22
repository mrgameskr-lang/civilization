import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from experiments.food_yield_factors import analyze_seed, crop_yield, replace_inputs


SEED_ZERO = Path(__file__).resolve().parents[1] / 'examples/food-reserve-v1/study/seed-00-A-regions.jsonl.gz'


def row(year=1, active=10, soil=1000):
    return {'year': year, 'region': 3, 'farm_workers_total': active, 'soil_before': soil,
            'sector_workers': 17, 'land_capacity': 15, 'productivity': 1000, 'technology': 1000,
            'fertility': 1000, 'climate': 1000, 'equipment': 1000, 'farm_multiplier': 1000,
            'harvest_total': 32, 'levied_food': 2, 'taxable_surplus_food': 7,
            'tax_private_before': 17, 'tax_private_after': 15, 'tax_protected_food': 10}


class YieldFactorsTests(unittest.TestCase):
    @unittest.skipUnless(SEED_ZERO.is_file(), 'published seed 0 regional archive is not installed')
    def test_first_three_observed_years_in_published_seed_zero(self):
        results = analyze_seed(SEED_ZERO, 0, checkpoints=(1, 2, 3))
        keys = ('observed_gross_food', 'fixed_year1_soil_gross_food', 'fixed_year1_workers_gross_food')
        self.assertEqual([tuple(row[k] for k in keys) for row in results.values()],
                         [(59836, 59836, 59836), (64406, 64142, 62313), (69251, 68729, 64830)])
        self.assertTrue(all(row['regions'] == 32 and row['levy_beyond_protected_surplus_food'] == 0
                            for row in results.values()))

    def test_single_input_substitutions_keep_current_productivity_and_weather(self):
        base = row()
        current = row(50, 5, 500)
        current.update(climate=1250, productivity=1200, harvest_total=12)
        # Current yield per worker is 2.4. Replacing only soil doubles it.
        self.assertEqual(crop_yield(current, 5, 500), 12)
        with_soil, with_workers, effective = replace_inputs(current, base)
        self.assertEqual((with_soil, with_workers, effective), (24, 24, 10))
        for field in ('land_capacity', 'sector_workers'):
            with self.subTest(field=field):
                constrained = {**current, field: 6}
                self.assertEqual(replace_inputs(constrained, base), (24, 14, 6))

    def test_region_rounding_baseline_identity_tax_boundary_and_production_validation(self):
        first = row(active=1)
        first['harvest_total'] = 3
        later = row(2, 1, 700)
        later.update(harvest_total=2, levied_food=9, tax_private_after=8)
        columns = list(first)

        def write_data(path, bad=None):
            with gzip.open(path, 'wt', encoding='utf-8') as out:
                print(json.dumps({'schema': 'food-flow/1', 'seed': 0, 'arm': 'A', 'columns': columns}), file=out)
                for entry in (first, later):
                    batch = [{**entry, 'region': i} for i in (2, 9)]
                    if entry is later and bad == 'gross': batch[0]['harvest_total'] += 1
                    if entry is later and bad == 'identity': batch[1]['region'] = 7
                    if entry is later and bad == 'unfunded': batch[1]['sector_workers'] = 0
                    if entry is later and bad == 'levy': batch[1]['tax_private_after'] = 0
                    print(json.dumps([[r[c] for c in columns] for r in batch]), file=out)

        with TemporaryDirectory() as folder:
            path = Path(folder) / 'test.gz'
            write_data(path)
            totals = analyze_seed(path, 0, checkpoints=(1, 2), region_count=2)
            self.assertEqual(totals[1]['fixed_year1_soil_minus_observed_food'], 0)
            self.assertEqual(totals[2]['observed_gross_food'], 4)
            self.assertEqual(totals[2]['fixed_year1_soil_gross_food'], 6)
            self.assertEqual(totals[2]['fixed_year1_workers_gross_food'], 4)
            self.assertEqual(totals[2]['observed_minus_year1_gross_food'], -2)
            self.assertEqual(totals[2]['levied_food'], 18)
            self.assertEqual(totals[2]['levy_beyond_protected_surplus_food'], 4)
            for damage in ('gross', 'identity', 'unfunded', 'levy'):
                with self.subTest(damage=damage):
                    write_data(path, damage)
                    with self.assertRaises(ValueError):
                        analyze_seed(path, 0, checkpoints=(1, 2), region_count=2)
