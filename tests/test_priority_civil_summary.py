import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from experiments.priority_civil_summary import ARMS, CUMULATIVE, YEARS, publish, summarize


def fixture(directory):
    (directory / 'execution.json').write_text(json.dumps({'seeds': list(range(40)), 'arms': ARMS,
                                                         'checkpoints': YEARS}), encoding='utf8')
    for seed in range(40):
        world = {'seed': seed, 'sample': 'development' if seed < 20 else 'validation', 'arms': {}}
        for arm, offset in zip(ARMS, (0, 4, seed - 20), strict=True):
            points = []
            for year in YEARS:
                units = 1000 + seed + year + offset
                points.append({'year': year, 'cumulative': dict.fromkeys(CUMULATIVE, units),
                               'population': 2 * units, 'cash': 3 * units,
                               'closing_stock': {'food': units, 'ore': units * 4, 'tools': units * 5},
                               'unrelated': {'ignored': 'arbitrary'}})
            world['arms'][arm] = {'checkpoints': points}
        (directory / f'seed-{seed:02}.json').write_text(json.dumps(world), encoding='utf8')


class PriorityCivilSummaryTests(unittest.TestCase):
    def test_all_contrasts_signed_and_cohorts_separate(self):
        with TemporaryDirectory() as name:
            root = Path(name)
            fixture(root)
            result = summarize(root)
        self.assertEqual(len(result['contrasts']), 18)
        self.assertEqual(len(result['seed_file_sha256']), 40)
        for row in result['contrasts']:
            seeds = range(20) if row['sample'] == 'development' else range(20, 40)
            offsets = {'move_off': [0]*20, 'move_on': [4]*20, 'relief_first': [s-20 for s in seeds]}
            diffs = [a-b for a, b in zip(offsets[row['first_arm']], offsets[row['subtract_arm']], strict=True)]
            self.assertEqual(row['seed_ids'], list(seeds))
            self.assertEqual(len(row['metrics']), 13)
            factors = {'population': 2, 'cash': 3, 'closing_ore': 4, 'closing_tools': 5}
            for metric, stats in row['metrics'].items():
                values = [d*factors.get(metric, 1) for d in diffs]
                self.assertEqual(stats, {'deltas': values, 'mean': sum(values)/20,
                                         'min': min(values), 'max': max(values)})

    def test_rejects_duplicate_checkpoint_and_missing_seed(self):
        with TemporaryDirectory() as name:
            root = Path(name)
            fixture(root)
            path = root / 'seed-07.json'
            record = json.loads(path.read_bytes())
            record['arms']['relief_first']['checkpoints'][1]['year'] = 50
            path.write_text(json.dumps(record), encoding='utf8')
            with self.assertRaisesRegex(ValueError, 'checkpoint'):
                summarize(root)
            path.unlink()
            with self.assertRaisesRegex(ValueError, 'seed files'):
                summarize(root)

    def test_preserves_published_output_and_is_reproducible(self):
        with TemporaryDirectory() as name:
            root = Path(name)
            fixture(root)
            first, second = root/'out1.json', root/'out2.json'
            publish(root, first)
            publish(root, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with self.assertRaises(FileExistsError):
                publish(root, first)
            self.assertEqual(first.read_bytes(), second.read_bytes())
