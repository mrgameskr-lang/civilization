"""Compare the two historical economic arms directly with their pinned Git blobs."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
COMMIT = '6db12f827bac1fc82447886d699d9fe42d70b9f9'
REFERENCE = 'examples/token-upkeep-v1/study'
RELEASE = ROOT / 'examples/relief-priority-v1/study'
ARMS = ('move_off', 'move_on')
YEARS = (50, 100, 200)
ECONOMIC_FIELDS = ('annual_sha256', 'cash', 'population', 'closing_stock')


def _line(value):
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')


def _years(record, arm):
    rows = record['arms'][arm]['checkpoints']
    indexed = {row['year']: row for row in rows if type(row['year']) is int}
    if len(rows) != len(YEARS) or set(indexed) != set(YEARS):
        raise ValueError(f'{arm} must have exactly one checkpoint for each of {YEARS}')
    return indexed


def _project(row, original_keys):
    return {**{k: row[k] for k in ECONOMIC_FIELDS},
            'cumulative': {k: row['cumulative'][k] for k in original_keys}}


def compare_seed(seed, baseline, release):
    """Compare declared economic fields. Additional release counters and arms are ignored."""
    sample = 'development' if seed < 20 else 'validation'
    hashes = [sha256(), sha256()]
    try:
        for record, checksum in zip((baseline, release), hashes):
            if type(record['seed']) is not int or record['seed'] != seed or record['sample'] != sample:
                raise ValueError(f'seed {seed}: wrong seed or sample')
            checksum.update(_line([seed, sample, record['opening_sha256']]))
        if baseline['opening_sha256'] != release['opening_sha256']:
            raise ValueError(f'seed {seed}: opening SHA-256 differs')

        for arm in ARMS:
            old, new = _years(baseline, arm), _years(release, arm)
            for year in YEARS:
                keys = old[year]['cumulative'].keys()
                pair = (_project(old[year], keys), _project(new[year], keys))
                # JSON equality distinguishes booleans, integers and floating point values.
                for field in (*ECONOMIC_FIELDS, 'cumulative'):
                    if _line(pair[0][field]) != _line(pair[1][field]):
                        raise ValueError(f'seed {seed}, {arm}, year {year}: {field} differs')
                for entry, checksum in zip(pair, hashes):
                    checksum.update(_line([arm, year, entry]))
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f'seed {seed}: missing or malformed archived comparison field') from exc

    return {'seed': seed, 'cohort': 'development' if seed < 20 else 'holdout',
            'opening_sha256': baseline['opening_sha256'], 'matched_annual_sha256': len(ARMS) * len(YEARS),
            'baseline_projection_sha256': hashes[0].hexdigest(), 'release_projection_sha256': hashes[1].hexdigest()}


def verify_archive(study):
    study = Path(study)
    filenames = [f'seed-{seed:02d}.json' for seed in range(40)]
    if {p.name for p in study.glob('seed-*.json')} != set(filenames):
        raise ValueError('expected seed-00.json through seed-39.json in the completed study')
    rows = []
    for seed, filename in enumerate(filenames):
        source = subprocess.check_output(['git', 'cat-file', 'blob', f'{COMMIT}:{REFERENCE}/{filename}'], cwd=ROOT)
        rows.append(compare_seed(seed, json.loads(source), json.loads((study / filename).read_bytes())))

    def counts(records):
        n = len(records)
        comparisons = sum(row['matched_annual_sha256'] for row in records)
        return {'seeds': n, 'matched_openings': n, 'matched_annual_sha256': comparisons,
                'matched_old_cumulative_maps': comparisons, 'matched_closing_economic_records': comparisons}

    return {'format': 'economic-archive-compat/1', 'reference_commit': COMMIT, 'reference_path': REFERENCE,
            'arms': list(ARMS), 'years': list(YEARS), 'economic_fields': list(ECONOMIC_FIELDS[1:]),
            'projection_encoding': 'Sorted ASCII JSON, compact separators, LF after each entry. '
                                   'Hash [seed,sample,opening_sha256], then [arm,year,fields] in listed order. '
                                   'Cumulative maps include exactly the corresponding pinned checkpoint keys.',
            'cohorts': {c: counts([r for r in rows if r['cohort'] == c]) for c in ('development', 'holdout')},
            'total': counts(rows), 'verified': rows}


def write_receipt(path, result):
    """Publish complete bytes atomically. Repeating an identical result is idempotent."""
    path = Path(path)
    content = (json.dumps(result, indent=2, sort_keys=True) + '\n').encode('ascii')
    path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=path.parent) as staging:
        ready = Path(staging) / 'receipt.json'
        ready.write_bytes(content)
        try:
            if os.name == 'nt':
                # Windows rename fails atomically if the destination already exists.
                os.rename(ready, path)
            else:
                os.link(ready, path)
        except FileExistsError:
            if path.read_bytes() != content:
                raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, default=RELEASE)
    parser.add_argument('--out', type=Path, default=RELEASE.parent / 'compat.json')
    args = parser.parse_args()
    try:
        result = verify_archive(args.study)
        write_receipt(args.out, result)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'archive comparison failed: {exc}\n')
    print(json.dumps(result['total'], sort_keys=True))


if __name__ == '__main__':
    main()
