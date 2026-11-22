"""Split the existing crop into private and public harvests from disjoint farm work.

One field slot supports one productive farmer in the regional production kernel.
Both shares use the year's common climate, soil, equipment and already-paid wear.
The public account receives only the marginal harvest of its assigned workers.
"""

from math import prod

from .fiscal_policy import _bounds
from .model import GOODS


VERSION = 'public-harvest/1'
DENOMINATOR = 10 * 1000**7


def _count(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(f'invalid {name}')
    return value


def _goods(stock):
    if not isinstance(stock, dict) or stock.keys() != set(GOODS):
        raise ValueError('invalid harvest inventory')
    return {good: _count(stock[good], good) for good in GOODS}


def harvest_row(region_id, owner, production, opening_depot, depot_before):
    """Reconstruct a single region's harvest without changing any of its inputs.

    The year-opening depot triggers work. The depot immediately before harvest
    provides the current storage headroom. The full production record still
    represents the gross crop, before the two owners receive their respective shares.
    """
    p = production
    region_id, owner = _count(region_id, 'region ID'), _count(owner, 'owner')
    initial = _goods(opening_depot)
    depot = _goods(depot_before)
    private = _goods(p['closing_stock'])
    population = _count(p['population'], 'population')
    active = _count(p['active_farmers'], 'active crop workers')
    capacity = _count(p['land_capacity'], 'field capacity')
    farmland = _count(p['farmland'], 'farmland tiles')
    added = _count(p['investment']['added_land_capacity'], 'improved field capacity')
    if (active != _count(p['active_labor']['farm'], 'working farmers') or active > capacity
            or capacity != 20 * farmland + added or added > 4 * farmland):
        raise ValueError('crop workers and field capacity disagree')

    factors = {k: _count(p[k], k) for k in (
        'productivity', 'technology', 'fertility', 'soil_before', 'climate', 'equipment')}
    factors['farm_multiplier'] = _count(p['investment']['farm_multiplier'], 'farm multiplier')
    numerator = 32 * prod(factors.values())
    full = active * numerator // DENOMINATOR
    if full != _count(p['produced']['food'], 'posted harvest') or private['food'] < full:
        raise ValueError('posted crop differs from physical yield or gross inventory')

    target = population // 8
    store_limit = _bounds(population)[1]['food']
    headroom = max(0, min(target, store_limit) - depot['food'])
    worker_limit = active // 8 if initial['food'] < target else 0
    public_workers = 0
    if worker_limit and headroom and full:
        # F(private_workers) must retain at least gross - headroom whole food units.
        keep = max(0, full - headroom)
        minimum_private_workers = (keep * DENOMINATOR + numerator - 1) // numerator
        public_workers = min(worker_limit, active - minimum_private_workers)
    private_food = (active - public_workers) * numerator // DENOMINATOR
    public_food = full - private_food
    if not public_food:
        public_workers = 0

    return {
        'id': region_id, 'owner': owner, 'population': population,
        'annual_open_food': initial['food'], 'reserve_target': target, 'storage_limit': store_limit,
        'headroom': headroom, 'eligible_worker_limit': worker_limit,
        'farmland_tiles': farmland, 'capacity_slots': capacity, 'unused_slots': capacity - active,
        'workers_total': active, 'workers_public': public_workers, 'workers_private': active - public_workers,
        'slots_total': active, 'slots_public': public_workers, 'slots_private': active - public_workers,
        'yield_factors': factors, 'yield_numerator': numerator, 'yield_denominator': DENOMINATOR,
        'food_total': full, 'food_private': private_food, 'food_public': public_food,
        'rounding_food': public_food - public_workers * numerator // DENOMINATOR,
        'private_before': private, 'private_after': {**private, 'food': private['food'] - public_food},
        'depot_before': depot, 'depot_after': {**depot, 'food': depot['food'] + public_food},
    }


def apply_public_harvest(regions, production, depots, opening_depots):
    """Assign each gross crop once after production and before trade or collection.

    Compute and validate all entries before posting. Only the live stock accounts
    change. The regional production trace and the separate year-opening depot
    snapshot are retained for independent replay.
    """
    homes = {}
    for region in regions:
        if region.id in homes:
            raise ValueError('duplicate harvest region')
        homes[region.id] = region
    if not homes.keys() == production.keys() == depots.keys() == opening_depots.keys():
        raise ValueError('regional harvest accounts differ')
    rows = []
    for i, r in sorted(homes.items()):
        p = production[i]
        if r.population != p['population'] or r.stock != p['closing_stock']:
            raise ValueError('live private store or population differs from the gross production boundary')
        rows.append(harvest_row(i, r.owner, p, opening_depots[i], depots[i]))
    for row in rows:
        if row['food_public']:
            i = row['id']
            homes[i].stock = row['private_after'].copy()
            depots[i] = row['depot_after'].copy()
    return {'version': VERSION, 'regions': rows}
