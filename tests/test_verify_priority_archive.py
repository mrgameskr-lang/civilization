from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from experiments.verify_priority_archive import compare_seed, write_receipt


def digest(label):
    return sha256(label.encode()).hexdigest()


def baseline(seed=0):
    record = {'seed': seed, 'sample': 'development' if seed < 20 else 'validation',
              'opening_sha256': digest(str(seed)), 'arms': {}}
    for arm in ('move_off', 'move_on'):
        record['arms'][arm] = {'checkpoints': [
            {'year': year, 'annual_sha256': digest(f'{arm}-{seed}-{year}'), 'cash': 0,
             'population': 10 + seed, 'closing_stock': {'food': 4, 'ore': 1, 'tools': 0},
             'cumulative': {'resident_meals': year * 10, 'receipts': 0}}
            for year in (50, 100, 200)]}
    return record


class ArchiveCompatibilityTests(unittest.TestCase):
    def test_extra_arms_and_new_counters_do_not_enter_the_old_comparison(self):
        old = baseline(20)
        current = deepcopy(old)
        current['arms']['unrelated'] = {'checkpoints': None}
        for arm in ('move_off', 'move_on'):
            current['arms'][arm]['checkpoints'].reverse()
            for row in current['arms'][arm]['checkpoints']:
                row['cumulative']['extra_civil_measure'] = 19
                row['extra_field'] = 'unexamined'
        receipt = compare_seed(20, old, current)
        self.assertEqual(receipt['cohort'], 'holdout')
        self.assertEqual(receipt['matched_annual_sha256'], 6)
        self.assertEqual(receipt['baseline_projection_sha256'], receipt['release_projection_sha256'])
        self.assertEqual(receipt, compare_seed(20, old, old))

    def test_each_archived_metric_and_checkpoint_identity_is_checked(self):
        for change in ('seed', 'sample', 'opening', 'annual', 'population', 'cash', 'stock',
                       'cumulative', 'counter_missing', 'duplicate_year', 'missing_year', 'swap_arms'):
            with self.subTest(change=change):
                old = baseline()
                current = deepcopy(old)
                rows = current['arms']['move_on']['checkpoints']
                row = rows[0]
                if change == 'seed': current['seed'] = False
                elif change == 'sample': current['sample'] = 'validation'
                elif change == 'opening': current['opening_sha256'] = digest('wrong')
                elif change == 'annual': row['annual_sha256'] = digest('wrong')
                elif change == 'population': row['population'] += 1
                elif change == 'cash': row['cash'] = False
                elif change == 'stock': row['closing_stock']['ore'] -= 1
                elif change == 'cumulative': row['cumulative']['receipts'] = False
                elif change == 'counter_missing': del row['cumulative']['receipts']
                elif change == 'duplicate_year': rows.append(deepcopy(row))
                elif change == 'missing_year': rows.pop()
                elif change == 'swap_arms': current['arms']['move_on'] = current['arms']['move_off']
                with self.assertRaises(ValueError):
                    compare_seed(0, old, current)

    def test_publication_repeats_identically_and_protects_different_receipt(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'audit' / 'receipt.json'
            write_receipt(path, {'ok': 12})
            before = path.read_bytes()
            write_receipt(path, {'ok': 12})
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaises(FileExistsError):
                write_receipt(path, {'ok': 13})
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(path.parent.iterdir()), [path])
