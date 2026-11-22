"""Connected tile regions, physical road paths, and national account consolidation."""

from collections import defaultdict, deque
from dataclasses import dataclass, fields

from .investment import ASSETS, LIFE, InvestingNation
from .model import GOODS, Nation, Tile, World


@dataclass(slots=True)
class Region(InvestingNation):
    owner: int
    members: tuple[int, ...]
    seat: int
    farmland: int
    fertility_remainder: int = 0
    ore_grade_remainder: int = 0


@dataclass(slots=True)
class RegionalNation(InvestingNation):
    farmland: int


@dataclass(frozen=True, slots=True)
class Road:
    a: int
    b: int
    distance: int
    capacity: int
    path: tuple[int, ...]


@dataclass(slots=True)
class RegionalWorld:
    seed: int
    width: int
    height: int
    tiles: list[Tile]
    nations: list[RegionalNation]
    regions: list[Region]
    roads: list[Road]
    borders: list[Road]
    year: int = 0


def _require(valid, message):
    if not valid:
        raise ValueError(message)


def _count(number):
    return type(number) is int and number >= 0


def _zero_capital():
    return {asset: [0] * LIFE for asset in ASSETS}


def _split(total, weights):
    """Largest-remainder integer apportionment. Earlier region IDs win ties."""
    _require(_count(total), "cannot apportion noninteger or negative balance")
    if total == 0:
        return [0] * len(weights)
    denominator = sum(weights)
    _require(denominator > 0, "a positive balance needs a positive allocation weight")
    portions = [divmod(total * w, denominator) for w in weights]
    shares = [q for q, _ in portions]
    remainder_order = sorted(range(len(weights)), key=lambda i: (-portions[i][1], i))
    for i in remainder_order[:total-sum(shares)]:
        shares[i] += 1
    return shares


def _neighbors(tile, width, height):
    x, y = tile % width, tile // width
    if y:
        yield tile - width
    if x:
        yield tile - 1
    if x + 1 < width:
        yield tile + 1
    if y + 1 < height:
        yield tile + width


def _tree(start, allowed, width, height):
    distance = {start: 0}
    parent = {start: None}
    frontier = deque([start])
    while frontier:
        tile = frontier.popleft()
        for neighbor in _neighbors(tile, width, height):
            if neighbor in allowed and neighbor not in distance:
                distance[neighbor] = distance[tile] + 1
                parent[neighbor] = tile
                frontier.append(neighbor)
    return distance, parent


def _partition(tiles, count, width, height):
    """Center seat, then farthest seats on the owner's actual tile graph."""
    land = len(tiles)
    sum_x, sum_y = sum(t % width for t in tiles), sum(t // width for t in tiles)
    first = min(tiles, key=lambda t: (abs((t % width)*land-sum_x) + abs((t // width)*land-sum_y), t))
    seats = [first]
    nearest, _ = _tree(first, tiles, width, height)
    _require(len(nearest) == land, "national territory must be connected")
    while len(seats) < min(count, land):
        seat = min(tiles, key=lambda t: (-nearest[t], t))
        seats.append(seat)
        distances, _ = _tree(seat, tiles, width, height)
        nearest = {tile: min(old, distances[tile]) for tile, old in nearest.items()}
    # BFS assigns each tile through a predecessor that already belongs to its region.
    labels = {seat: i for i, seat in enumerate(seats)}
    frontier = deque(seats)
    while frontier:
        tile = frontier.popleft()
        for neighbor in _neighbors(tile, width, height):
            if neighbor in tiles and neighbor not in labels:
                labels[neighbor] = labels[tile]
                frontier.append(neighbor)
    groups = [[] for _ in seats]
    for tile in sorted(tiles):
        groups[labels[tile]].append(tile)
    return zip(seats, groups)


def _national_regions(n, members, all_tiles, width, height, count, first_id):
    result, geological = [], []
    fertility_offset = n.fertility - sum(all_tiles[t].fertility for t in members) // len(members)
    grade_offset = n.ore_grade - sum(all_tiles[t].ore_grade for t in members) // len(members)
    for i, (seat, group) in enumerate(_partition(members, count, width, height)):
        land = len(group)
        fertility, fertility_remainder = divmod(sum(all_tiles[t].fertility for t in group), land)
        grade, grade_remainder = divmod(sum(all_tiles[t].ore_grade for t in group), land)
        fertility += fertility_offset
        grade += grade_offset
        geological.append(sum(all_tiles[t].deposit for t in group))
        accessible = max(58, min(98, (70 if i == 0 else 90) + (fertility - n.fertility) // 10))
        farmland = max(1, (land * accessible + 50) // 100)
        result.append(Region(id=first_id+i, name=f"{n.name} {i+1}", owner=n.id, members=tuple(group),
                             seat=seat, farmland=farmland, land=land, fertility=fertility, ore_grade=grade,
                             productivity=n.productivity, technology=n.technology, soil=n.soil,
                             population=0, cash=0, deposit=0, stock=dict.fromkeys(GOODS, 0),
                             capital=_zero_capital(), fertility_remainder=fertility_remainder,
                             ore_grade_remainder=grade_remainder))
    settlement = [r.land * (165 if i == 0 else 86) * (850 + r.ore_grade // 5) for i,r in enumerate(result)]
    farming = [r.farmland * r.fertility for r in result]
    mining = [r.land * r.ore_grade for r in result]
    for field, amount, weights in (("population", n.population, settlement), ("cash", n.cash, settlement),
                                   ("deposit", n.deposit, geological), ("food", n.stock["food"], farming),
                                   ("ore", n.stock["ore"], mining), ("tools", n.stock["tools"], settlement)):
        for r, value in zip(result, _split(amount, weights)):
            if field in GOODS:
                r.stock[field] = value
            else:
                setattr(r, field, value)
    if isinstance(n, InvestingNation):
        _check_capital(n.capital)
        for asset in ASSETS:
            for age, quantity in enumerate(n.capital[asset]):
                # Place inherited facilities on accessible tiles, keeping the local class cap.
                for _ in range(quantity):
                    available = [r for r in result if sum(r.capital[asset]) < (r.land + 5) // 6]
                    _require(available, "inherited national facilities exceed regional capacity")
                    target = max(available, key=lambda r: (r.land - 6 * sum(r.capital[asset]), -r.id))
                    target.capital[asset][age] += 1
    return result


def _crossings(labels, width, height):
    pairs = defaultdict(list)
    for tile, a in enumerate(labels):
        for neighbor in _neighbors(tile, width, height):
            b = labels[neighbor]
            if a < b:
                pairs[a,b].append((tile, neighbor))
    return pairs


def _toward_seat(tile, parent):
    path = []
    while tile is not None:
        path.append(tile)
        tile = parent[tile]
    return path


def _roads(world, labels):
    trees = [_tree(r.seat, set(r.members), world.width, world.height) for r in world.regions]
    for (a,b), boundary in sorted(_crossings(labels, world.width, world.height).items()):
        dist_a, parents_a = trees[a]
        dist_b, parents_b = trees[b]
        t, u = min(boundary, key=lambda pair: (dist_a[pair[0]]+dist_b[pair[1]], *pair))
        path = tuple([*_toward_seat(t, parents_a)[::-1], *_toward_seat(u, parents_b)])
        distance = len(path) - 1
        capacity = max(1, (120 + 40 * len(boundary)) * 10 // (4 + distance))
        edges = world.roads if world.regions[a].owner == world.regions[b].owner else world.borders
        edges.append(Road(a, b, distance, capacity, path))


def regionalize(world: World, regions_per_nation: int = 4) -> RegionalWorld:
    _require(type(regions_per_nation) is int and regions_per_nation > 0, "regions_per_nation must be positive")
    w = RegionalWorld(world.seed, world.width, world.height, list(world.tiles), [], [], [], [], world.year)
    _require(w.width > 0 and w.height > 0 and len(w.tiles) == w.width*w.height, "map dimension mismatch")
    members = defaultdict(set)
    for i, tile in enumerate(w.tiles):
        _require((tile.x,tile.y) == (i % w.width, i // w.width), "expected row-major tile coordinates")
        members[tile.owner].add(i)
    _require(set(members) == set(range(len(world.nations))), "missing or unknown national territory")
    for i, n in enumerate(world.nations):
        _require(n.id == i and n.land == len(members[i]), "invalid national ID or land balance")
        group = _national_regions(n, members[i], w.tiles, w.width, w.height, regions_per_nation, len(w.regions))
        w.regions.extend(group)
        data = {f.name: getattr(n, f.name) for f in fields(Nation)}
        data["stock"] = n.stock.copy()
        capital = {k: list(v) for k,v in n.capital.items()} if isinstance(n, InvestingNation) else _zero_capital()
        w.nations.append(RegionalNation(**data, farmland=sum(r.farmland for r in group), capital=capital))
    labels = [0] * len(w.tiles)
    for r in w.regions:
        for t in r.members:
            labels[t] = r.id
    _roads(w, labels)
    audit_geography(w)
    audit_regions(w)
    return w


def _check_capital(capital):
    _require(isinstance(capital, dict) and capital.keys() == set(ASSETS), "missing capital class")
    for ages in capital.values():
        _require(isinstance(ages, list) and len(ages) == LIFE and all(_count(x) for x in ages),
                 "invalid capital age accounts")


def _check_account(account):
    numeric = ("land", "farmland", "population", "cash", "deposit", "soil",
               "fertility", "ore_grade", "technology", "productivity")
    _require(all(_count(getattr(account, k)) for k in numeric),
             "invalid regional or national quantity")
    _require(account.land > 0 and account.farmland <= account.land, "invalid farmland area")
    _require(isinstance(account.stock,dict) and account.stock.keys() == set(GOODS)
             and all(_count(x) for x in account.stock.values()), "invalid stock quantities")
    _check_capital(account.capital)


def _group_accounts(world):
    groups = [[] for _ in world.nations]
    for i,r in enumerate(world.regions):
        _require(_count(r.id) and r.id == i and _count(r.owner) and r.owner < len(groups), "invalid regional ID or owner")
        _check_account(r)
        _require(r.land == len(r.members), "land and member tile count differ")
        _require(all(_count(value) and value < r.land for value in (r.fertility_remainder, r.ore_grade_remainder)),
                 "invalid regional intensity remainder")
        groups[r.owner].append(r)
    for i,n in enumerate(world.nations):
        _require(_count(n.id) and n.id == i and groups[i], "invalid or empty national account")
    return groups


def _totals(group):
    values = {k: sum(getattr(r,k) for r in group) for k in ("land","farmland","population","cash","deposit")}
    for k in ("soil", "technology", "productivity", "fertility", "ore_grade"):
        numerator = sum(getattr(r, k) * r.land for r in group)
        if k in ("fertility", "ore_grade"):
            numerator += sum(getattr(r, f"{k}_remainder") for r in group)
        values[k] = numerator // values["land"]
    values["stock"] = {g: sum(r.stock[g] for r in group) for g in GOODS}
    values["capital"] = {kind: [sum(r.capital[kind][age] for r in group) for age in range(LIFE)]
                         for kind in ASSETS}
    return values


def sync_nations(world: RegionalWorld) -> None:
    """Rebuild national totals after region-level changes. Regional accounts are authoritative."""
    groups = _group_accounts(world)
    for n, group in zip(world.nations, groups):
        for k, value in _totals(group).items():
            setattr(n, k, value)


def audit_regions(world: RegionalWorld) -> None:
    """Check current stocks, people, currency, land, mineral reserves, soil and capital cohorts."""
    groups = _group_accounts(world)
    for n, group in zip(world.nations, groups):
        _check_account(n)
        for k, expected in _totals(group).items():
            _require(getattr(n,k) == expected, f"nation {n.id}: {k} disagrees with regional accounts")


def audit_geography(world: RegionalWorld) -> None:
    """Expensive static validation of the tile partition, regional connectivity and all routes."""
    w, h = world.width, world.height
    _require(w > 0 and h > 0 and len(world.tiles) == w*h, "invalid tile count")
    labels = [-1] * len(world.tiles)
    for i,r in enumerate(world.regions):
        _require(r.id == i and _count(r.owner) and r.owner < len(world.nations), "invalid region identity")
        _require(isinstance(r.members,tuple) and r.land == len(r.members) and r.seat in r.members,
                 "invalid region seat or territory size")
        for t in r.members:
            _require(_count(t) and t < len(labels) and labels[t] == -1, "duplicate or unknown member tile")
            tile = world.tiles[t]
            _require((tile.x,tile.y,tile.owner) == (t%w,t//w,r.owner), "tile coordinate or ownership mismatch")
            labels[t] = i
        distance, _ = _tree(r.seat, set(r.members), w, h)
        _require(len(distance) == r.land, "disconnected regional territory")
    _require(-1 not in labels, "unassigned tile")
    expected = set(_crossings(labels, w, h))
    seen = set()
    for foreign, roads in ((False,world.roads),(True,world.borders)):
        for road in roads:
            a,b,path = road.a, road.b, road.path
            _require(_count(a) and _count(b) and (a,b) in expected and (a,b) not in seen, "invalid or repeated road")
            seen.add((a,b))
            ra,rb = world.regions[a],world.regions[b]
            _require((ra.owner != rb.owner) == foreign, "domestic/border route misclassified")
            _require(_count(road.capacity) and road.capacity > 0 and _count(road.distance)
                     and road.distance > 0 and len(path) == road.distance+1, "invalid road capacity or distance")
            _require(path[0] == ra.seat and path[-1] == rb.seat and len(set(path)) == len(path),
                     "road has incorrect endpoints or loops")
            _require(all(_count(t) and t < len(labels) for t in path), "unknown road tile")
            crossings = 0
            for t,u in zip(path,path[1:]):
                _require(u in _neighbors(t,w,h) and labels[u] in (a,b), "road jump or third region")
                crossings += int(labels[t] != labels[u])
            _require(crossings == 1, "road must cross one common boundary")
    _require(seen == expected, "missing route between adjacent regions")
