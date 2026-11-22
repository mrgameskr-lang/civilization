"""Retrospective civilian crop inputs and a one-worker, fixed-inventory calculation."""

import argparse
from collections import Counter
import gzip
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .food_yield_factors import FACTORS, crop_yield
from .publication import publish_file


FIELDS = ('year', 'region', 'farm_workers_total', 'farm_workers_planned', 'sector_workers', 'mine_workers',
          'factory_workers', 'farmland', 'land_capacity', 'farm_tools_used', 'tools_needed', 'harvest_total',
          'soil_before', 'soil_after', *FACTORS)
BANDS = ((50, 50), (100, 100), (200, 200), (151, 200))


def regional_practices(r, first, previous_soil):
    """Account once for existing material inputs and compute a single labor substitution."""
    active, planned = r['farm_workers_total'], r['farm_workers_planned']
    soil, slots, fields = r['soil_before'], r['land_capacity'], r['farmland']
    gross, used, needed = r['harvest_total'], r['farm_tools_used'], r['tools_needed']
    if (active != min(slots, planned) or not 20 * fields <= slots <= 24 * fields
            or active + r['mine_workers'] + r['factory_workers'] != r['sector_workers']):
        raise ValueError('farm labor or field balance differs')
    if (not 0 <= used <= needed == (active + 29) // 30 or r['equipment'] != 1000 + 150 * used // max(1, needed)
            or gross != crop_yield(r, active, soil)):
        raise ValueError('recorded wear, equipment factor or gross crop differs')
    capital, remainder = divmod(r['farm_multiplier'] - 1000, 12)
    if capital < 0 or remainder:
        raise ValueError('farm multiplier is inconsistent with the regional equipment rule')

    erosion = 8 * active // max(1, slots)
    natural = max(550, min(1150, soil + 6 - erosion)) if fields else soil
    local_gain = r['soil_after'] - natural
    # The planner buys the minimum integer packages to achieve its realized repair.
    packages = (local_gain * fields + 63) // 64
    treated = min(fields, 8 * packages)
    if (local_gain < 0 or (local_gain and (soil >= 950 or not fields))
            or local_gain != min(max(0, 1000 - natural), 8 * treated // max(1, fields))):
        raise ValueError('observed soil recovery is incompatible with paid local care')
    public_soil = 0
    if previous_soil is not None and soil != previous_soil:
        expected = min(max(0, 1150 - previous_soil), 24 * min(12, fields) // max(1, fields))
        if soil - previous_soil != expected or expected <= 0:
            raise ValueError('production-time soil differs from the previous close and the public repair rule')
        public_soil = 1

    extra = int(active < slots and r['factory_workers'] > 0)
    candidate_workers = active + extra
    candidate_need = (candidate_workers + 29) // 30
    diluted = 1000 + 150 * used // max(1, candidate_need)
    option = crop_yield({**r, 'equipment': diluted}, candidate_workers, soil) - gross
    extra_erosion = 8 * candidate_workers // max(1, slots) - erosion

    return {
        'region_years': 1, 'active_crop_workers': active, 'planned_crop_workers': planned,
        'positive_farm_region_years': int(active > 0), 'occupied_slots': active, 'total_slots': slots,
        'binding_land_region_years': int(planned > slots), 'planned_workers_above_capacity': planned - active,
        'farmland_tiles': fields, 'improved_slots': slots - 20 * fields,
        'occupied_improved_slots': max(0, active - 20 * fields), 'gross_food': gross,
        'observed_food_minus_no_improved_slots': gross - crop_yield(r, min(active, 20 * fields), soil),
        'wear_tools': used, 'tools_for_full_equipment': needed,
        'partial_equipment_region_years': int(used < needed), 'operated_farm_assets': capital,
        'farm_asset_upkeep_tools': capital, 'observed_food_minus_no_sector_tool_wear':
            gross - crop_yield({**r, 'equipment': 1000}, active, soil),
        'observed_food_minus_no_farm_asset_bonus': gross - crop_yield({**r, 'farm_multiplier': 1000}, active, soil),
        'local_soil_packages': packages, 'local_soil_ore': packages, 'local_soil_tools': packages,
        'local_soil_workers': 4 * packages, 'public_soil_known_region_years': int(previous_soil is not None),
        'public_soil_packages': public_soil, 'public_soil_ore': 2 * public_soil,
        'public_soil_tools': 2 * public_soil, 'public_soil_workers': 4 * public_soil,
        'worker_weighted_soil_sum': active * soil, 'worker_weighted_technology_sum': active * r['technology'],
        'worker_weighted_productivity_sum': active * r['productivity'],
        'technology_changed_region_years': int(r['technology'] != first['technology']),
        'productivity_changed_region_years': int(r['productivity'] != first['productivity']),
        'territorial_farmland_changed_region_years': int(fields != first['farmland']),
        'option_factory_worker_years': extra, 'option_additional_tools': 0, 'option_food_change': option,
        'option_positive_region_years': int(extra and option > 0),
        'option_zero_region_years': int(extra and option == 0), 'option_negative_region_years': int(extra and option < 0),
        'option_increases_erosion_region_years': int(extra_erosion > 0),
    }


def _read_seed(path, seed, tallies):
    first, prior = {}, {}
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        head = json.loads(stream.readline())
        columns = head['columns']
        if (head.get('seed') != seed or head.get('arm') != 'A' or head.get('schema') != 'food-flow/1'
                or len(columns) != len(set(columns)) or not set(FIELDS).issubset(columns)):
            raise ValueError('unexpected PR25 region header')
        indices = {key: columns.index(key) for key in FIELDS}
        for year in range(1, 201):
            observed = set()
            for raw in json.loads(stream.readline()):
                if len(raw) != len(columns):
                    raise ValueError('invalid column count')
                r = {k: raw[i] for k, i in indices.items()}
                if any(type(v) is not int or v < 0 for v in r.values()) or r['year'] != year:
                    raise ValueError('invalid region inputs or year')
                i = r['region']
                if i in observed or (year > 1 and i not in first):
                    raise ValueError('unknown or repeated region')
                observed.add(i)
                if year == 1:
                    first[i] = r
                result = regional_practices(r, first[i], prior.get(i))
                for lo, hi in BANDS:
                    if lo <= year <= hi:
                        tallies[lo, hi].update(result)
                prior[i] = r['soil_after']
            if len(observed) != 32 or observed != first.keys():
                raise ValueError('incomplete PR25 regional panel')
        if stream.readline():
            raise ValueError('unexpected trailing year')


def diagnose(study):
    cohorts = {name: {band: Counter() for band in BANDS} for name in ('development', 'holdout')}
    fingerprints = {}
    for seed in range(40):
        path = Path(study) / f'seed-{seed:02}-A-regions.jsonl.gz'
        fingerprints[path.name] = sha256(path.read_bytes()).hexdigest()
        _read_seed(path, seed, cohorts['development' if seed < 20 else 'holdout'])
    return {
        'schema': 'crop-practices/1', 'source_arm': 'A', 'input_sha256': fingerprints,
        'audited_region_years': 256000,
        'cohorts': {name: [{'first_year': a, 'last_year': b, 'seeds': 20, **by_band[a, b]}
                           for a, b in BANDS] for name, by_band in cohorts.items()},
        'interpretation': {
            'units': 'Absolute sums over the stated worlds and years. Food/ore/tools are goods, labor is worker-years, land capacity is worker-slots. Soil and technology indices are per mille.',
            'saturation': 'Land binds when planned farmers exceed productive field slots. Unoccupied slots alone do not imply available labor or equipment.',
            'sector_tools': 'Actual farm tool wear; full coverage needs ceil(active farmers/30). The no-wear comparison removes its yield factor at the same actual labor, soil, climate, and capital.',
            'assets': 'PR25 regional production applies +12 permille per operating farm asset. Annual upkeep costs one tool/unit; a new asset costs eight tools, eight ore, six worker-years and first operates in the following year. Installed/build counts are not inferred from annual operation.',
            'land': 'Each reclamation unit costs ten tools, six ore and twelve worker-years to build and one tool/year to operate. It can add up to 24 slots within the regional tile ceiling. Occupied improved slots are measured against the original twenty slots per farmland tile.',
            'soil': 'Private local care packages are reconstructed from actual closing soil minus natural change: minimum packages = ceil(realized gain × farmland/64). Each costs one ore, one tool and four worker-years after harvest preparation; its repair affects closing soil. A public soil project costs two ore, two tools and four worker-years; an observed rise from last closing soil to field-time soil must match the public treatment formula.',
            'technology': 'Changes compare each region with its own first observation. Labor-weighted indices may move when regional employment changes even if regional levels remain fixed.',
            'one_worker_option': 'Conditionally reassign one observed factory worker in every region with an unoccupied slot. Pay one factory worker-year and use only already consumed farm tools; recompute coverage and wear dilution for the larger crew. Include all qualifying cases, even negative crop changes. Extra erosion is tested before the soil clamp. Ore, tools and land are not created.',
            'limits': 'This option is a one-season agricultural arithmetic comparison. The raw panel does not identify how much manufacturing output a displaced employee would forgo, the financing of additional future capital, or multiyear soil/market responses. Crop comparisons with no wear, no asset bonus and no improved land overlap and must not be added. Taxes occur downstream of gross harvest.',
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.out.exists():
            raise FileExistsError(args.out)
        result = diagnose(args.study)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=args.out.parent) as staging:
            file = Path(staging) / 'diagnosis.json'
            file.write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode())
            publish_file(file, args.out)
    except (ValueError, OSError, KeyError, EOFError) as exc:
        parser.exit(1, f'crop diagnosis failed: {exc}\n')
    print(f"Checked {result['audited_region_years']} regional crops across 40 archived worlds")


if __name__ == '__main__':
    main()
