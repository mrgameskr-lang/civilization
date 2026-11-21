from copy import deepcopy
import unittest

from experiments.food_assessment import COLUMNS, food_assessment


def receipt(private=120, floor=20, public=7, cap=40, assessed=0, cut=0, refused=0,
            extra=0, fee=0):
    gross = assessed-cut-refused
    net = gross-fee
    values = dict(private_open=private, protected=floor, depot_open=public, reserve_cap=cap,
                  baseline_levy=assessed, foregone_concession=cut, refused=refused, levied=gross,
                  handling_used=fee, deposited=net, private_close=private-gross, depot_close=public+net,
                  standing_levy=gross-extra, extra_levy=extra)
    return {k: {'food': v} for k, v in values.items()}


class FoodAssessmentTests(unittest.TestCase):
    def test_positive_and_unchanged(self):
        data = receipt(assessed=15, cut=3, refused=4, extra=3, fee=1)
        old = deepcopy(data)
        row = food_assessment(data)
        self.assertEqual(row, [120, 20, 7, 40, 15, 3, 4, 8, 1, 7, 'positive_net'])
        self.assertEqual(len(COLUMNS), len(row))
        self.assertEqual(data, old)

    def test_zero_receipts_and_overlapping_limits(self):
        for source, reason in [
            (receipt(private=20), 'no_taxable_surplus'),
            (receipt(private=12, public=42), 'no_taxable_surplus'),
            (receipt(public=40), 'warehouse_full'),
            (receipt(public=41), 'warehouse_full'),
            (receipt(private=21), 'below_integer_levy_or_other_nonassessment'),
            (receipt(assessed=4, cut=1, refused=3), 'concession_or_refusal'),
            (receipt(assessed=4, refused=3, extra=1, fee=1), 'handling'),
        ]:
            with self.subTest(reason=reason):
                self.assertEqual(food_assessment(source)[-1], reason)

    def test_rejects_inconsistent_food_balances_and_impossible_assessments(self):
        for key in ('baseline_levy', 'foregone_concession', 'refused', 'levied', 'handling_used',
                    'deposited', 'private_close', 'depot_close', 'standing_levy'):
            with self.subTest(key=key):
                source = receipt(assessed=4)
                source[key]['food'] += 1
                with self.assertRaises(ValueError):
                    food_assessment(source)
        for source in [receipt(private=21, assessed=2), receipt(public=39, assessed=2),
                       receipt(private=False), receipt(public=-1)]:
            with self.assertRaises(ValueError):
                food_assessment(source)
