"""Describe the annual civilian food economy of published, matched world trajectories."""
import argparse
from collections import Counter, defaultdict
import gzip
from hashlib import sha256
import io
import json
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory

from experiments.publication import publish_file


HORIZONS = (50, 100, 200)
LATE_START = 151
ARMS = ('A', 'B', 'C')
FLOWS = ('food_need', 'food_eaten', 'food_unmet', 'harvest_total', 'harvest_private', 'harvest_public',
         'levied_food', 'levy_deposited_food', 'levy_handling_food', 'relief_received_food',
         'aid_sent_food', 'aid_received_food', 'depot_spoiled_food', 'private_spoiled_food', 'private_freight_food',
         'public_freight_food', 'public_farm_workers', 'private_farm_workers', 'mine_workers',
         'factory_workers', 'sector_workers', 'farm_workers_planned', 'farm_workers_total', 'farm_tools_used',
         'tools_needed', 'private_farm_slots', 'public_farm_slots', 'soil_before_farmer_weighted_sum',
         'equipment_farmer_weighted_sum', 'climate_farmer_weighted_sum', 'region_count',
         'no_taxable_surplus_regions', 'private_harvest_regions', 'private_harvest_no_surplus_regions')
POINTS = ('closing_population', 'private_close', 'public_open', 'public_close', 'farmland',
          'land_capacity', 'taxable_surplus_food')
FIELDS = (*FLOWS, *POINTS)


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def sustained_turns(flags, length=5):
    """Date a change from its first year, using length future-confirmed consecutive years.

    An episode starts with the first sustained True. False must then persist for the
    same number of years to mark a recovery. None interrupts a streak without proving
    a reversal. The initial state is outside the episode.
    """
    if length < 1:
        raise ValueError('The confirmation window must be positive')
    state, previous, streak = False, None, 0
    out = []
    for year, flag in enumerate(flags, start=1):
        if flag is None:
            previous, streak = None, 0
            continue
        if type(flag) is not bool:
            raise ValueError('Expected annual boolean observations or None')
        streak = streak + 1 if previous is flag else 1
        previous = flag
        if streak == length and state != flag:
            state = flag
            out.append({'state': flag, 'first_year': year-length+1, 'confirmed_year': year})
    return out


def reserve_window(records):
    """Convert closing stock to days at annual mean resident demand (365 days/year)."""
    if not records:
        raise ValueError('No annual observations')
    observed = [r for r in records if r['food_need'] > 0]
    days = [365*r['public_close']/r['food_need'] for r in observed]
    one_day = sum(365*r['public_close'] >= r['food_need'] for r in observed)
    change = records[-1]['public_close']-records[0]['public_open']
    maintained = one_day == len(records) if len(observed) == len(records) else None
    return {'years': len(records), 'demand_years': len(observed),
            'positive_years': sum(r['public_close'] > 0 for r in records), 'one_day_years': one_day,
            'minimum_days': min(days) if days else None,
            'pooled_days': _ratio(365 * sum(r['public_close'] for r in observed),
                                  sum(r['food_need'] for r in observed)),
            'net_stock_change': change, 'maintained_one_day': maintained,
            'maintained_without_net_drawdown': None if maintained is None else maintained and change >= 0}


def _distribution(values):
    valid = [v for v in values if v is not None]
    return {'observed': len(valid), 'min': min(valid), 'median': median(valid),
            'max': max(valid), 'mean': sum(valid)/len(valid)} if valid else {
                'observed': 0, 'min': None, 'median': None, 'max': None, 'mean': None}


def _ratios(totals):
    denominators = {
        'eaten_share': ('food_eaten', 'food_need'), 'unmet_share': ('food_unmet', 'food_need'),
        'harvest_to_need': ('harvest_total', 'food_need'),
        'private_harvest_to_need': ('harvest_private', 'food_need'),
        'public_fraction_of_harvest': ('harvest_public', 'harvest_total'),
        'net_levy_to_need': ('levy_deposited_food', 'food_need'),
        'harvest_per_active_farm_worker': ('harvest_total', 'farm_workers_total'),
        'active_fraction_of_planned_farm_workers': ('farm_workers_total', 'farm_workers_planned'),
        'farm_tool_use_to_need': ('farm_tools_used', 'tools_needed'),
        'farmer_weighted_soil_before': ('soil_before_farmer_weighted_sum', 'farm_workers_total'),
        'farmer_weighted_equipment': ('equipment_farmer_weighted_sum', 'farm_workers_total'),
        'farmer_weighted_climate': ('climate_farmer_weighted_sum', 'farm_workers_total'),
        'no_taxable_surplus_region_share': ('no_taxable_surplus_regions', 'region_count'),
        'no_surplus_among_private_harvesting_regions': ('private_harvest_no_surplus_regions', 'private_harvest_regions'),
    }
    return {name: _ratio(totals[a], totals[b]) for name, (a, b) in denominators.items()}


def _read(path):
    raw = path.read_bytes()
    worlds, countries = [], defaultdict(list)
    owners = None
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        for year, line in enumerate(stream, start=1):
            entry = json.loads(line)
            if entry['year'] != year:
                raise ValueError(f'Out-of-order year in {path.name}')
            world = {k: entry['world'][k] for k in FIELDS}
            local = {r['owner']: r for r in entry['countries']}
            if owners is None:
                owners = set(local)
            if len(local) != 8 or len(entry['countries']) != 8 or set(local) != owners:
                raise ValueError(f'Incomplete country panel in {path.name}')
            for k, value in world.items():
                if type(value) is not int or value < 0 or sum(r[k] for r in local.values()) != value:
                    raise ValueError(f'Country totals do not reconcile in {path.name}, year {year}, {k}')
            for cell in (world, *local.values()):
                if (cell['food_eaten'] + cell['food_unmet'] != cell['food_need']
                        or cell['harvest_private'] + cell['harvest_public'] != cell['harvest_total']
                        or cell['private_farm_workers'] + cell['public_farm_workers'] != cell['farm_workers_total']
                        or cell['private_harvest_no_surplus_regions'] > min(cell['private_harvest_regions'], cell['no_taxable_surplus_regions'])
                        or max(cell['private_harvest_regions'], cell['no_taxable_surplus_regions']) > cell['region_count']):
                    raise ValueError(f'Inconsistent food quantities in {path.name}, year {year}')
            worlds.append(world)
            if year >= LATE_START:
                for owner, row in local.items():
                    countries[owner].append({k: row[k] for k in ('public_open', 'public_close', 'food_need',
                        'food_unmet', 'closing_population', 'harvest_public', 'levy_deposited_food')})
    if len(worlds) != max(HORIZONS):
        raise ValueError(f'Expected 200 annual observations in {path.name}')
    return worlds, countries, sha256(raw).hexdigest()


def _history(flags):
    turns = sustained_turns(flags)
    at50 = [t for t in turns if t['confirmed_year'] <= 50]
    return {'first_onset': next((t['first_year'] for t in turns if t['state']), None),
            'confirmed_active_at_50': bool(at50 and at50[-1]['state']),
            'later_confirmed_turns': [t for t in turns if t['confirmed_year'] > 50]}


def _seed(worlds, countries):
    checkpoints = {}
    totals = Counter()
    for year, row in enumerate(worlds, start=1):
        totals.update({k: row[k] for k in FLOWS})
        if year in HORIZONS:
            checkpoints[year] = {'annual': row, 'cumulative': dict(totals)}

    predicates = {
        'zero_public_food': [r['public_close'] == 0 for r in worlds],
        'reserve_under_one_day': [365*r['public_close'] < r['food_need'] if r['food_need'] else None for r in worlds],
        'harvest_below_resident_need': [r['harvest_total'] < r['food_need'] for r in worlds],
        'zero_net_food_levy': [r['levy_deposited_food'] == 0 for r in worlds],
        'majority_private_harvest_no_taxable_surplus': [
            2*r['private_harvest_no_surplus_regions'] > r['private_harvest_regions']
            if r['private_harvest_regions'] else None for r in worlds]}
    late = worlds[LATE_START-1:]
    local = {}
    for owner, records in countries.items():
        need = sum(r['food_need'] for r in records)
        unmet = sum(r['food_unmet'] for r in records)
        local[owner] = {'reserve': reserve_window(records), 'unmet': unmet, 'need': need,
                        'unmet_share': _ratio(unmet, need), 'harvest_public': sum(r['harvest_public'] for r in records),
                        'net_food_levy': sum(r['levy_deposited_food'] for r in records),
                        'closing_population': records[-1]['closing_population']}
    return {'checkpoints': checkpoints, 'turns': {k: _history(v) for k, v in predicates.items()},
            'reserve': reserve_window(late), 'late_flows': {k: sum(r[k] for r in late) for k in FLOWS},
            'countries': local}


def _pooled(rows):
    pooled = {k: sum(r[k] for r in rows) for k in rows[0]}
    result = {'mean_per_seed': {k: v/len(rows) for k, v in pooled.items()}, 'pooled_ratios': _ratios(pooled)}
    if 'public_close' in pooled:
        result['pooled_ratios']['closing_public_days'] = _ratio(365*pooled['public_close'], pooled['food_need'])
        result['pooled_ratios']['closing_private_days'] = _ratio(365*pooled['private_close'], pooled['food_need'])
    return result


def _window_pool(windows):
    return {'windows': len(windows), 'positive_years': sum(w['positive_years'] for w in windows),
            'observed_calendar_years': sum(w['years'] for w in windows),
            'one_day_years': sum(w['one_day_years'] for w in windows),
            'observed_demand_years': sum(w['demand_years'] for w in windows),
            'maintained_one_day_windows': sum(w['maintained_one_day'] is True for w in windows),
            'maintained_without_net_drawdown_windows': sum(w['maintained_without_net_drawdown'] is True for w in windows),
            'unclassified_windows': sum(w['maintained_one_day'] is None for w in windows),
            'minimum_days_distribution': _distribution([w['minimum_days'] for w in windows]),
            'pooled_days_within_window_distribution': _distribution([w['pooled_days'] for w in windows])}


def _arm(source, seeds, arm):
    runs = [source[s, arm] for s in seeds]
    reports = {}
    for year in HORIZONS:
        cells = [r['checkpoints'][year] for r in runs]
        reports[year] = {period: _pooled([c[period] for c in cells]) for period in ('annual', 'cumulative')}
    late = {'world': _window_pool([r['reserve'] for r in runs]),
            'countries': _window_pool([c['reserve'] for r in runs for c in r['countries'].values()]),
            'flows': _pooled([r['late_flows'] for r in runs]),
            'worlds_maintaining_one_day': [s for s in seeds if source[s, arm]['reserve']['maintained_one_day']],
            'worlds_maintaining_without_net_drawdown': [s for s in seeds if source[s, arm]['reserve']['maintained_without_net_drawdown']]}
    turning = {}
    for condition in runs[0]['turns']:
        records = [r['turns'][condition] for r in runs]
        signed = {s: [t['first_year'] if t['state'] else -t['first_year'] for t in source[s, arm]['turns'][condition]['later_confirmed_turns']]
                  for s in seeds}
        turning[condition] = {
            'first_onset_year': _distribution([r['first_onset'] for r in records]),
            'active_at_50': sum(r['confirmed_active_at_50'] for r in records),
            'first_later_onset': _distribution([next((y for y in changes if y > 0), None) for changes in signed.values()]),
            'first_later_recovery': _distribution([next((-y for y in changes if y < 0), None) for changes in signed.values()]),
            'turns_confirmed_after_50_by_seed': signed}
    return {'checkpoints': reports, 'late_151_200': late, 'turning_points': turning}


def _pair_values(run, year):
    point = run['checkpoints'][year]
    annual, cumulative = point['annual'], point['cumulative']
    values = {k: annual[k] for k in ('closing_population', 'private_close', 'public_close')}
    values.update({'cumulative_' + k: v for k, v in cumulative.items()})
    values.update({'cumulative_' + k: v for k, v in _ratios(cumulative).items()})
    values['public_days'] = _ratio(365*annual['public_close'], annual['food_need'])
    if year == 200:
        values['late_positive_reserve_years'] = run['reserve']['positive_years']
        values['late_one_day_years'] = run['reserve']['one_day_years']
        values['late_minimum_days'] = run['reserve']['minimum_days']
    return values


def _signed(first, second):
    return {k: a-second[k] if a is not None and second[k] is not None else None for k,a in first.items()}


def _changes(values):
    return {**_distribution(values), 'increase': sum(v is not None and v > 0 for v in values),
            'decrease': sum(v is not None and v < 0 for v in values), 'tied': sum(v == 0 for v in values)}


def _cases(pairs, variable):
    """Choose the largest increase/decrease and first tie in a deterministic input order."""
    valid = [p for p in pairs if p['C'][variable] is not None and p['reference'][variable] is not None]
    diff = lambda p: p['C'][variable] - p['reference'][variable]
    high = max((p for p in valid if diff(p) > 0), key=diff, default=None)
    low = min((p for p in valid if diff(p) < 0), key=diff, default=None)
    tie = next((p for p in valid if diff(p) == 0), None)
    return {'largest_increase': high, 'largest_decrease': low, 'first_tie': tie}


def _pairs(source, seeds, reference):
    reports = {}
    for year in HORIZONS:
        pairs = []
        for s in seeds:
            a, b = (_pair_values(source[s, arm], year) for arm in ('C', reference))
            pairs.append({'seed': s, 'C': a, 'reference': b, 'delta': _signed(a, b)})
        metrics = {k: _changes([p['delta'][k] for p in pairs]) for k in pairs[0]['delta']}
        reports[year] = {'deltas': metrics}
        if year == max(HORIZONS):
            keep = ('closing_population', 'private_close', 'public_close', 'public_days', 'cumulative_food_need',
                    'cumulative_food_eaten', 'cumulative_food_unmet', 'cumulative_unmet_share',
                    'cumulative_harvest_private', 'cumulative_harvest_public', 'cumulative_levy_deposited_food')
            compact = [{'seed': p['seed'], **{arm: {k: p[arm][k] for k in keep} for arm in ('C', 'reference')}} for p in pairs]
            reports[year]['unmet_share_examples'] = _cases(compact, 'cumulative_unmet_share')
            reports[year]['unmet_share_deltas_by_seed'] = {p['seed']: p['delta']['cumulative_unmet_share'] for p in pairs}
    locals_ = []
    for s in seeds:
        a, b = (source[s, arm]['countries'] for arm in ('C', reference))
        if set(a) != set(b):
            raise ValueError('Country identities differ across arms')
        for owner in sorted(a):
            case = {'seed': s, 'owner': owner}
            for label, row in (('C', a[owner]), ('reference', b[owner])):
                case[label] = {k: v for k, v in row.items() if k != 'reserve'}
                case[label]['positive_reserve_years'] = row['reserve']['positive_years']
                case[label]['minimum_reserve_days'] = row['reserve']['minimum_days']
            locals_.append(case)
    national_diffs = [p['C']['unmet_share']-p['reference']['unmet_share'] for p in locals_
                      if p['C']['unmet_share'] is not None and p['reference']['unmet_share'] is not None]
    return {'checkpoints': reports, 'country_unmet_share_151_200': _changes(national_diffs),
            'country_examples_151_200': _cases(locals_, 'unmet_share')}


def summarize(study):
    """Read world and country totals only. Output is deterministic for the same 120 files."""
    study = Path(study)
    expected = {(s, arm): f'seed-{s:02}-{arm}-totals.jsonl.gz' for s in range(40) for arm in ARMS}
    if {p.name for p in study.glob('seed-*-*-totals.jsonl.gz')} != set(expected.values()):
        raise ValueError('Incomplete or unexpected aggregate input files')
    source, hashes = {}, {}
    for key, name in expected.items():
        worlds, countries, hashes[name] = _read(study / name)
        source[key] = _seed(worlds, countries)
    by_cohort = {}
    for sample, seeds in (('development', list(range(20))), ('validation', list(range(20,40)))):
        by_cohort[sample] = {'seeds': seeds, 'arms': {arm: _arm(source, seeds, arm) for arm in ARMS},
                             'paired_C_minus': {arm: _pairs(source, seeds, arm) for arm in ('A','B')}}
    return {'schema': 'food-reserve-trajectory/1', 'cohorts': by_cohort, 'source_sha256': hashes,
            'definitions': {
                'arms': 'A is the archived reference ordering. B prioritizes resident relief. C uses the reference ordering with the public-farm harvest allocation. C-minus-B therefore compares two complete policy paths.',
                'time': 'Each checkpoint gives that single year and cumulative flows through that year. Labor and land slots accumulated across years are worker-years and slot-years.',
                'days': '365 × closing public food / annual resident food need using uniform daily demand. Zero need has no day estimate. Stock days measure coverage, not delivered meals.',
                'persistence': 'A 151–200 window maintains a one-day floor if 365 × closing food ≥ need at all 50 observations with positive need each year. The stricter count also requires closing stock in 200 ≥ opening stock in 151. Both describe only the observed interval.',
                'stock_counts': 'All 50 year-end stocks contribute to positive_years. Only positive-demand observations contribute to one_day_years. A world and its countries are checked separately.',
                'aggregation': 'Cross-section and cumulative ratios divide sums across each 20-seed cohort. Paired C-minus-reference differences first compare within each seed; summary statistics give each comparable pair equal weight. Undefined ratios are excluded and counted via observed.',
                'taxable_surplus': 'At levy time compare private stock with the protected floor. Among private harvesters means region-years with positive private harvest, independent of the public share. The share is weighted by region-year appearances.',
                'labor': 'Public and private farm workers and effective farm slots partition agriculture. Physical farmland is counted separately. Soil, equipment and climate means weight by active farm workers. A paired allocation change does not isolate the same-state opportunity cost.',
                'turns': 'Five consecutive true years establish onset; five false years after onset establish recovery. First onset may predate year 51. For transitions confirmed in 51–200, positive/negative signed values date the first year of the onset/recovery run. Later brief fluctuations are ignored. A final unconfirmed transition is right-censored.',
                'cases': 'At year 200 an increase in cumulative unmet share represents a larger fraction of resident need left unmet. Examples give the largest increase, largest decrease and first exact tie; null means no observed example. Country cases evaluate only years 151–200.'}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    result = summarize(args.study)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=args.out.parent) as folder:
        stage = Path(folder) / 'summary.json'
        stage.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)+'\n', encoding='utf8', newline='\n')
        publish_file(stage, args.out)
    print('Summarized 24,000 world-years, 192,000 country-years and 120 trajectories.')


if __name__ == '__main__':
    main()
