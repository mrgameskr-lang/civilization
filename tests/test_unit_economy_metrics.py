"""Read settled civilian freight and meals at their actual final destinations."""

from copy import deepcopy
import unittest

from civsim.model import generate_world
from civsim.regional_engine import step_regional
from civsim.regions import regionalize
from experiments.unit_economy_metrics import civil_totals


def goods(food=0, ore=0, tools=0):
    return {'food': food, 'ore': ore, 'tools': tools}


def settled():
    # Region 1 is a transit point. Freight provisions and spoiled food are distinct.
    residents = [(0, 5, 6, 20), (1, 5, 8, 8), (2, 5, 15, 10), (3, 7, 4, 2)]
    regions = [{'id': i, 'owner': owner, 'consumption': {
        'food_need': need, 'opening_food': stock, 'food_eaten': min(need, stock),
        'used': goods(min(need, stock) + max(0, stock - need) // 12),
    }} for i, owner, need, stock in residents]
    domestic = {'nodes': [
        {'id': 0, 'owner': 5, 'exports': goods(9), 'imports': goods(tools=3)},
        {'id': 1, 'owner': 5, 'exports': goods(), 'imports': goods(), 'transit': goods(9)},
        {'id': 2, 'owner': 5, 'exports': goods(tools=3), 'imports': goods(9)},
        {'id': 3, 'owner': 7, 'exports': goods(), 'imports': goods()},
    ], 'shipments': [
        {'source': 0, 'target': 2, 'good': 'food', 'quantity': 9, 'path': [0, 1, 2], 'cost_food': 2},
        {'source': 2, 'target': 0, 'good': 'tools', 'quantity': 3, 'path': [2, 0], 'cost_food': 1},
    ], 'delivered': goods(9, tools=3)}
    return {'year': 1, 'countries': [{'id': 5}, {'id': 7}], 'regions': regions,
            'domestic': domestic, 'government': {'relief': {'delivered': 50}},
            'border_market': {'trades': [{'good': 'food', 'quantity': 77}]}}


class CivilTotalsTests(unittest.TestCase):
    def test_endpoints_once_and_personal_meals_after_freight_and_spoilage(self):
        raw = settled()
        before = deepcopy(raw)
        result = civil_totals(raw)
        self.assertEqual(result['regions'][0], {'owner': 5, 'food_eaten': 6,
                         'sent': goods(9), 'received': goods(tools=3)})
        self.assertEqual(result['regions'][1], {'owner': 5, 'food_eaten': 8,
                         'sent': goods(), 'received': goods()})
        self.assertEqual(result['countries'][5], {'sent': goods(9, tools=3),
                         'received': goods(9, tools=3), 'food_eaten': 24})
        self.assertEqual(result['countries'][7], {'sent': goods(), 'received': goods(), 'food_eaten': 2})
        self.assertEqual(result['world'], {'sent': goods(9, tools=3),
                         'received': goods(9, tools=3), 'food_eaten': 26})
        self.assertEqual(result['year'], 1)
        result['regions'][0]['sent']['food'] = 999
        self.assertEqual(raw, before)
        self.assertEqual(result['world']['sent']['food'], 9)

    def test_rejects_cross_border_stale_or_inconsistent_receipts(self):
        for edit in ('foreign', 'node', 'delivered', 'missing_node', 'meal', 'duplicate', 'negative', 'bool'):
            with self.subTest(edit=edit):
                raw = settled()
                if edit == 'foreign':
                    raw['domestic']['shipments'][0]['target'] = 3
                elif edit == 'node':
                    raw['domestic']['nodes'][0]['exports']['food'] += 1
                elif edit == 'delivered':
                    raw['domestic']['delivered']['ore'] = 3
                elif edit == 'missing_node':
                    raw['domestic']['nodes'].pop()
                elif edit == 'meal':
                    raw['regions'][0]['consumption']['food_eaten'] += 1
                elif edit == 'duplicate':
                    raw['regions'].append(raw['regions'][0])
                elif edit == 'negative':
                    raw['domestic']['shipments'][1]['quantity'] = -1
                else:
                    raw['domestic']['shipments'][0]['source'] = False
                with self.assertRaises(ValueError):
                    civil_totals(raw)

    def test_normal_year_with_unchanged_source_and_all_country_totals(self):
        raw = step_regional(regionalize(generate_world(4)), 1)
        before = deepcopy(raw)
        totals = civil_totals(raw)
        self.assertEqual(raw, before)
        self.assertEqual(len(totals['regions']), 32)
        self.assertEqual(len(totals['countries']), 8)
        for nation in raw['countries']:
            owner = nation['id']
            nodes = [n for n in raw['domestic']['nodes'] if n['owner'] == owner]
            self.assertEqual(totals['countries'][owner]['received'],
                             {g: sum(n['imports'][g] for n in nodes) for g in goods()})
        self.assertEqual(totals['world']['food_eaten'], sum(
            r['consumption']['used']['food'] - r['consumption']['food_spoiled'] for r in raw['regions']))
