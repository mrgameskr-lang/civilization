from copy import deepcopy
import unittest

from civsim.government import start_government, step_government
from civsim.model import generate_world
from civsim.regional_engine import RegionalPolicy, step_regional
from civsim.regions import regionalize
from experiments.turn_civil_balances import paired_civil_delta, turn_civil_balances


def goods(food=0, ore=0, tools=0):
    return {'food': food, 'ore': ore, 'tools': tools}


def example():
    return {
        'year': 3, 'countries': [{'id': 8}],
        'regions': [
            {'id': i, 'owner': 8, 'closing': {'population': pop, 'cash': cash},
             'consumption': {'food_need': need, 'opening_food': eaten, 'food_eaten': eaten,
                             'food_unmet': need-eaten}}
            for i, pop, cash, need, eaten in [(3, 12, 6, 10, 8), (7, 15, 9, 16, 15)]],
        'domestic': {
            'shipments': [{'source': 3, 'target': 7, 'good': 'ore', 'quantity': 4}],
            'nodes': [{'id': 3, 'owner': 8, 'exports': goods(ore=4), 'imports': goods()},
                      {'id': 7, 'owner': 8, 'exports': goods(), 'imports': goods(ore=4)}],
            'delivered': goods(ore=4)},
        'government': {
            'depots': [{'region': 3, 'closing': goods(11, 0, 1)},
                       {'region': 7, 'closing': goods(1, 3, 2)}],
            'roads': [{'a': 3, 'b': 7, 'capacity': 21, 'unused': 10, 'private_use': 4}],
            'relief': {'delivered': 5, 'shipments': [
                {'source': 3, 'target': 3, 'quantity': 3}, {'source': 3, 'target': 7, 'quantity': 2}]}},
    }


class TurnCivilBalanceTests(unittest.TestCase):
    def test_agrees_with_manual_accounts_and_preserves_input(self):
        r = example()
        original = deepcopy(r)
        v = turn_civil_balances(r)
        self.assertEqual(v['world'], {'private_shipments': goods(ore=4), 'food_eaten': 23,
                         'food_unmet': 3, 'government_stock': goods(12, 3, 3), 'road_used': 11,
                         'road_remaining': 10, 'relief_delivered': 5, 'population': 27, 'cash': 15})
        self.assertEqual(v['regions'][3]['road_used'], v['regions'][7]['road_used'])
        self.assertEqual(v['regions'][3]['private_shipments'], goods())
        self.assertEqual(v['regions'][7]['private_shipments'], goods(ore=4))
        self.assertEqual((v['regions'][3]['relief_delivered'], v['regions'][7]['relief_delivered']), (3, 2))
        v['regions'][7]['government_stock']['tools'] = 999
        self.assertEqual(r, original)

    def test_signed_paired_change_and_incompatible_observations(self):
        earlier, later = example(), example()
        later['government']['depots'][1]['closing']['tools'] -= 1
        later['regions'][1]['closing']['cash'] += 5
        later['government']['roads'][0]['unused'] -= 3
        diff = paired_civil_delta(earlier, later)
        self.assertEqual(diff['world']['government_stock'], goods(tools=-1))
        self.assertEqual(diff['world']['road_remaining'], -3)
        self.assertEqual(diff['world']['road_used'], 3)
        self.assertEqual(diff['world']['cash'], 5)
        self.assertEqual(diff['regions'][3]['cash'], 0)
        self.assertEqual(diff['world']['food_eaten'], 0)
        later['year'] += 1
        with self.assertRaises(ValueError):
            paired_civil_delta(earlier, later)

    def test_same_observation_zero_and_region_identity_checked(self):
        record = example()
        difference = paired_civil_delta(record, record)
        for row in (difference['world'], *difference['regions'].values()):
            for name, value in row.items():
                if name != 'owner':
                    self.assertEqual(value, goods() if isinstance(value, dict) else 0)
        reassigned = deepcopy(record)
        reassigned['countries'][0]['id'] = 9
        for entry in reassigned['regions'] + reassigned['domestic']['nodes']:
            entry['owner'] = 9
        with self.assertRaisesRegex(ValueError, 'ownership'):
            paired_civil_delta(record, reassigned)

    def test_bad_depot_road_and_relief_data_fail(self):
        for source in ('depot', 'relief', 'road', 'unmet'):
            with self.subTest(source=source):
                r = example()
                if source == 'depot':
                    r['government']['depots'].pop()
                elif source == 'relief':
                    r['government']['relief']['delivered'] += 1
                elif source == 'road':
                    r['government']['roads'][0]['unused'] = 50
                else:
                    r['regions'][0]['consumption']['food_unmet'] += 1
                with self.assertRaises(ValueError):
                    turn_civil_balances(r)

    def test_real_fiscal_record_and_older_record_without_fiscal_accounts(self):
        sim = start_government(regionalize(generate_world(0)))
        real = step_government(sim, 1, 'integrated')
        v = turn_civil_balances(real)['world']
        self.assertEqual(v['cash'], sum(n['closing']['cash'] for n in real['countries']))
        self.assertEqual(v['population'], sum(n['closing']['population'] for n in real['countries']))
        fiscal_stock = {g: sum(d['closing'][g] for d in real['government']['depots']) for g in goods()}
        self.assertEqual(v['government_stock'], fiscal_stock)
        old = step_regional(regionalize(generate_world(0)), 1, RegionalPolicy(logistics='unlimited'))
        v = turn_civil_balances(old)['world']
        self.assertIsNone(v['government_stock'])
        self.assertIsNone(v['relief_delivered'])
        self.assertIsNone(v['road_remaining'])
        self.assertEqual(v['road_used'], sum(r['used'] for r in old['domestic']['roads']))
