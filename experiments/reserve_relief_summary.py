"""Summarize civilian harvest, warehouse coverage, resident meals and funded relief."""

import argparse
from collections import Counter
from fractions import Fraction
import gzip
from hashlib import sha256
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .publication import publish_file


ARMS = ('A', 'C', 'D7', 'D14', 'E')
HORIZONS = (50, 100, 200)
STOCKS = ('closing_population', 'private_open', 'private_close', 'public_open', 'public_close',
          'pre_extra_public', 'opening_cash', 'closing_cash')
STOCK_EXPOSURE = ('unmet_with_local_stock', 'unmet_with_other_domestic_stock_only', 'unmet_without_domestic_stock')
ORDINARY_GAPS = ('ordinary_gap_not_authorized', 'ordinary_gap_admin', 'ordinary_gap_budget', 'ordinary_gap_not_dispatched')
UNFILLED = tuple('emergency_unfilled_' + k for k in ('handling', 'admin', 'stock', 'road', 'freight'))
FLOWS = ('food_need', 'food_eaten', 'food_unmet', 'deaths', 'harvest_total', 'harvest_private', 'harvest_public',
         'levied_food', 'levy_deposited_food', 'levy_handling_food', 'private_farm_workers', 'public_farm_workers',
         'private_spoiled_food', 'depot_spoiled_food', 'public_freight_food',
         'private_domestic_food_in', 'private_foreign_food_in', 'aid_received_food',
         'ordinary_prior_request', 'ordinary_forecast_quantity', 'ordinary_approved_food', 'ordinary_open_gap',
         'ordinary_sent_food', 'ordinary_received_food', 'ordinary_freight_food', 'ordinary_remote_received',
         'emergency_requested', 'emergency_approved', 'emergency_dispatched_for_target', 'emergency_sent_food',
         'emergency_received_food', 'emergency_freight_food', 'emergency_remote_received',
         'unmet_with_closing_local_stock', 'unmet_without_ordinary_approval', 'unmet_after_ordinary_approval',
         'unmet_with_reserved_household_food', 'unmet_after_observed_remote_delivery', *STOCK_EXPOSURE, *ORDINARY_GAPS, *UNFILLED)


def civilian_row(source):
    row = {k: source[k] for k in (*STOCKS, *FLOWS)}
    if any(type(v) is not int or v < 0 for v in row.values()):
        raise ValueError('invalid civilian amount')
    if (row['food_eaten'] + row['food_unmet'] != row['food_need']
            or row['harvest_public'] + row['harvest_private'] != row['harvest_total']
            or row['levy_deposited_food'] + row['levy_handling_food'] != row['levied_food']
            or sum(row[k] for k in STOCK_EXPOSURE) != row['food_unmet']
            or row['unmet_after_ordinary_approval'] + row['unmet_without_ordinary_approval'] != row['food_unmet']):
        raise ValueError('resident meals, harvest ownership or stock exposure do not add up')
    if (row['ordinary_sent_food'] != row['ordinary_received_food'] or row['emergency_sent_food'] != row['emergency_received_food']
            or row['ordinary_open_gap'] != sum(row[k] for k in ORDINARY_GAPS) + row['ordinary_received_food']
            or row['emergency_requested'] != sum(row[k] for k in UNFILLED) + row['emergency_received_food']
            or row['emergency_requested'] - row['emergency_unfilled_handling'] - row['emergency_unfilled_admin'] != row['emergency_approved']
            or row['emergency_dispatched_for_target'] != row['emergency_received_food']):
        raise ValueError('relief stage request or settlement accounts do not add up')
    return row


def _ratio(a, b):
    return Fraction(a, b) if b else None


def _number(q):
    return float(q) if isinstance(q, Fraction) else q


def _rates(row):
    return {**{k: _number(_ratio(row[k], row['food_unmet'])) for k in STOCK_EXPOSURE},
            'unmet_share': _number(_ratio(row['food_unmet'], row['food_need'])),
            'closing_local_stock_unmet_share': _number(_ratio(row['unmet_with_closing_local_stock'], row['food_unmet'])),
            'emergency_received_per_requested': _number(_ratio(row['emergency_received_food'], row['emergency_requested'])),
            'ordinary_parts_per_open_gap': {k: _number(_ratio(row[k], row['ordinary_open_gap']))
                                           for k in (*ORDINARY_GAPS, 'ordinary_received_food')},
            'emergency_unfilled_per_request': {k: _number(_ratio(row[k], row['emergency_requested'])) for k in UNFILLED}}


def reserve_windows(windows):
    """Evaluate each world or country independently for exactly years 151 through 200."""
    out = {'windows': len(windows), 'calendar_years': 50 * len(windows), 'positive_demand_years': 0,
           'unclassified_windows': 0, 'net_drawdown_windows': 0, 'net_stock_change_food': 0,
           'thresholds': {str(n): dict.fromkeys(('covered_years', 'years_with_shortage_and_coverage',
                          'unmet_food_in_those_years', 'maintained_windows', 'maintained_without_net_drawdown'), 0)
                          for n in (1, 7, 14)}}
    minima, total_stock, total_need = [], 0, 0
    for records in windows:
        if len(records) != 50:
            raise ValueError('incomplete reserve window')
        observed = [r for r in records if r['food_need'] > 0]
        change = records[-1]['public_close'] - records[0]['public_open']
        out['positive_demand_years'] += len(observed)
        out['unclassified_windows'] += len(observed) < 50
        out['net_drawdown_windows'] += change < 0
        out['net_stock_change_food'] += change
        total_stock += sum(r['public_close'] for r in observed)
        total_need += sum(r['food_need'] for r in observed)
        if len(observed) == 50:
            minima.append(min(Fraction(365*r['public_close'], r['food_need']) for r in observed))
        for days, result in out['thresholds'].items():
            covered = [r for r in observed if 365 * r['public_close'] >= int(days) * r['food_need']]
            result['covered_years'] += len(covered)
            result['years_with_shortage_and_coverage'] += sum(r['food_unmet'] > 0 for r in covered)
            result['unmet_food_in_those_years'] += sum(r['food_unmet'] for r in covered)
            result['maintained_windows'] += len(covered) == 50
            result['maintained_without_net_drawdown'] += len(covered) == 50 and change >= 0
    out['pooled_public_days_across_demand_years'] = _number(_ratio(365 * total_stock, total_need))
    out['mean_of_complete_window_minimum_days'] = float(sum(minima)/len(minima)) if minima else None
    return out


def _read(path):
    raw = path.read_bytes()
    rolling, late_totals, points = Counter(), Counter(), {}
    windows = {i: [] for i in range(8)}
    world_window, previous = [], None
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        for year in range(1, 201):
            entry = json.loads(stream.readline())
            local = {r['owner']: civilian_row(r) for r in entry['countries']}
            world = civilian_row(entry['world'])
            if (type(entry['year']) is not int or entry['year'] != year or len(entry['countries']) != 8
                    or local.keys() != windows.keys() or any(sum(r[k] for r in local.values()) != v for k, v in world.items())
                    or world['opening_cash'] != world['closing_cash']):
                raise ValueError(f'incorrect country/world annual totals in {path.name}, year {year}')
            if previous is not None:
                for i, row in local.items():
                    old = previous[i]
                    if (old['private_close'], old['public_close'], old['closing_cash'], old['closing_population']) != (
                            row['private_open'], row['public_open'], row['opening_cash'], row['food_need']):
                        raise ValueError(f'discontinuous country accounts in {path.name}, year {year}')
            previous = local
            rolling.update({k: world[k] for k in FLOWS})
            if year in HORIZONS:
                points[year] = {'annual': world, 'cumulative': dict(rolling)}
            if year >= 151:
                late_totals.update({k: world[k] for k in FLOWS})
                for i, row in local.items():
                    windows[i].append({k: row[k] for k in ('food_need', 'food_unmet', 'public_open', 'public_close')})
                world_window.append({k: world[k] for k in ('food_need', 'food_unmet', 'public_open', 'public_close')})
        if stream.readline():
            raise ValueError(f'extra records after year 200 in {path.name}')
    return {'checkpoints': points, 'late': late_totals, 'world': world_window, 'countries': windows}, sha256(raw).hexdigest()


def paired_measure(pairs, *, cases=False):
    """Summarize signed differences with one vote per matched seed (or seed/country)."""
    valid = [(label, a, b, a-b) for label, a, b in pairs if a is not None and b is not None]
    diffs = [d for _, _, _, d in valid]
    result = {'matched': len(valid), 'undefined': len(pairs) - len(valid), 'increased': sum(d > 0 for d in diffs),
              'decreased': sum(d < 0 for d in diffs), 'tied': sum(d == 0 for d in diffs),
              'mean_delta': float(sum(diffs) / len(diffs)) if diffs else None,
              'min_delta': _number(min(diffs, default=None)), 'max_delta': _number(max(diffs, default=None))}
    if cases:
        def present(item):
            if item is None:
                return None
            label, a, b, delta = item
            return {**label, 'arm_value': _number(a), 'reference_value': _number(b), 'delta': _number(delta)}
        result['examples'] = {
            'largest_increase': present(max((p for p in valid if p[-1] > 0), key=lambda p:p[-1], default=None)),
            'largest_decrease': present(min((p for p in valid if p[-1] < 0), key=lambda p:p[-1], default=None)),
            'first_tie': present(next((p for p in valid if p[-1] == 0), None)),
        }
    return result


def _pooled(rows):
    sums = {k: sum(r[k] for r in rows) for k in rows[0]}
    result = {'sum': sums, 'mean_per_seed': {k: v / len(rows) for k, v in sums.items()},
              'ratios_of_sums': _rates(sums)}
    if 'public_close' in sums:
        result['ratios_of_sums']['public_days'] = _number(_ratio(365 * sums['public_close'], sums['food_need']))
    return result


def _arm(runs):
    checks = {year: {scope: _pooled([r['checkpoints'][year][scope] for r in runs]) for scope in ('annual', 'cumulative')}
              for year in HORIZONS}
    return {'checkpoints': checks, 'years_151_200': {'flows': _pooled([r['late'] for r in runs]),
            'world_coverage': reserve_windows([r['world'] for r in runs]),
            'country_coverage': reserve_windows([w for r in runs for w in r['countries'].values()])}}


def _pair_values(run, year):
    end, cumulative = (run['checkpoints'][year][k] for k in ('annual', 'cumulative'))
    values = {k: end[k] for k in ('closing_population', 'private_close', 'public_close')}
    values['public_days'] = _ratio(365 * end['public_close'], end['food_need'])
    for period, row in (('annual', end), ('cumulative', cumulative)):
        for k in ('food_need', 'food_eaten', 'food_unmet', 'deaths', 'harvest_total', 'harvest_private',
                  'harvest_public', 'levy_deposited_food', 'ordinary_received_food', 'emergency_received_food'):
            values[f'{period}_{k}'] = row[k]
        values[f'{period}_unmet_share'] = _ratio(row['food_unmet'], row['food_need'])
    return values


def _paired(source, seeds, arm, reference):
    result = {}
    for year in HORIZONS:
        pairs = [(s, _pair_values(source[s, arm], year), _pair_values(source[s, reference], year)) for s in seeds]
        result[year] = {k: paired_measure([({'seed': s}, a[k], b[k]) for s,a,b in pairs],
                         cases=k in ('annual_unmet_share','cumulative_unmet_share','cumulative_food_eaten'))
                        for k in pairs[0][1]}
        for example in result[year]['cumulative_unmet_share']['examples'].values():
            if example is not None:
                for label, name in (('arm_totals', arm), ('reference_totals', reference)):
                    cumulative = source[example['seed'],name]['checkpoints'][year]['cumulative']
                    example[label] = {k: cumulative[k] for k in ('food_need','food_eaten','food_unmet','harvest_total')}
    late = []
    for s in seeds:
        for i in range(8):
            rates = []
            for name in (arm, reference):
                rows = source[s,name]['countries'][i]
                rates.append(_ratio(sum(r['food_unmet'] for r in rows), sum(r['food_need'] for r in rows)))
            late.append(({'seed': s, 'country': i}, *rates))
    country_rates = paired_measure(late, cases=True)
    for example in country_rates['examples'].values():
        if example is not None:
            for label, name in (('arm_totals', arm), ('reference_totals', reference)):
                cells = source[example['seed'],name]['countries'][example['country']]
                example[label] = {k: sum(r[k] for r in cells) for k in ('food_need','food_unmet')}
    return {'checkpoints': result, 'country_151_200_unmet_share': country_rates}


def summarize(study):
    study = Path(study)
    source, hashes = {}, {}
    for seed in range(40):
        for arm in ARMS:
            path = study / f'seed-{seed:02}-{arm}-totals.jsonl.gz'
            source[seed, arm], hashes[path.name] = _read(path)
    cohorts = {}
    for name, seeds in (('development', list(range(20))), ('holdout', list(range(20,40)))):
        cohorts[name] = {'seeds': seeds, 'arms': {arm: _arm([source[s, arm] for s in seeds]) for arm in ARMS},
            'paired': {f'{arm}_minus_{ref}': _paired(source, seeds, arm, ref)
                       for j, arm in enumerate(ARMS) for ref in ARMS[:j]}}
    return {'schema': 'civil-reserve-relief-summary/1', 'source_sha256': hashes, 'world_years': 40000,
            'country_years': 320000, 'cohorts': cohorts, 'definitions': {
                'source': 'Seed and arm are identified by the published totals filename. Individual SHA-256 digests bind the 200 files read by this analysis; the study separately validates historical annual ledger hashes.',
                'units': 'Food measures are food units, labor is people per annual observation and worker-years when accumulated. Counts of deaths and residents are people. Rates are fractions, not percentages.',
                'time': 'Annual is the named year; cumulative sums flows from year 1 through that year. Stocks, cash and population appear at their boundaries only. All cohort sums are over 20 worlds. Dividing sums by 20 gives a mean per world.',
                'paired': 'Each difference is arm minus reference, computed within a seed. Paired means equally weight each defined seed, or each defined seed/country for the late national comparison. Lower unmet share means improvement; exact fractions classify direction and ties before rounding for JSON.',
                'comparisons': 'All ten pairwise contrasts are provided. C versus A adds public harvests, D7/D14 versus C lower the reserve target, E versus C adds the emergency relief stage to C. Other contrasts can combine different mechanisms.',
                'ratio': 'Cohort unmet share = sum(unmet)/sum(need), public days = 365*sum(closing public food)/sum(need). Undefined denominators give null. Absolute food eaten and a changing resident population are reported separately.',
                'persistence': 'For every world and each country separately, years 151–200 must all meet 1, 7 or 14 days of closing public stock coverage with positive demand. A stricter count also requires closing stock in year 200 >= opening stock in year 151. Net drawdown is the opposite endpoint inequality. A zero-demand year leaves window persistence unclassified.',
                'stock_exposure': 'Final resident food deficit is partitioned by positive public stocks immediately before supplemental relief: local, elsewhere in the same country only, or absent in that country. Shares divide by total final unmet food. Positive stock establishes overlap, not free or deliverable surplus. Closing-local exposure is a separate observation.',
                'stages': 'Ordinary open gap = actual receipt + unauthorized + admin + budget + nondispatched residual. Emergency requested = receipt + handling + admin + stock + road + freight unfilled under the sequential stage rules. Reconciliations cover that stage only. Do not add them to final resident deficit or infer a meal from a delivery.',
                'cases': 'Largest increase, largest decrease, and first tie in numerical seed/country order, or null if absent. Country counterexamples use summed late unmet/summed late need. Positive-reserve years with shortage are counts of world/country years and do not locate residents and stocks together within a region.',
            }}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--study', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    try:
        if args.out.exists():
            raise FileExistsError(args.out)
        result = summarize(args.study)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=args.out.parent) as folder:
            path = Path(folder) / 'summary.json'
            path.write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode())
            publish_file(path, args.out)
    except (ValueError, OSError, EOFError, KeyError) as exc:
        p.exit(1, f'civilian reserve summary failed: {exc}\n')
    print('Checked 40,000 world-years and 320,000 country-years.')


if __name__ == '__main__':
    main()
