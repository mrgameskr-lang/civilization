from copy import deepcopy
from hashlib import sha256
import unittest

from civsim.model import climate_factor, generate_world
from civsim.public_harvest import apply_public_harvest, harvest_row, harvest_version
from civsim.regional_production import produce_regions
from civsim.regions import regionalize
from civsim.storage import canonical_line
from tests.test_public_harvest import crop, goods


class ReserveTargetTests(unittest.TestCase):
    def test_seven_and_fourteen_day_targets_use_their_own_integer_headroom(self):
        for days, target, workers, food in ((7, 3, 1, 3), (14, 6, 2, 6)):
            with self.subTest(days=days):
                r = harvest_row(9, 2, crop(), goods(0), goods(0), reserve_days=days)
                self.assertEqual((r['reserve_days'], r['reserve_target'], r['workers_public'], r['food_public']),
                                 (days, target, workers, food))
                self.assertEqual(r['food_private'] + food, r['food_total'])
                self.assertEqual(r['private_before']['food'] - r['private_after']['food'], food)
                self.assertEqual(r['depot_after']['food'] - r['depot_before']['food'], food)
                no_room = harvest_row(9, 2, crop(), goods(0), goods(target - 2), reserve_days=days)
                self.assertEqual((no_room['workers_public'], no_room['food_public']), (0, 0))
                closed = harvest_row(9, 2, crop(), goods(target), goods(0), reserve_days=days)
                self.assertEqual((closed['workers_public'], closed['food_public']), (0, 0))
                for people, expected in ((0, 0), (1, 0), (364, days - 1), (365, days)):
                    row = harvest_row(9, 2, crop(population=people), goods(0), goods(0), reserve_days=days)
                    self.assertEqual(row['reserve_target'], expected)
                    self.assertLessEqual(row['depot_after']['food'], min(row['storage_limit'], expected))

    def test_invalid_days_rejected_even_for_empty_batch(self):
        for days in (True, False, '7', 7.0, 14.0, 0, -1, 1, 8, 15):
            with self.subTest(days=days):
                with self.assertRaises(ValueError): harvest_version(days)
                with self.assertRaises(ValueError): harvest_row(0, 0, crop(), goods(0), goods(0), reserve_days=days)
                with self.assertRaises(ValueError): apply_public_harvest([], {}, {}, {}, reserve_days=days)

    def test_default_receipt_matches_hash_from_before_the_change(self):
        world = regionalize(generate_world(0))
        prod = produce_regions(world.regions, {n.id: climate_factor(0, 1, n.id) for n in world.nations})
        warehouses = {r.id: goods(4, 2, 3) for r in world.regions}
        default = apply_public_harvest(deepcopy(world.regions), prod, deepcopy(warehouses), warehouses)
        self.assertEqual(sha256(canonical_line(default)).hexdigest(),
                         'e52a3cdbfa59929694cbf8e948be2dd1ec0d6d7d34d22b100de98b11b7f9c478')
        for days in (None, 7, 14):
            entries = apply_public_harvest(deepcopy(world.regions), prod, deepcopy(warehouses), warehouses,
                                           reserve_days=days)
            self.assertEqual(entries['version'], harvest_version(days))
            if days is None:
                self.assertEqual(entries, default)
            else:
                self.assertEqual(entries['version'], f'public-harvest/2-d{days}')
                self.assertTrue(all(row['reserve_days'] == days for row in entries['regions']))
