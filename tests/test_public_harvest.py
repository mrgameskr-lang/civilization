"""Allocation of a realized regional harvest between the two actual stores."""

from copy import deepcopy
from types import SimpleNamespace
import unittest

from civsim.model import generate_world
from civsim.public_harvest import apply_public_harvest, harvest_row
from civsim.regional_production import produce_regions
from civsim.regions import regionalize


def goods(food, ore=3, tools=4):
    return {'food': food, 'ore': ore, 'tools': tools}


def crop(workers=32, tiles=2, population=160):
    # Each farmer at the neutral input factors gives 3.2 food before rounding.
    output = workers * 32 // 10
    return {'population': population, 'productivity': 1000, 'technology': 1000, 'fertility': 1000,
            'soil_before': 1000, 'climate': 1000, 'equipment': 1000, 'farmland': tiles,
            'active_farmers': workers, 'active_labor': {'farm': workers}, 'land_capacity': 20 * tiles,
            'investment': {'farm_multiplier': 1000, 'added_land_capacity': 0},
            'produced': goods(output, 0, 0), 'closing_stock': goods(output + 17)}


class PublicHarvestTests(unittest.TestCase):
    def test_gross_minus_private_marginal_keeps_integer_rounding_once(self):
        p = crop()
        row = harvest_row(2, 1, p, goods(0), goods(0))
        self.assertEqual((row['workers_total'], row['workers_private'], row['workers_public']), (32, 28, 4))
        self.assertEqual((row['slots_total'], row['slots_private'], row['slots_public']), (32, 28, 4))
        self.assertEqual((row['food_total'], row['food_private'], row['food_public']), (102, 89, 13))
        self.assertEqual((row['private_before'], row['private_after']), (goods(119), goods(106)))
        self.assertEqual((row['depot_before'], row['depot_after']), (goods(0), goods(13)))
        self.assertEqual(row['rounding_food'], 1)

    def test_opening_trigger_and_current_headroom_are_distinct(self):
        for old, now, workers, public, food in (
            (20, 0, 32, 0, 0), (19, 13, 32, 2, 6), (0, 18, 32, 0, 0),
            (0, 50, 32, 0, 0), (0, 0, 7, 0, 0), (0, 0, 0, 0, 0),
        ):
            with self.subTest(old=old, now=now, workers=workers):
                row = harvest_row(0, 0, crop(workers, tiles=0 if not workers else 2), goods(old), goods(now))
                self.assertEqual((row['workers_public'], row['food_public']), (public, food))
                self.assertEqual(row['food_public'] + row['food_private'], row['food_total'])
        p = crop()
        p['climate'] = 0
        p['produced']['food'] = 0
        self.assertEqual(harvest_row(0, 0, p, goods(0), goods(0))['workers_public'], 0)

    def test_every_receipt_is_validated_before_any_private_or_public_store_changes(self):
        for damage in ('gross', 'capacity', 'private', 'missing_depot'):
            with self.subTest(damage=damage):
                production = {0: crop(), 1: crop()}
                homes = [SimpleNamespace(id=i, owner=2, stock=p['closing_stock'].copy(), population=160)
                         for i, p in production.items()]
                depots = {i: goods(0) for i in production}
                opening = deepcopy(depots)
                if damage == 'gross': production[1]['produced']['food'] -= 1
                elif damage == 'capacity': production[1]['land_capacity'] = 1
                elif damage == 'private': homes[1].stock['food'] += 1
                else: del depots[1]
                before = deepcopy((homes, depots, opening, production))
                with self.assertRaises(ValueError):
                    apply_public_harvest(homes, production, depots, opening)
                self.assertEqual((homes, depots, opening, production), before)

    def test_live_regions_conserve_private_plus_public_stock_cash_labor_and_territory(self):
        world = regionalize(generate_world(0))
        p = produce_regions(world.regions, {n.id: 1000 for n in world.nations})
        immutable_p = deepcopy(p)
        depots = {r.id: goods(0) for r in world.regions}
        opening = deepcopy(depots)
        totals = {r.id: (r.cash, r.population, r.land, r.farmland) for r in world.regions}
        result = apply_public_harvest(world.regions, p, depots, opening)
        self.assertEqual(result['version'], 'public-harvest/1')
        self.assertEqual(len(result['regions']), 32)
        self.assertGreater(sum(row['food_public'] for row in result['regions']), 0)
        for r, row in zip(sorted(world.regions, key=lambda r: r.id), result['regions'], strict=True):
            self.assertEqual((row['id'], row['owner']), (r.id, r.owner))
            self.assertEqual((r.cash, r.population, r.land, r.farmland), totals[r.id])
            self.assertEqual(row['workers_public'] + row['workers_private'], p[r.id]['active_farmers'])
            self.assertEqual(row['slots_public'] + row['slots_private'], p[r.id]['active_farmers'])
            self.assertEqual(row['food_total'], p[r.id]['produced']['food'])
            self.assertEqual(row['food_public'] + row['food_private'], row['food_total'])
            self.assertLessEqual(depots[r.id]['food'], r.population // 8)
            for g in ('food', 'ore', 'tools'):
                self.assertEqual(r.stock[g] + depots[r.id][g], p[r.id]['closing_stock'][g] + opening[r.id][g])
        self.assertEqual((p, opening), (immutable_p, {r.id: goods(0) for r in world.regions}))
