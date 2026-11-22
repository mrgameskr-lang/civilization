"""Purchases of complete, identical two-item sets."""

from concurrent.futures import ThreadPoolExecutor
import unittest

from civsim.inventory_sets import take_sets


class InventorySetsTests(unittest.TestCase):
    def test_only_complete_sets_are_charged(self):
        for food, tools, request, bought in (
            (4, 7, 2, 2), (4, 7, 1, 1), (4, 7, 0, 0), (4, 1, 2, 1),
            (1, 4, 2, 1), (0, 4, 2, 0), (4, 0, 2, 0),
        ):
            with self.subTest(food=food, tools=tools, request=request):
                stock = {'food': food, 'ore': 13, 'tools': tools, 'paint': 5}
                self.assertEqual(take_sets(stock, request), bought)
                self.assertEqual(stock, {'food': food - bought, 'tools': tools - bought,
                                         'ore': 13, 'paint': 5})

    def test_invalid_requests_balances_and_missing_items_are_atomic(self):
        cases = [({'food': 5, 'tools': 7}, request) for request in (-1, 3, True, 1.0, '2')]
        for field in ('food', 'tools'):
            for bad in (-1, True, 1.5, None):
                cases.append(({'food': 5, 'tools': 7, field: bad}, 2))
            cases.append(({g: 5 for g in ('food', 'tools') if g != field}, 0))
        for stock, request in cases:
            with self.subTest(stock=stock, request=request):
                before = stock.copy()
                with self.assertRaises(ValueError):
                    take_sets(stock, request)
                self.assertEqual(stock, before)

    def test_concurrent_purchases_do_not_overdraw_a_shared_inventory(self):
        stock = {'food': 83, 'tools': 67, 'ore': 11}
        with ThreadPoolExecutor(max_workers=8) as pool:
            bought = list(pool.map(lambda _: take_sets(stock, 2), range(80)))
        self.assertEqual(sum(bought), 67)
        self.assertEqual(stock, {'food': 16, 'tools': 0, 'ore': 11})
