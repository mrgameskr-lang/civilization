"""Normal entry points, economic custody and the optional civic harvest save format."""

from contextlib import redirect_stdout
from copy import deepcopy
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from civsim import annual_game
from civsim.game_journal import append_turn, new_journal
from civsim.public_harvest import harvest_row
from civsim.storage import canonical_line
from civsim.unit_economy import audit_game, step_game


def cli(*args):
    output = StringIO()
    with redirect_stdout(output):
        annual_game.main(list(map(str, args)))
    return json.loads(output.getvalue())


class PublicFarmGameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        game = annual_game.create(0)
        cls.geography = deepcopy(game.economy.world)
        cls.prior = step_game(game)
        cls.record = step_game(game, public_farm=True)

    def test_gross_crops_and_two_recipient_accounts_balance_before_border_and_levy(self):
        record = self.record
        audit_game(record, self.geography, previous=self.prior)
        regions = {r['id']: r for r in record['regions']}
        levies = {r['region']: r for r in record['government']['levies']}
        rows = record['public_harvest']['regions']
        balances = {h['id']: h['private_after'].copy() for h in rows}
        for trade in record['border_market']['trades']:
            balances[trade['seller']][trade['good']] -= trade['quantity']
            balances[trade['buyer']][trade['good']] += trade['quantity']
            balances[trade['seller']]['food'] -= trade['cost_food']
        self.assertEqual(set(balances), set(regions))
        self.assertGreater(sum(h['food_public'] for h in rows), 0)
        for h in rows:
            i = h['id']
            p = regions[i]['production']
            self.assertEqual((h['private_before'], h['food_total']), (p['closing_stock'], p['produced']['food']))
            self.assertEqual(h['food_private'] + h['food_public'], h['food_total'])
            self.assertEqual(h['workers_public'] + h['workers_private'], p['active_farmers'])
            self.assertEqual(h['slots_public'] + h['slots_private'], p['active_farmers'])
            self.assertEqual(h['private_before']['food'] - h['private_after']['food'], h['food_public'])
            self.assertEqual(h['depot_after']['food'] - h['depot_before']['food'], h['food_public'])
            self.assertEqual(balances[i], levies[i]['private_open'])

    def test_rejects_changes_to_fiscal_crop_labor_land_store_cash_and_population(self):
        paths = (
            ('public_harvest', 'regions', 0, 'food_public'),
            ('public_harvest', 'regions', 0, 'workers_public'),
            ('public_harvest', 'regions', 0, 'slots_private'),
            ('public_harvest', 'regions', 0, 'depot_after', 'food'),
            ('government', 'levies', 0, 'levied', 'food'),
            ('government', 'depots', 0, 'closing', 'food'),
            ('government', 'accounts', 0, 'combined_close', 'food'),
            ('regions', 0, 'closing', 'stock', 'food'),
            ('regions', 0, 'closing', 'cash'),
            ('regions', 0, 'closing', 'population'),
        )
        for path in paths:
            with self.subTest(field=path):
                forged = deepcopy(self.record)
                node = forged
                for key in path[:-1]:
                    node = node[key]
                node[path[-1]] += 1
                with self.assertRaises(ValueError):
                    audit_game(forged, self.geography, previous=self.prior)

    def test_archive_audit_rejects_boolean_substituted_for_integer_rounding(self):
        forged = deepcopy(self.record)
        row = forged['public_harvest']['regions'][0]
        row['rounding_food'] = bool(row['rounding_food'])
        with self.assertRaises(ValueError):
            audit_game(forged, self.geography, previous=self.prior)

    def test_recomputed_receipt_cannot_legitimize_forged_underlying_production(self):
        for damage in ('closing_store', 'farmland', 'production_factors'):
            with self.subTest(damage=damage):
                forged = deepcopy(self.record)
                region = forged['regions'][0]
                i, owner = region['id'], region['owner']
                production = region['production']
                if damage == 'closing_store':
                    production['closing_stock']['food'] += 10000
                elif damage == 'farmland':
                    production['farmland'] += 1
                    production['land_capacity'] += 20
                else:
                    self.assertNotEqual(production['productivity'], production['technology'])
                    production['productivity'], production['technology'] = (
                        production['technology'], production['productivity'])
                crops = forged['public_harvest']['regions']
                index = next(j for j, r in enumerate(crops) if r['id'] == i)
                opening = next(d['opening'] for d in forged['government']['depots'] if d['region'] == i)
                crops[index] = harvest_row(i, owner, production, opening, crops[index]['depot_before'])
                with self.assertRaises(ValueError):
                    audit_game(forged, self.geography, previous=self.prior)

    def test_stays_active_after_cli_replay_and_detects_a_missing_or_forged_flag(self):
        with TemporaryDirectory() as root:
            paths = [Path(root) / f'{i}.json' for i in range(4)]
            cli('new', '--seed', 0, '--out', paths[0])
            cli('step', paths[0], '--out', paths[1])
            before = paths[1].read_bytes()
            results = cli('step', paths[1], '--public-farm', '--out', paths[2])
            self.assertEqual(results['public_harvest']['version'], 'public-harvest/1')
            self.assertEqual(paths[1].read_bytes(), before)
            continued = cli('step', paths[2], '--out', paths[3])
            self.assertEqual(continued['public_harvest']['version'], 'public-harvest/1')
            self.assertTrue(cli('show', paths[3])['public_farm'])
            journal, restored = annual_game.load(paths[3])
            self.assertTrue(restored.economy.public_farm)
            with self.assertRaises(ValueError):
                step_game(restored, public_farm=False)
            self.assertEqual(restored.economy.world.year, 3)
            self.assertEqual(len(journal['turns']), 3)
            for removed in ('flag', 'journal'):
                slot = json.loads(paths[3].read_bytes())
                if removed == 'flag':
                    del slot['public_farm']
                    slot['schema'] = 'annual-game/1'
                else:
                    slot['journal']['turns'][1]['command'] = None
                edited = Path(root) / 'tampered.json'
                edited.write_text(json.dumps(slot), encoding='utf-8')
                with self.subTest(removed=removed), self.assertRaises(ValueError):
                    annual_game.load(edited)

    def test_legacy_optional_save_metadata_round_trips_as_an_opaque_value(self):
        # Exercise only the conditional JSON envelope; the farm does not interpret this field.
        game = annual_game.create(1)
        command = {'public_farm': True, 'move': None}
        record = annual_game.play(game, command)
        journal = append_turn(new_journal(1), command, record)
        with TemporaryDirectory() as root:
            for name, legacy in [('absent', None), ('present', {'opaque': [1, 2, 0]})]:
                path = Path(root) / (name + '.json')
                annual_game.save(path, journal, game.away, legacy, public_farm=True)
                slot = json.loads(path.read_bytes())
                self.assertEqual('game_upkeep' in slot, legacy is not None)
                game.economy.game_upkeep = deepcopy(legacy)
                # Supply a pre-existing replay result to isolate the storage boundary.
                with patch.object(annual_game, 'restore_journal', return_value=game):
                    self.assertTrue(cli('show', path)['public_farm'])
                    if legacy is not None:
                        slot['game_upkeep'] = {'opaque': [2]}
                        path.write_text(json.dumps(slot), encoding='utf-8')
                        with self.assertRaises(ValueError):
                            annual_game.load(path)

    def test_default_and_explicit_disable_retain_published_economic_hash(self):
        expected = '2cdb96bc118087635ee8a195000b73a626d7d854f6508db4275ab29849309017'
        explicit = step_game(annual_game.create(0), public_farm=False)
        self.assertNotIn('public_harvest', explicit)
        self.assertNotIn('harvest_rule', explicit['public_policy'])
        self.assertEqual(sha256(canonical_line(self.prior)).hexdigest(), expected)
        self.assertEqual(sha256(canonical_line(explicit)).hexdigest(), expected)
