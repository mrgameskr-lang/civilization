"""Recompute both pre-existing annual paths with optional features at their defaults."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from time import perf_counter

from check import PIN, ROOT, original, sha

sys.path.insert(0, str(ROOT))
from experiments import posting_replay65, repeat_posting_register65
from experiments.verify_civic_off64 import publish_receipt


SOURCES = (
    'civsim/supply62.py', 'civsim/service62.py', 'civsim/supply_audit62.py',
    'civsim/peace62.py', 'civsim/posting_engine65.py', 'civsim/postings65.py',
    'experiments/posting_replay65.py', 'experiments/repeat_posting_register65.py',
)
ARCHIVES = {'A': 'examples/phase6c1-m1/pr18-replay.json',
            'B': 'examples/phase6c1-m1/register-repeat.json'}
FIELDS = {'A': posting_replay65.FIELDS, 'B': repeat_posting_register65.FIELDS}
YEARS = (50, 100, 200)


def current_sources():
    return {name: sha((ROOT / name).read_bytes()) for name in SOURCES}


def require_same_sources(expected):
    if current_sources() != expected:
        raise ValueError('Annual path source changed during the replay')


def replay(job):
    arm, seed, expected, sources = job
    require_same_sources(sources)
    if arm == 'A':
        rows = posting_replay65.check_seed((seed, expected))
    else:
        rows = repeat_posting_register65.replay(seed)
    require_same_sources(sources)
    return arm, rows


def run(out, workers):
    targets = {key: out / f'final-off-{key}.json' for key in ('sources', 'sample', 'all')}
    for path in targets.values():
        if path.exists():
            raise FileExistsError(path)
    if workers not in range(1, 5):
        raise ValueError('Expected one through four workers')
    start = perf_counter()
    sources = current_sources()
    pinned, indexed = {}, {}
    for arm, path in ARCHIVES.items():
        raw = original(path)
        if raw != (ROOT / path).read_bytes():
            raise ValueError('Historical receipt differs from its Git object: ' + path)
        rows = json.loads(raw)['checkpoints']
        indexed[arm] = {(r['seed'], r['year']): r for r in rows}
        grid = {(seed, year) for seed in range(40) for year in YEARS}
        if len(rows) != len(grid) or set(indexed[arm]) != grid:
            raise ValueError('Historical receipt has duplicate or missing observations')
        pinned[arm] = {'path': path, 'sha256': sha(raw)}
    earlier, pins = posting_replay65.baseline()
    meta = {'baseline_commit': PIN, 'working_source_sha256': sources, 'archives': pinned,
            'a_input_table_sha256': pins, 'workers_total': workers, 'horizons': list(YEARS),
            'started_utc': datetime.now(timezone.utc).isoformat()}
    publish_receipt(targets['sources'], meta)
    matched = {arm: [] for arm in ARCHIVES}
    sample = [0, 20]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for label, picks in (('sample', sample), ('all', [s for s in range(40) if s not in sample])):
            jobs = [(arm, seed, earlier[seed], sources) for seed in picks for arm in ARCHIVES]
            for arm, rows in pool.map(replay, jobs):
                for row in rows:
                    if indexed[arm][row['seed'], row['year']] != row:
                        raise ValueError(f"{arm} seed {row['seed']} year {row['year']} differs")
                    matched[arm].append(row)
            seeds = sample if label == 'sample' else list(range(40))
            grid = {(s, y) for s in seeds for y in YEARS}
            require_same_sources(sources)
            arms = {}
            for arm, rows in matched.items():
                if len(rows) != len(grid) or {(r['seed'], r['year']) for r in rows} != grid:
                    raise ValueError(f'Incomplete {label} replay for {arm}')
                arms[arm] = {'world_years': len(seeds) * max(YEARS), 'streams': FIELDS[arm],
                             'matched_digests': len(rows) * len(FIELDS[arm]),
                             'checkpoints': sorted(rows, key=lambda r: (r['seed'], r['year']))}
            receipt = {**meta, 'seeds': seeds, 'paths': arms,
                       'elapsed_seconds_including_sample': round(perf_counter() - start, 3),
                       'sample_included': label == 'all'}
            publish_receipt(targets[label], receipt)
            print(f"{label}: {sum(r['matched_digests'] for r in arms.values())} digests matched, "
                  f"{receipt['elapsed_seconds_including_sample']}s", flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    run(args.out, args.workers)
