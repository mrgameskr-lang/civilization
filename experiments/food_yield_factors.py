"""One-year arithmetic crop sensitivities from the archived arm A regional inputs."""

import argparse
from collections import Counter
import gzip
import json
from math import prod
from pathlib import Path
from tempfile import TemporaryDirectory

from .publication import publish_file


CHECKPOINTS = (50, 100, 200)
FACTORS = ('productivity', 'technology', 'fertility', 'climate', 'equipment', 'farm_multiplier')
COLUMNS = ('year', 'region', 'farm_workers_total', 'sector_workers', 'land_capacity', 'soil_before',
           'harvest_total', 'levied_food', 'taxable_surplus_food', 'tax_private_before',
           'tax_private_after', 'tax_protected_food', *FACTORS)


def crop_yield(row, workers, soil):
    """Food units; round down once regionally, using productive workers and field-time soil."""
    return 32 * workers * soil * prod(row[k] for k in FACTORS) // (10 * 1000**7)


def replace_inputs(row, first):
    """Change exactly one factor per calculation, retaining observed equipment intensity."""
    workers = min(first['farm_workers_total'], row['land_capacity'], row['sector_workers'])
    return (crop_yield(row, row['farm_workers_total'], first['soil_before']),
            crop_yield(row, workers, row['soil_before']), workers)


def _check_row(row, year):
    if any(type(v) is not int or v < 0 for v in row.values()) or row['year'] != year:
        raise ValueError(f'invalid regional quantities or year at year {year}')
    workers = row['farm_workers_total']
    if workers > min(row['sector_workers'], row['land_capacity']):
        raise ValueError(f'recorded farmers exceed regional labor or land at year {year}')
    if crop_yield(row, workers, row['soil_before']) != row['harvest_total']:
        raise ValueError(f'gross crop formula differs in year {year}, region {row["region"]}')
    before, levy = row['tax_private_before'], row['levied_food']
    if (max(0, before - row['tax_protected_food']) != row['taxable_surplus_food']
            or before - levy != row['tax_private_after']):
        raise ValueError(f'private tax boundary differs in year {year}, region {row["region"]}')


def _measure(row, first):
    soil_food, labor_food, effective = replace_inputs(row, first)
    now, old = row['harvest_total'], first['harvest_total']
    excess = max(0, row['levied_food'] - row['taxable_surplus_food'])
    return {
        'regions': 1, 'year1_gross_food': old, 'observed_gross_food': now,
        'observed_minus_year1_gross_food': now - old,
        'fixed_year1_soil_gross_food': soil_food, 'fixed_year1_soil_minus_observed_food': soil_food - now,
        'fixed_year1_workers_gross_food': labor_food, 'fixed_year1_workers_minus_observed_food': labor_food - now,
        'year1_workers': first['farm_workers_total'], 'observed_workers': row['farm_workers_total'],
        'fixed_workers_after_caps': effective, 'regions_capped': int(effective < first['farm_workers_total']),
        'levied_food': row['levied_food'], 'taxable_surplus_food': row['taxable_surplus_food'],
        'levy_beyond_protected_surplus_food': excess, 'regions_levied_beyond_protected_surplus': int(excess > 0),
    }


def analyze_seed(path, seed, *, checkpoints=CHECKPOINTS, region_count=32):
    """Validate every regional yield through the last requested year; summarize checkpoint years only."""
    checkpoints = set(checkpoints)
    if not checkpoints or any(type(y) is not int or y < 1 for y in checkpoints):
        raise ValueError('expected positive checkpoint years')
    last = max(checkpoints)
    first, results = {}, {}
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        header = json.loads(stream.readline())
        columns = header['columns']
        if (header.get('schema') != 'food-flow/1' or header.get('arm') != 'A' or header.get('seed') != seed
                or len(columns) != len(set(columns)) or not set(COLUMNS).issubset(columns)):
            raise ValueError(f'unexpected region header for seed {seed}')
        indices = {key: columns.index(key) for key in COLUMNS}
        for year in range(1, last + 1):
            line = stream.readline()
            if not line:
                raise ValueError(f'seed {seed} ends before year {year}')
            seen, totals = set(), Counter()
            for raw in json.loads(line):
                if len(raw) != len(columns):
                    raise ValueError(f'wrong column count in seed {seed}, year {year}')
                row = {key: raw[index] for key, index in indices.items()}
                _check_row(row, year)
                i = row['region']
                if i in seen or (year > 1 and i not in first):
                    raise ValueError(f'unknown or duplicate region in seed {seed}, year {year}')
                seen.add(i)
                if year == 1:
                    first[i] = row
                if year in checkpoints:
                    totals.update(_measure(row, first[i]))
            if len(seen) != region_count or seen != first.keys():
                raise ValueError(f'incomplete regional panel in seed {seed}, year {year}')
            if year in checkpoints:
                results[year] = dict(totals)
        if last == 200 and stream.readline():
            raise ValueError(f'extra years beyond the official 200-year study in seed {seed}')
    return results


def analyze(study):
    cohorts = {c: {y: Counter() for y in CHECKPOINTS} for c in ('development', 'holdout')}
    observations = []
    for seed in range(40):
        cohort = 'development' if seed < 20 else 'holdout'
        path = Path(study) / f'seed-{seed:02}-A-regions.jsonl.gz'
        for year, row in analyze_seed(path, seed).items():
            cohorts[cohort][year].update(row)
            observations.append({'seed': seed, 'cohort': cohort, 'year': year, **row})
    return {
        'schema': 'food-yield-factors/1', 'arm': 'A', 'years': list(CHECKPOINTS),
        'observed_region_years_verified': 40 * 32 * max(CHECKPOINTS),
        'units': {'*_food': 'integer food units during the indicated year', '*workers* (counts)': 'people',
                  'regions*': 'region counts', 'soil_before and other intensity factors': 'permille'},
        'method': {
            'baseline': 'First production-year soil and active farmers from the same seed and region.',
            'soil': 'Use year-one soil_before. This is the soil entering production after any public works and before annual erosion/recovery.',
            'workers': 'Use year-one active farmers capped by current effective land slots and current total sector workers. No other sector is simulated.',
            'constants': 'All other factors use the observed year, including actual climate, productivity, technology, soil or labor as applicable, and observed equipment intensity.',
            'calculation': 'Each region separately rounds down 32 × farmers × soil × productivity × technology × fertility × climate × equipment × farm_multiplier / (10 × 1000^7). Sum afterward.',
            'meaning': 'Each difference is a separate one-year arithmetic sensitivity. The two differences can overlap. They do not constitute an additive decomposition or a causal long-run intervention.',
            'tax': 'Observed taxes are post-harvest transfers. Excess is max(0, levy − observed private surplus above the protected reserve) per region. This tests reserve compliance only, not the welfare effect of taxation.',
            'cohorts': 'Development seeds 0–19 and holdout seeds 20–39. Values below are sums across 20 worlds at the named year, not cumulative over time.',
        },
        'cohorts': {c: [{'year': y, 'seeds': 20, **totals} for y, totals in by_year.items()]
                    for c, by_year in cohorts.items()}, 'seed_years': observations,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.out.exists():
            raise FileExistsError(f'output exists: {args.out}')
        result = analyze(args.study)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=args.out.parent) as staging:
            path = Path(staging) / 'factors.json'
            path.write_bytes((json.dumps(result, indent=2, ensure_ascii=False) + '\n').encode('utf-8'))
            publish_file(path, args.out)
    except (OSError, ValueError, KeyError, EOFError) as exc:
        parser.exit(1, f'yield analysis failed: {exc}\n')
    print(f"Verified {result['observed_region_years_verified']} regional harvests and wrote {args.out}")


if __name__ == '__main__':
    main()
