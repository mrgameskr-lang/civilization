"""Read settled civilian deliveries and resident consumption from one existing annual ledger."""

from civsim.model import GOODS


def _count(value, label):
    if type(value) is not int or value < 0:
        raise ValueError(f'invalid {label}: {value!r}')
    return value


def _empty():
    return {'sent': dict.fromkeys(GOODS, 0), 'received': dict.fromkeys(GOODS, 0), 'food_eaten': 0}


def _add(total, part):
    total['food_eaten'] += part['food_eaten']
    for good in GOODS:
        total['sent'][good] += part['sent'][good]
        total['received'][good] += part['received'][good]


def _check_receipt(reported, counted, label):
    if reported.keys() != counted.keys() or any(
        _count(reported[g], label) != counted[g] for g in GOODS
    ):
        raise ValueError(f'{label} disagrees with private domestic shipment endpoints')


def civil_totals(record):
    """Return year, regions and countries (integer IDs), and world, without changing the input.

    Each private domestic invoice contributes its cargo once to its origin's ``sent``
    and once to its destination's ``received``. These are two views of the same goods.
    Transit, freight provisions, international trade and public transfers are excluded.
    ``food_eaten`` counts personal meals from all sources after the delivery stages.
    """
    regions, countries = {}, {}
    for nation in record['countries']:
        owner = _count(nation['id'], 'country ID')
        if owner in countries:
            raise ValueError('duplicate country ID')
        countries[owner] = _empty()

    for entry in record['regions']:
        home = _count(entry['id'], 'region ID')
        owner = _count(entry['owner'], 'region owner')
        if home in regions or owner not in countries:
            raise ValueError('duplicate region or unknown owner')
        meal = entry['consumption']
        eaten = _count(meal['food_eaten'], 'food eaten')
        if eaten != min(_count(meal['food_need'], 'food need'), _count(meal['opening_food'], 'meal stock')):
            raise ValueError('resident meals disagree with food need and meal stock')
        regions[home] = {**_empty(), 'owner': owner, 'food_eaten': eaten}

    freight = record['domestic']
    for invoice in freight['shipments']:
        source = _count(invoice['source'], 'dispatch region')
        target = _count(invoice['target'], 'delivery region')
        if source == target or source not in regions or target not in regions:
            raise ValueError('invalid domestic shipment endpoints')
        if regions[source]['owner'] != regions[target]['owner']:
            raise ValueError('private domestic shipment crosses a country boundary')
        quantity = _count(invoice['quantity'], 'cargo quantity')
        good = invoice['good']
        if quantity == 0 or good not in GOODS:
            raise ValueError('invalid private cargo')
        regions[source]['sent'][good] += quantity
        regions[target]['received'][good] += quantity

    seen = set()
    for node in freight['nodes']:
        home = _count(node['id'], 'transport node')
        if home in seen or home not in regions or _count(node['owner'], 'transport owner') != regions[home]['owner']:
            raise ValueError('duplicate transport node or unknown region/owner')
        seen.add(home)
        _check_receipt(node['exports'], regions[home]['sent'], 'regional dispatches')
        _check_receipt(node['imports'], regions[home]['received'], 'regional deliveries')
    if seen != regions.keys():
        raise ValueError('incomplete domestic transport receipts')

    for row in regions.values():
        _add(countries[row['owner']], row)
    world = _empty()
    for row in countries.values():
        _add(world, row)
    _check_receipt(freight['delivered'], world['received'], 'total deliveries')
    return {'year': record['year'], 'regions': regions, 'countries': countries, 'world': world}
