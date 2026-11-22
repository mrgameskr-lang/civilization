import unittest

from civsim.model import generate_world
from civsim.regional_production import produce_regions
from civsim.regions import regionalize
from experiments.crop_practices import regional_practices
from experiments.food_yield_factors import crop_yield


def crop(active=10, tiles=2, capacity=40, **changes):
    need = (active + 29) // 30
    row = dict(farm_workers_total=active, farm_workers_planned=active, farmland=tiles, land_capacity=capacity,
               mine_workers=3, factory_workers=1, sector_workers=active + 4, tools_needed=need,
               farm_tools_used=need, productivity=1000, technology=1000, fertility=1000,
               climate=1000, equipment=1150, farm_multiplier=1000, soil_before=1000)
    row.update(changes)
    row.setdefault('soil_after', max(550, min(1150, row['soil_before'] + 6 - 8 * active // max(1, capacity))))
    row['harvest_total'] = crop_yield(row, active, row['soil_before'])
    return row


class CropPracticesTests(unittest.TestCase):
    def test_additional_crop_worker_requires_an_existing_factory_worker_and_field_slot(self):
        for row, labor, benefit in ((crop(), 1, 4), (crop(30), 1, -4),
                                    (crop(40, farm_workers_planned=45), 0, 0),
                                    (crop(factory_workers=0, sector_workers=13), 0, 0)):
            with self.subTest(row=row):
                before = row.copy()
                out = regional_practices(row, row, None)
                self.assertEqual((out['option_factory_worker_years'], out['option_food_change']), (labor, benefit))
                self.assertEqual(out['option_additional_tools'], 0)
                self.assertEqual(row, before)

    def test_measured_soil_gain_implies_paid_packages_and_pre_harvest_public_cost(self):
        current = crop(16, tiles=16, capacity=320, soil_before=900, soil_after=910)
        out = regional_practices(current, current, 882)
        self.assertEqual(out['local_soil_packages'], 1)
        self.assertEqual((out['local_soil_ore'], out['local_soil_tools'], out['local_soil_workers']), (1, 1, 4))
        self.assertEqual((out['public_soil_packages'], out['public_soil_ore'], out['public_soil_tools'],
                          out['public_soil_workers']), (1, 2, 2, 4))
        for field, value in (('soil_after', 909), ('farm_tools_used', 0), ('harvest_total', 900)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                regional_practices({**current, field: value}, current, 882)

    def test_funded_farm_equipment_and_occupied_reclaimed_slots(self):
        row = crop(22, tiles=1, capacity=24, farm_multiplier=1024)
        stats = regional_practices(row, {**row, 'technology': 990}, None)
        self.assertEqual(stats['operated_farm_assets'], 2)
        self.assertEqual(stats['farm_asset_upkeep_tools'], 2)
        self.assertEqual(stats['occupied_improved_slots'], 2)
        self.assertEqual(stats['technology_changed_region_years'], 1)
        self.assertGreater(stats['observed_food_minus_no_improved_slots'], 0)

    def test_reconstructed_practice_costs_match_actual_regional_accounts(self):
        world = regionalize(generate_world(3))
        for region in world.regions:
            region.soil = 880
            region.stock.update(ore=240, tools=240)
            region.capital['farm'][0] = 1
        produced = produce_regions(world.regions, {n.id: 1000 for n in world.nations})
        care_total = 0
        for p in produced.values():
            obs = {**p, 'farm_workers_total': p['active_farmers'], 'farm_workers_planned': p['labor_before']['farm'],
                   'sector_workers': p['workers'], 'mine_workers': p['labor']['mine'],
                   'factory_workers': p['labor']['factory'], 'farm_tools_used': p['investment']['sector_used']['tools'],
                   'tools_needed': p['tool_need'], 'farm_multiplier': p['investment']['farm_multiplier'],
                   'harvest_total': p['produced']['food']}
            out = regional_practices(obs, obs, None)
            care = p['soil_care']
            self.assertEqual((out['local_soil_ore'], out['local_soil_tools'], out['local_soil_workers']),
                             (care['used']['ore'], care['used']['tools'], care['workers']))
            self.assertEqual(out['farm_asset_upkeep_tools'], p['investment']['upkeep_used']['tools'])
            care_total += out['local_soil_packages']
        self.assertGreater(care_total, 0)
