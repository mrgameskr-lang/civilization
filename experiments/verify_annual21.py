"""Replay PR 21's published default scenarios and check their bytes against Git."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import gzip
from hashlib import sha256
import json
from pathlib import Path
import platform
import subprocess
from tempfile import TemporaryDirectory
from time import perf_counter

from civsim.storage import canonical_line
from experiments import annual_unit_case, annual_unit_study
from experiments.verify_civic_off64 import publish_receipt


ROOT = Path(__file__).resolve().parents[1]
BASE = 'a6d9e6b85f58a2cfc35fc96b1afd8c23b781276c'
EXAMPLE = 'examples/annual-unit-v1'
ARMS = ('move', 'hold')
HORIZONS = (50, 100, 200)
DRIVERS = ('experiments/annual_unit_study.py', 'experiments/annual_unit_case.py',
           'experiments/unit_economy_metrics.py')


def digest(content):
    return sha256(content).hexdigest()


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, stdout=subprocess.PIPE, check=True).stdout


def archived(path):
    return git('cat-file', 'blob', BASE + ':' + path)


def source_fingerprints():
    paths = sorted((ROOT / 'civsim').glob('*.py')) + [ROOT / p for p in DRIVERS]
    return {p.relative_to(ROOT).as_posix(): digest(p.read_bytes()) for p in paths}


def compare_case():
    directory = EXAMPLE + '/case'
    originals = git('ls-tree', '-r', '--name-only', BASE, '--', directory).decode().splitlines()
    names = {Path(path).name for path in originals}
    if not names or len(names) != len(originals):
        raise ValueError('Incomplete or ambiguous PR 21 case directory')
    verified = {}
    with TemporaryDirectory() as scratch:
        out = Path(scratch) / 'case'
        annual_unit_case.case(out)
        if {f.name for f in out.iterdir()} != names:
            raise ValueError('Different case file inventory')
        for path in originals:
            name = Path(path).name
            reference, current = archived(path), (out / name).read_bytes()
            if name.endswith('.gz'):
                expected, actual = gzip.decompress(reference), gzip.decompress(current)
            else:
                expected, actual = reference, current
            if expected != actual:
                raise ValueError('PR 21 case payload differs: ' + name)
            verified[name] = {'reference_file_sha256': digest(reference),
                              'replayed_file_sha256': digest(current),
                              'identical_file_bytes': reference == current,
                              'matched_payload_sha256': digest(actual)}
    return verified


def compare_seed(job):
    seed, years = job
    path = f'{EXAMPLE}/study/seed-{seed:02}.json'
    raw = archived(path)
    original = json.loads(raw)
    if original['seed'] != seed or tuple(p['arm'] for p in original['paths']) != ARMS:
        raise ValueError(f'Unexpected PR 21 seed or arms at {path}')
    for arm in original['paths']:
        if tuple(r['year'] for r in arm['checkpoints']) != HORIZONS:
            raise ValueError(f'Unexpected PR 21 checkpoint grid at {path}')

    # The historical case and study drivers use their original default engine settings.
    result = annual_unit_study.run_seed(seed, years=max(years), checkpoints=years)
    for arm in original['paths']:
        arm['checkpoints'] = [r for r in arm['checkpoints'] if r['year'] in years]
    if result != original:
        raise ValueError(f'Replay differs from {path} through year {max(years)}')
    encoded = canonical_line(result)
    if years == HORIZONS and encoded != raw:
        raise ValueError(f'Seed {seed} matched structurally but its serialized file differs')
    return {'seed': seed, 'reference_file_sha256': digest(raw),
            'replayed_file_sha256': digest(encoded), 'complete_seed_file': years == HORIZONS,
            'checkpoints': [{'arm': arm['arm'], 'year': row['year'],
                             'annual_chain_sha256': row['annual_chain_sha256']}
                            for arm in result['paths'] for row in arm['checkpoints']]}


def verify(out, scope, workers):
    if out.exists():
        raise FileExistsError(out)
    if not 1 <= workers <= 4 or scope not in ('smoke', 'full'):
        raise ValueError('Choose smoke or full and one through four workers')
    for driver in DRIVERS:
        if (ROOT / driver).read_bytes().replace(b'\r\n', b'\n') != archived(driver).replace(b'\r\n', b'\n'):
            raise ValueError('PR 21 measurement driver changed: ' + driver)
    start = perf_counter()
    started = datetime.now(timezone.utc).isoformat()
    sources = source_fingerprints()
    cases = compare_case()
    seeds = list(range(40)) if scope == 'full' else [0]
    years = HORIZONS if scope == 'full' else (50,)
    with ProcessPoolExecutor(max_workers=min(workers, len(seeds))) as pool:
        results = list(pool.map(compare_seed, [(s, years) for s in seeds]))
    if source_fingerprints() != sources:
        raise ValueError('Engine or PR 21 measurement source changed during verification')
    receipt = {'scope': scope, 'reference_commit': BASE, 'python': platform.python_version(),
               'started_utc': started, 'elapsed_seconds': round(perf_counter() - start, 3),
               'workers': min(workers, len(seeds)), 'seeds': seeds, 'horizons': years,
               'matched_checkpoints': len(seeds) * len(years) * len(ARMS),
               'observed_arm_years': len(seeds) * max(years) * len(ARMS),
               'unique_year_steps': len(seeds) * (1 + (max(years) - 1) * len(ARMS)),
               'cases': cases, 'seed_results': results, 'working_source_sha256': sources}
    publish_receipt(out, receipt)
    print(f"{receipt['matched_checkpoints']} checkpoints and {len(cases)} case payloads matched "
          f"in {receipt['elapsed_seconds']} seconds")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', choices=('smoke', 'full'), required=True)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    verify(args.out, args.scope, args.workers)
