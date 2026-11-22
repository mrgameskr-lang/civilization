"""Same-country, capacity-constrained shipments with freight provisions paid in food."""

from heapq import heappop, heappush

from .model import GOODS


def _require(ok, message):
    if not ok:
        raise ValueError(f"domestic logistics: {message}")


def _integer(value):
    return type(value) is int and value >= 0


def _edge(a, b):
    return (a, b) if a < b else (b, a)


def _cost(quantity, distance):
    return (quantity * distance + 99) // 100


def _targets(region):
    return {"food": region.population, "ore": region.population // 20, "tools": region.population // 40}


def _shortfall(target, stock):
    return {g: max(0, target[g] - stock[g]) for g in GOODS}


def _open(regions, roads, mode, width):
    _require(mode in ("limited", "unlimited"), "invalid mode")
    _require(width is None or type(width) is int and width > 0, "invalid map width")
    nodes, territory = {}, {}
    for r in sorted(regions, key=lambda r: r.id):
        _require(_integer(r.id) and r.id not in nodes, "duplicate or invalid region ID")
        _require(_integer(r.population) and _integer(r.owner), "invalid opening population or owner")
        _require(r.stock.keys() == set(GOODS) and all(_integer(v) for v in r.stock.values()),
                 "invalid opening stock")
        for tile in r.members:
            _require(_integer(tile) and tile not in territory, "invalid or overlapping territory")
            territory[tile] = r.id
        _require(territory.get(r.seat) == r.id, "seat is outside its region")
        targets = _targets(r)
        nodes[r.id] = {"id": r.id, "owner": r.owner, "population": r.population,
                       "targets": targets, "opening": r.stock.copy(), "closing": r.stock.copy(),
                       "imports": dict.fromkeys(GOODS, 0), "exports": dict.fromkeys(GOODS, 0),
                       "transit": dict.fromkeys(GOODS, 0), "cost_food": 0,
                       "unmet_before": _shortfall(targets, r.stock)}
    seats = {r.id: r.seat for r in regions}
    edges, adj = {}, {k: [] for k in nodes}
    for r in sorted(roads, key=lambda r: (r.a, r.b)):
        a, b, path = r.a, r.b, tuple(r.path)
        _require(a in nodes and b in nodes and a < b and (a, b) not in edges, "invalid road endpoints")
        _require(nodes[a]["owner"] == nodes[b]["owner"], "road crosses national border")
        _require(_integer(r.capacity) and _integer(r.distance) and r.distance > 0, "invalid road capacity or length")
        _require(len(path) == r.distance + 1 and path[0] == seats[a] and path[-1] == seats[b],
                 "physical route does not connect seats at stated distance")
        _require(len(set(path)) == len(path), "repeated tile in road")
        crossed = False
        for tile in path:
            current = territory.get(tile)
            _require(current in (a, b) and not (crossed and current == a), "road strays outside its two regions")
            crossed = current == b
        if width is not None:
            for u, v in zip(path, path[1:]):
                ux, uy = u % width, u // width
                vx, vy = v % width, v // width
                _require(abs(ux - vx) + abs(uy - vy) == 1, "nonadjacent road tiles")
        edges[a, b] = {"a": a, "b": b, "distance": r.distance, "capacity": r.capacity,
                       "used": 0, "remaining": r.capacity if mode == "limited" else None, "cost_food": 0}
        adj[a].append(b)
        adj[b].append(a)
    paths = {(r.a, r.b): tuple(r.path) for r in roads}
    return nodes, edges, adj, paths


def _routes(buyer, adj, edges):
    """From the buyer, rank simple paths by minimum freight for one unit, then tile distance."""
    queue = [(0, 0, (buyer,))]
    settled = set()
    while queue:
        one_unit_cost, distance, reverse_path = heappop(queue)
        node = reverse_path[-1]
        if node in settled:
            continue
        settled.add(node)
        if node != buyer:
            yield tuple(reversed(reverse_path))
        for nxt in adj[node]:
            edge = edges[_edge(node, nxt)]
            if nxt not in settled and edge["remaining"] != 0:
                leg = edge["distance"]
                heappush(queue, (one_unit_cost + _cost(1, leg), distance + leg, (*reverse_path, nxt)))


def _affordable(source, good, need, route):
    stock, target = source["closing"], source["targets"]
    surplus = stock[good] - target[good]
    food_budget = stock["food"] - target["food"]
    if surplus <= 0 or food_budget <= 0:
        return 0
    high = min(need, surplus, *(e["remaining"] for e in route if e["remaining"] is not None))
    low = 0
    while low < high:
        trial = (low + high + 1) // 2
        freight = sum(_cost(trial, e["distance"]) for e in route)
        if freight + (trial if good == "food" else 0) <= food_budget:
            low = trial
        else:
            high = trial - 1
    return low


def _shipment(path, good, quantity, edges, paths):
    legs, tile_path = [], []
    for a, b in zip(path, path[1:]):
        key = _edge(a, b)
        distance = edges[key]["distance"]
        tiles = paths[key] if a < b else tuple(reversed(paths[key]))
        tile_path.extend(tiles if not tile_path else tiles[1:])
        legs.append({"a": a, "b": b, "distance": distance, "cost_food": _cost(quantity, distance)})
    return {"source": path[0], "target": path[-1], "good": good, "quantity": quantity,
            "path": list(path), "tile_path": tile_path, "legs": legs,
            "cost_food": sum(e["cost_food"] for e in legs), "distance": len(tile_path) - 1}


def _post(nodes, edges, shipment):
    good, qty = shipment["good"], shipment["quantity"]
    seller, buyer = nodes[shipment["source"]], nodes[shipment["target"]]
    seller["closing"][good] -= qty
    buyer["closing"][good] += qty
    seller["exports"][good] += qty
    buyer["imports"][good] += qty
    seller["closing"]["food"] -= shipment["cost_food"]
    seller["cost_food"] += shipment["cost_food"]
    for region in shipment["path"][1:-1]:
        nodes[region]["transit"][good] += qty
    for leg in shipment["legs"]:
        e = edges[_edge(leg["a"], leg["b"])]
        e["used"] += qty
        e["cost_food"] += leg["cost_food"]
        if e["remaining"] is not None:
            e["remaining"] -= qty


def ship(regions, roads, mode="limited", *, width=None):
    """Move goods, audit against original stocks, then publish the new regional stocks."""
    regions, roads = list(regions), list(roads)
    nodes, edges, adj, paths = _open(regions, roads, mode, width)
    shipments = []
    delivered = dict.fromkeys(GOODS, 0)
    for good in GOODS:
        buyers = sorted(nodes, key=lambda k: (nodes[k]["closing"][good] - nodes[k]["targets"][good], k))
        for buyer in buyers:
            need = nodes[buyer]["targets"][good] - nodes[buyer]["closing"][good]
            while need > 0:
                for path in _routes(buyer, adj, edges):
                    route = [edges[_edge(a, b)] for a, b in zip(path, path[1:])]
                    qty = _affordable(nodes[path[0]], good, need, route)
                    if qty:
                        s = _shipment(path, good, qty, edges, paths)
                        _post(nodes, edges, s)
                        shipments.append(s)
                        delivered[good] += qty
                        need -= qty
                        break
                else:
                    break
    for node in nodes.values():
        node["unmet_after"] = _shortfall(node["targets"], node["closing"])
    trace = {"mode": mode, "nodes": list(nodes.values()), "roads": list(edges.values()),
             "shipments": shipments, "delivered": delivered, "cost_food": sum(s["cost_food"] for s in shipments)}
    audit_logistics(regions, roads, trace, width=width)
    for region in regions:
        region.stock = nodes[region.id]["closing"].copy()
    return trace


def audit_logistics(regions, roads, trace, *, width=None):
    """Verify independently against pre-shipment regional states and trusted physical road definitions."""
    regions, roads = list(regions), list(roads)
    nodes, edges, _, paths = _open(regions, roads, trace["mode"], width)
    delivered = dict.fromkeys(GOODS, 0)
    last_good = 0
    for s in trace["shipments"]:
        path, good, qty = s["path"], s["good"], s["quantity"]
        _require(type(path) is list and len(path) >= 2 and len(set(path)) == len(path)
                 and all(k in nodes for k in path), "invalid regional route")
        _require(s["source"] == path[0] and s["target"] == path[-1], "invalid counterparties")
        _require(good in GOODS and GOODS.index(good) >= last_good and _integer(qty) and qty > 0,
                 "invalid good, priority, or quantity")
        last_good = GOODS.index(good)
        seller, buyer = nodes[path[0]], nodes[path[-1]]
        _require(seller["closing"][good] - qty >= seller["targets"][good], "shipment consumed local reserve")
        _require(buyer["closing"][good] + qty <= buyer["targets"][good], "shipment exceeds demand")
        _require(len(s["legs"]) == len(path) - 1, "wrong number of legs")
        cost, total_distance, tile_path = 0, 0, []
        for idx, (a, b) in enumerate(zip(path, path[1:])):
            key = _edge(a, b)
            _require(key in edges, "shipment uses a missing road")
            edge = edges[key]
            distance = edge["distance"]
            leg_cost = (qty * distance + 99) // 100
            _require(s["legs"][idx] == {"a": a, "b": b, "distance": distance, "cost_food": leg_cost},
                     "incorrect leg cost/distance/endpoint")
            flat = paths[key] if a < b else tuple(reversed(paths[key]))
            tile_path.extend(flat if idx == 0 else flat[1:])
            cost += leg_cost
            total_distance += distance
            edge["used"] += qty
            edge["cost_food"] += leg_cost
            if edge["remaining"] is not None:
                edge["remaining"] -= qty
                _require(edge["remaining"] >= 0, "road capacity exceeded")
        _require(s["tile_path"] == tile_path and s["cost_food"] == cost and s["distance"] == total_distance,
                 "false path, shipment cost, or total distance")
        for k in path[1:-1]:
            nodes[k]["transit"][good] += qty
        delivered[good] += qty
        seller["closing"][good] -= qty
        seller["closing"]["food"] -= cost
        _require(seller["closing"]["food"] >= seller["targets"]["food"], "freight consumed residents' rations")
        seller["exports"][good] += qty
        seller["cost_food"] += cost
        buyer["closing"][good] += qty
        buyer["imports"][good] += qty
    balance = {}
    for n in nodes.values():
        n["unmet_after"] = _shortfall(n["targets"], n["closing"])
        total = balance.setdefault(n["owner"], dict.fromkeys(GOODS, 0))
        for g in GOODS:
            _require(n["closing"][g] >= 0, "negative regional stock")
            total[g] += n["closing"][g] - n["opening"][g]
        total["food"] += n["cost_food"]
    _require(all(v == 0 for nation in balance.values() for v in nation.values()), "national goods balance")
    _require(trace["nodes"] == list(nodes.values()) and trace["roads"] == list(edges.values()), "posting mismatch")
    _require(trace["delivered"] == delivered and trace["cost_food"] == sum(n["cost_food"] for n in nodes.values()),
             "shipment totals mismatch")
