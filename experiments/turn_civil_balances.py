"""Read settled civilian accounts for one year and compare matching annual records."""
from civsim.model import GOODS
from experiments.unit_economy_metrics import civil_totals


def _quantity(value):
    if type(value) is not int or value < 0:
        raise ValueError(f'Expected a nonnegative integer quantity, received {value!r}')
    return value


def _road_totals(edges, regions, fiscal):
    seen = set()
    world = {'road_used': 0, 'road_remaining': 0}
    for edge in edges:
        a, b = edge['a'], edge['b']
        key = tuple(sorted((a, b)))
        if a == b or key in seen or a not in regions or b not in regions:
            raise ValueError('Duplicate or invalid domestic road')
        seen.add(key)
        if fiscal:
            left = _quantity(edge['unused'])
            used = _quantity(_quantity(edge['capacity']) - left)
        else:
            left = edge['remaining']
            if left is not None:
                left = _quantity(left)
            used = _quantity(edge['used'])
        for totals in (world, regions[a], regions[b]):
            totals['road_used'] += used
            if totals['road_remaining'] is None or left is None:
                totals['road_remaining'] = None
            else:
                totals['road_remaining'] += left
    return world


def turn_civil_balances(record):
    """Return world totals and local observations keyed by integer region ID.

    Cargo is privately delivered domestic cargo, counted once at the destination.
    Relief is food delivered to residents, including local depot distributions. Meals
    count actual personal consumption. Stocks, resident population and cash are closing
    balances. Each region sees all incident domestic road use and residual capacity;
    the world counts each road once. Unlimited capacity and unavailable fiscal
    observations (older regional records) are represented by None.
    """
    meals_and_cargo = civil_totals(record)
    government = record.get('government')
    fiscal = government is not None
    regions = {}
    for region in record['regions']:
        i = region['id']
        private = meals_and_cargo['regions'][i]
        unmet = _quantity(region['consumption']['food_unmet'])
        if unmet + private['food_eaten'] != region['consumption']['food_need']:
            raise ValueError('Resident unmet need does not reconcile with meals')
        regions[i] = {
            'owner': private['owner'], 'private_shipments': private['received'],
            'food_eaten': private['food_eaten'], 'food_unmet': unmet,
            'government_stock': None, 'relief_delivered': 0 if fiscal else None,
            'road_used': 0, 'road_remaining': 0,
            'population': _quantity(region['closing']['population']), 'cash': _quantity(region['closing']['cash']),
        }
    stocks, relief = None, None
    if fiscal:
        stocks = dict.fromkeys(GOODS, 0)
        for depot in government['depots']:
            i = depot['region']
            if i not in regions or regions[i]['government_stock'] is not None:
                raise ValueError('Duplicate depot or unknown region')
            quantities = {g: _quantity(depot['closing'][g]) for g in GOODS}
            regions[i]['government_stock'] = quantities
            for g in GOODS:
                stocks[g] += quantities[g]
        if any(r['government_stock'] is None for r in regions.values()):
            raise ValueError('Missing regional depot closing balance')
        for shipment in government['relief']['shipments']:
            target = shipment['target']
            if target not in regions:
                raise ValueError('Unknown relief recipient region')
            regions[target]['relief_delivered'] += _quantity(shipment['quantity'])
        relief = sum(r['relief_delivered'] for r in regions.values())
        if relief != _quantity(government['relief']['delivered']):
            raise ValueError('Delivered relief does not match receipts')

    roads = government['roads'] if fiscal else record['domestic']['roads']
    world = _road_totals(roads, regions, fiscal)
    for name in ('population', 'cash', 'food_unmet', 'food_eaten'):
        world[name] = sum(r[name] for r in regions.values())
    world.update(private_shipments=meals_and_cargo['world']['received'], government_stock=stocks,
                 relief_delivered=relief)
    return {'year': record['year'], 'world': world, 'regions': regions}


def _delta(first, second):
    result = {}
    for key, previous in first.items():
        current = second[key]
        if key == 'owner':
            if previous != current:
                raise ValueError('Region ownership differs between paired records')
            result[key] = current
        elif previous is None or current is None:
            result[key] = None
        elif isinstance(previous, dict):
            result[key] = {g: current[g] - previous[g] for g in GOODS}
        else:
            result[key] = current - previous
    return result


def paired_civil_delta(first, second):
    """Return signed second-minus-first differences for the same year and region IDs."""
    if first['year'] != second['year']:
        raise ValueError('Paired years differ')
    a, b = turn_civil_balances(first), turn_civil_balances(second)
    if a['regions'].keys() != b['regions'].keys():
        raise ValueError('Paired region IDs differ')
    return {'year': a['year'], 'world': _delta(a['world'], b['world']),
            'regions': {i: _delta(r, b['regions'][i]) for i, r in a['regions'].items()}}
