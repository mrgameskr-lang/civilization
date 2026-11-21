"""Compare civilian economic checkpoint totals in completed paired studies."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from experiments.publication import publish_file
from experiments.summarize_token_civil import CUMULATIVE as PR23_CIVIL_FLOWS


ARMS = ('move_off', 'move_on', 'relief_first')
CONTRASTS = (('relief_first', 'move_on'), ('move_on', 'move_off'), ('relief_first', 'move_off'))
YEARS = (50, 100, 200)
CUMULATIVE = (*PR23_CIVIL_FLOWS, 'levied_food', 'levied_tools', 'public_freight_food')
CLOSING = ('population', 'cash', 'closing_food', 'closing_ore', 'closing_tools')


def _values(point):
    values = {k: point['cumulative'][k] for k in CUMULATIVE}
    values.update(population=point['population'], cash=point['cash'])
    for good in ('food', 'ore', 'tools'):
        values['closing_' + good] = point['closing_stock'][good]
    if any(type(value) is not int or value < 0 for value in values.values()):
        raise ValueError('Expected nonnegative integer economic balances and flows')
    return values


def summarize(study):
    """Return 18 paired comparisons covering all 40 published world trajectories."""
    seeds = list(range(40))
    manifest = json.loads((study / 'execution.json').read_bytes())
    if (manifest.get('seeds', seeds) != seeds or tuple(manifest.get('checkpoints', YEARS)) != YEARS
            or sorted(manifest.get('arms', ARMS)) != sorted(ARMS)):
        raise ValueError('Execution manifest disagrees with expected cohort or checkpoint grid')
    names = [f'seed-{seed:02}.json' for seed in seeds]
    if sorted(p.name for p in study.glob('seed-*.json')) != names:
        raise ValueError('Missing or unexpected seed files')

    hashes, observations = {}, {}
    for seed, name in zip(seeds, names, strict=True):
        raw = (study / name).read_bytes()
        hashes[name] = sha256(raw).hexdigest()
        record = json.loads(raw)
        sample = 'development' if seed < 20 else 'validation'
        if record['seed'] != seed or record['sample'] != sample or sorted(record['arms']) != sorted(ARMS):
            raise ValueError(f'Unexpected seed, sample or study arm in {name}')
        for arm in ARMS:
            points = record['arms'][arm]['checkpoints']
            if tuple(p['year'] for p in points) != YEARS:
                raise ValueError(f'Missing, duplicate or unexpected checkpoint in {name} / {arm}')
            for point in points:
                observations[seed, arm, point['year']] = _values(point)

    contrasts = []
    for sample, group in [('development', seeds[:20]), ('validation', seeds[20:])]:
        for year in YEARS:
            for first, subtract in CONTRASTS:
                metrics = {}
                for key in (*CUMULATIVE, *CLOSING):
                    deltas = [observations[s, first, year][key] - observations[s, subtract, year][key]
                              for s in group]
                    metrics[key] = {'deltas': deltas, 'mean': sum(deltas) / len(deltas),
                                    'min': min(deltas), 'max': max(deltas)}
                contrasts.append({'sample': sample, 'year': year, 'first_arm': first,
                                  'subtract_arm': subtract, 'seed_ids': group, 'metrics': metrics})
    return {'schema': 'priority-civilian-summary/1', 'cumulative_metrics': CUMULATIVE,
            'closing_metrics': CLOSING, 'years': YEARS, 'seed_file_sha256': hashes,
            'difference': 'First arm minus subtract arm within each seed; deltas follow seed_ids order.',
            'notes': {'unmet': 'Unmet resident food units; a negative difference means less unmet demand.',
                      'private_delivered': 'Domestic private cargo units delivered, all goods combined.',
                      'public_stock': 'Closing food, ore and tools in public depots.',
                      'public_freight_food': 'Cumulative food spent on public freight as recorded in checkpoints.'},
            'contrasts': contrasts}


def publish(study, destination):
    if destination.exists():
        raise FileExistsError(destination)
    summary = summarize(study)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent) as scratch:
        staged = Path(scratch) / 'summary.json'
        staged.write_text(json.dumps(summary, sort_keys=True, indent=2) + '\n', encoding='utf8', newline='\n')
        publish_file(staged, destination)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    publish(args.study, args.out)
    print('Published 18 paired comparisons of 13 civilian metrics.')
