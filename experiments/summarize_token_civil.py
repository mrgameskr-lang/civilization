"""Pair published world-level civilian outcomes by seed, checkpoint and study arm."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from experiments.publication import publish_file


YEARS = (50, 100, 200)
ARMS = ('move_off', 'move_on', 'hold_on')
CUMULATIVE = ('private_delivered', 'eaten', 'unmet', 'relief_delivered', 'road_used')
METRICS = (*CUMULATIVE, 'population', 'closing_food', 'closing_tools')


def _civil_values(point):
    values = {key: point['cumulative'][key] for key in CUMULATIVE}
    values['population'] = point['population']
    for good in ('food', 'tools'):
        values['closing_' + good] = point['closing_stock'][good]
    if any(type(value) is not int or value < 0 for value in values.values()):
        raise ValueError('Expected nonnegative integer civilian totals')
    return values


def _classify(pairs):
    """pairs contains one signed observation per seed in a single cohort."""
    by_direction = {'increased': [], 'decreased': [], 'tied': []}
    for seed, value in sorted(pairs.items()):
        key = 'increased' if value > 0 else 'decreased' if value < 0 else 'tied'
        by_direction[key].append(seed)
    return {'mean': sum(pairs.values()) / len(pairs), 'min': min(pairs.values()),
            'max': max(pairs.values()), 'seed_ids': by_direction}


def summarize(study):
    """Read a completed published study. No simulation entry point is called."""
    execution = json.loads((study / 'execution.json').read_bytes())
    if (execution['seeds'] != list(range(40)) or tuple(execution['checkpoints']) != YEARS
            or tuple(execution['arms']) != ARMS):
        raise ValueError('Expected 40 seeds, the three original arms and all three checkpoints')
    files = {f'seed-{seed:02}.json' for seed in range(40)}
    if {p.name for p in study.glob('seed-*.json')} != files:
        raise ValueError('Incomplete or unexpected seed files')

    sources, records = {}, {}
    for seed in range(40):
        name = f'seed-{seed:02}.json'
        raw = (study / name).read_bytes()
        sources[name] = sha256(raw).hexdigest()
        data = json.loads(raw)
        sample = 'development' if seed < 20 else 'validation'
        if data['seed'] != seed or data['sample'] != sample or set(data['arms']) != set(ARMS):
            raise ValueError(f'Unexpected sample, seed or arm in {name}')
        for arm in ARMS:
            points = data['arms'][arm]['checkpoints']
            if tuple(p['year'] for p in points) != YEARS:
                raise ValueError(f'Incomplete or duplicate checkpoint in {name}, {arm}')
            for p in points:
                records[seed, arm, p['year']] = _civil_values(p)

    contrasts = []
    for sample, seeds in [('development', range(20)), ('validation', range(20, 40))]:
        for year in YEARS:
            for reference in ('move_off', 'hold_on'):
                metrics = {}
                for metric in METRICS:
                    paired = {s: records[s, 'move_on', year][metric] - records[s, reference, year][metric]
                              for s in seeds}
                    metrics[metric] = _classify(paired)
                contrasts.append({'sample': sample, 'year': year, 'first_arm': 'move_on',
                                  'subtract_arm': reference, 'paired_seeds': len(seeds), 'metrics': metrics})
    return {
        'schema': 'civilian-paired-totals/1', 'seeds_per_sample': 20, 'years': YEARS,
        'cumulative_metrics': CUMULATIVE, 'end_of_year_metrics': METRICS[len(CUMULATIVE):],
        'metric_notes': {
            'private_delivered': 'Domestic private cargo units delivered across all goods.',
            'eaten': 'Resident meals eaten. A positive difference means more total meals.',
            'unmet': 'Unmet resident food units. A decrease is improvement on this measure; an increase is worsening.',
            'relief_delivered': 'Public food delivered to residents.',
            'road_used': 'Used capacity of domestic roads, counted once per road and year.',
            'population': 'Closing resident headcount.',
            'closing_food': 'Food remaining in public depots.', 'closing_tools': 'Tools remaining in public depots.'},
        'differences': 'First arm minus subtract arm, paired within seed. Means give each seed equal weight.',
        'interpretation': 'A change in volume, population, or stock alone does not establish welfare.',
        'seed_file_sha256': sources, 'contrasts': contrasts,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    result = summarize(args.study)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=args.out.parent) as temp:
        stage = Path(temp) / 'summary.json'
        stage.write_text(json.dumps(result, sort_keys=True, indent=2) + '\n', encoding='utf8', newline='\n')
        publish_file(stage, args.out)
    print(f"Compared {len(result['contrasts'])} paired sample/checkpoint/arm contrasts.")


if __name__ == '__main__':
    main()
