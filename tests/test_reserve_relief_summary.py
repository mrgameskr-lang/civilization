from fractions import Fraction
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from experiments.reserve_relief_summary import _read, civilian_row, FLOWS, STOCKS, paired_measure, reserve_windows


class ReserveReliefSummaryTests(unittest.TestCase):
    def test_persistent_reserve_needs_every_year_and_drawdown_uses_first_opening(self):
        rows = [{'food_need': 365, 'food_unmet': 1, 'public_open': 10, 'public_close': 7} for _ in range(50)]
        out = reserve_windows([rows])
        self.assertEqual(out['net_drawdown_windows'], 1)
        self.assertEqual(out['thresholds']['7']['maintained_windows'], 1)
        self.assertEqual(out['thresholds']['7']['maintained_without_net_drawdown'], 0)
        self.assertEqual(out['thresholds']['7']['years_with_shortage_and_coverage'], 50)
        rows[8]['public_close'] = 6
        self.assertEqual(reserve_windows([rows])['thresholds']['7']['maintained_windows'], 0)
        rows[7]['food_need'] = 0
        out = reserve_windows([rows])
        self.assertEqual(out['positive_demand_years'], 49)
        self.assertEqual(out['unclassified_windows'], 1)

    def test_paired_ratio_comparisons_use_exact_per_seed_denominators(self):
        pairs = [({'seed': 1}, Fraction(2, 200), Fraction(2, 100)),
                 ({'seed': 2}, Fraction(50, 100), Fraction(1, 2)),
                 ({'seed': 3}, Fraction(6, 80), Fraction(1, 20)),
                 ({'seed': 4}, None, Fraction(0, 1))]
        m = paired_measure(pairs, cases=True)
        self.assertEqual((m['decreased'], m['tied'], m['increased'], m['undefined']), (1, 1, 1, 1))
        self.assertAlmostEqual(m['mean_delta'], 0.005)
        self.assertEqual(m['examples']['largest_decrease']['seed'], 1)
        self.assertEqual(m['examples']['largest_increase']['seed'], 3)
        self.assertEqual(m['examples']['first_tie']['seed'], 2)

    def test_shortage_partition_and_request_reasons_are_separate_accounts(self):
        row = dict.fromkeys((*FLOWS, *STOCKS), 0)
        row.update(food_need=14, food_eaten=10, food_unmet=4, unmet_with_other_domestic_stock_only=4,
                   unmet_without_ordinary_approval=4, emergency_requested=9, emergency_approved=6,
                   emergency_unfilled_handling=3, emergency_unfilled_stock=5, emergency_received_food=1,
                   emergency_sent_food=1, emergency_dispatched_for_target=1)
        self.assertEqual(civilian_row(row)['food_unmet'], 4)
        for field in ('unmet_with_local_stock', 'ordinary_gap_admin', 'emergency_unfilled_road', 'food_eaten'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                civilian_row({**row, field: 1 + row[field]})

    def test_country_totals_and_cross_year_custody_checked_before_accumulation(self):
        base = dict.fromkeys((*FLOWS, *STOCKS), 0)
        base.update(food_need=3, food_eaten=3, closing_population=3, harvest_private=3, harvest_total=3,
                    public_open=2, public_close=2)
        with TemporaryDirectory() as folder:
            path = Path(folder)/'small.gz'
            for corrupt in (False, True):
                with gzip.open(path, 'wt', encoding='utf-8') as out:
                    for year in range(1, 201):
                        rows = [dict(owner=i, **base) for i in range(8)]
                        if corrupt and year == 2:
                            rows[0]['public_open'] += 1
                        world = {k: sum(row[k] for row in rows) for k in base}
                        out.write(json.dumps({'year':year,'countries':rows,'world':world})+'\n')
                if corrupt:
                    with self.assertRaisesRegex(ValueError, 'discontinuous'):
                        _read(path)
                else:
                    run, _ = _read(path)
                    self.assertEqual(run['checkpoints'][50]['annual']['public_close'], 16)
                    self.assertEqual(run['checkpoints'][50]['cumulative']['food_eaten'], 1200)
                    self.assertNotIn('public_close', run['checkpoints'][50]['cumulative'])
                    self.assertEqual(run['late']['food_eaten'], 1200)
