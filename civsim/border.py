"""Bilateral foreign trade and demographic migration along actual adjacent roads."""
from .demography import _local_balance
from .economy import BASE_PRICES
from .model import GOODS


def validate_border_paths(regions, borders, width):
    """Validate foreign roads against the live partition before goods or people use them."""
    owners = {r.id: r.owner for r in regions}
    seats = {r.id: r.seat for r in regions}
    tiles = {tile: r.id for r in regions for tile in r.members}
    seen = set()
    for road in borders:
        a, b, path = road.a, road.b, road.path
        if (a not in owners or b not in owners or a >= b or owners[a] == owners[b] or (a,b) in seen
                or type(road.capacity) is not int or road.capacity < 0 or type(road.distance) is not int
                or road.distance < 1 or len(path) != road.distance + 1 or len(set(path)) != len(path)
                or path[0] != seats[a] or path[-1] != seats[b]):
            raise ValueError("invalid international road")
        seen.add((a, b))
        crossed = False
        for previous, tile in zip(path, path[1:]):
            region = tiles.get(tile)
            distance = abs(previous % width - tile % width) + abs(previous // width - tile // width)
            if distance != 1 or region not in (a, b) or (crossed and region == a):
                raise ValueError("international road leaves adjacent tiles or its two regions")
            crossed = region == b


def border_market(regions, borders):
    by_id = {r.id: r for r in regions}
    targets = {r.id: {"food": r.population + r.population // 8, "ore": r.population // 20,
                      "tools": r.population // 40} for r in regions}
    quotes = {r.id: {g: max(b // 4, min(4*b, b * targets[r.id][g] // max(1, r.stock[g])))
                     for g, b in BASE_PRICES.items()} for r in regions}
    free = {(r.a, r.b): r.capacity for r in borders}
    trades = []
    for good in GOODS:
        offers = []
        for road in borders:
            for seller, buyer in ((road.a, road.b), (road.b, road.a)):
                if (by_id[seller].population and by_id[buyer].population
                        and by_id[seller].stock[good] > targets[seller][good]
                        and by_id[buyer].stock[good] < targets[buyer][good]):
                    offers.append((-quotes[buyer][good], buyer, quotes[seller][good], seller, road))
        for _, buyer_id, _, seller_id, road in sorted(offers, key=lambda t: t[:4]):
            buyer, seller = by_id[buyer_id], by_id[seller_id]
            price = (quotes[buyer_id][good] + quotes[seller_id][good]) // 2
            excess = seller.stock[good] - targets[seller_id][good]
            demand = targets[buyer_id][good] - buyer.stock[good]
            food_spare = seller.stock["food"] - seller.population
            if good == "food":
                affordable_freight = 100 * excess // (100 + road.distance)
            else:
                affordable_freight = 100 * food_spare // road.distance
            key = road.a, road.b
            qty = min(excess, demand, buyer.cash // price, free[key], affordable_freight)
            if qty <= 0:
                continue
            freight = (qty * road.distance + 99) // 100
            before = buyer.cash
            seller.stock[good] -= qty
            seller.stock["food"] -= freight
            buyer.stock[good] += qty
            buyer.cash -= qty * price
            seller.cash += qty * price
            free[key] -= qty
            trades.append({"seller": seller_id, "buyer": buyer_id, "good": good, "quantity": qty,
                           "distance": road.distance, "cost_food": freight, "unit_price": price,
                           "value": qty * price, "buyer_cash_before": before})
    return {"trades": trades, "quotes": [{"region": r.id, "targets": targets[r.id], "prices": quotes[r.id]}
                                        for r in regions]}


def move_people(regions, meals, roads):
    vital = {r.id: _local_balance(r, meals[r.id]) for r in regions}
    neighbors = {r.id: [] for r in regions}
    for road in roads:
        neighbors[road.a].append((road.b, road.distance))
        neighbors[road.b].append((road.a, road.distance))
    donors = sorted(vital, key=lambda i: (-vital[i]["pressure_permille"], i))
    moves = []
    for i in donors:
        donor = vital[i]
        remaining = donor["requested_departures"]
        if not remaining:
            continue
        for j, distance in sorted(neighbors[i], key=lambda e: (vital[e[0]]["pressure_permille"], e[1], e[0])):
            host = vital[j]
            qty = min(remaining, host["host_capacity"] - host["immigrants"])
            if qty:
                donor["emigrants"] += qty
                host["immigrants"] += qty
                remaining -= qty
                moves.append({"source": i, "target": j, "people": qty, "distance": distance})
            if not remaining:
                break
    for r in regions:
        row = vital[r.id]
        r.population = row["population_before_migration"] + row["immigrants"] - row["emigrants"]
        row["closing_population"] = r.population
    return vital, moves
