"""Additional domestic household food relief from already funded public stocks.

Apply after ordinary relief and before private domestic trade. National intake
slots are spent when a delivery reaches households. Local handling is a limit
on the number accepted, with no invented material cost. The stage observes
the current private stock and any already-paid food due to households.
"""
from collections import Counter
from fractions import Fraction

from . import logistics
from .public_works import _affordable_rations, _opening, _relief_open
from .storage import canonical_line


VERSION = "emergency-relief/1"
UNFILLED = ("handling", "admin", "stock", "road", "freight")


def _require(ok, message):
    if not ok:
        raise ValueError("emergency relief: " + message)


def _quantity(q):
    return type(q) is int and q >= 0


def _index(rows, key):
    result = {key(row): row for row in rows}
    _require(len(result) == len(rows), "duplicate ordinary receipt")
    return result


def _ordinary_boundary(nodes, edges, capacity, ordinary, rations):
    """Bind the old private, road and admin closings to the new opening."""
    owners = {r.owner for r in nodes.values()}
    totals = _index(ordinary["admin"], lambda r: r["owner"])
    old_nodes = _index(ordinary["nodes"], lambda r: r["id"])
    old_edges = _index(ordinary["roads"], lambda e: (e["a"], e["b"]))
    _require(set(totals) == owners and old_nodes.keys() == nodes.keys() == rations.keys(),
             "incomplete regional or administrative opening")
    _require(old_edges.keys() == capacity.keys() == edges.keys(), "incomplete roads")
    delivered, used, road_use = Counter(), Counter(), Counter()
    for trip in ordinary["shipments"]:
        source, target, owner, q = trip["source"], trip["target"], trip["owner"], trip["quantity"]
        path = trip["path"]
        _require(trip["purpose"] == "relief" and trip["good"] == "food" and _quantity(q) and q > 0
                 and path and path[0] == source and path[-1] == target and len(path) == len(set(path))
                 and all(i in nodes and nodes[i].owner == owner for i in path), "invalid ordinary delivery")
        delivered[target] += q
        used[owner] += q
        for a, b in zip(path, path[1:]):
            edge = logistics._edge(a, b)
            _require(edge in edges, "unknown ordinary route")
            road_use[edge] += q
    _require(_quantity(ordinary["delivered"]) and sum(delivered.values()) == ordinary["delivered"],
             "ordinary food counted twice or omitted")
    for i, r in nodes.items():
        old = old_nodes[i]
        _require(_quantity(rations[i]) and rations[i] <= r.population, "invalid paid household food")
        _require(old["owner"] == r.owner and _quantity(old["private_food_open"])
                 and _quantity(old["private_food_close"])
                 and old["private_food_close"] == r.stock["food"] == old["private_food_open"] + delivered[i],
                 "private food differs from ordinary relief closing")
    for key, e in old_edges.items():
        _require(_quantity(e["capacity"]) and _quantity(e["remaining"])
                 and e["capacity"] - road_use[key] == e["remaining"] == capacity[key], "road opening discontinuity")
    limits = {}
    for owner, t in totals.items():
        _require(_quantity(t["limit"]) and _quantity(t["used"]) and t["used"] == used[owner] <= t["limit"],
                 "inconsistent ordinary administrative use")
        limits[owner] = t["limit"]
    _relief_open(nodes, edges, capacity, limits)
    return delivered, used, limits


def _local_dispatch(node, quantity):
    return {"source": node.id, "target": node.id, "good": "food", "quantity": quantity, "path": [node.id],
            "tile_path": [node.seat], "legs": [], "cost_food": 0, "distance": 0}


def _dispatch(target, approved, members, nodes, balances, edges, adj, paths, shipments):
    """Find physically feasible funded deliveries; recompute routes after every dispatch."""
    remaining = approved
    while remaining:
        if balances[target]:
            quantity = min(remaining, balances[target])
            trip = _local_dispatch(nodes[target], quantity)
        else:
            stocked = any(balances[i] > 0 for i in members)
            if not stocked:
                return approved - remaining, "stock"
            reachable_stock = False
            for path in logistics._routes(target, adj, edges):
                source = path[0]
                if not balances[source]:
                    continue
                reachable_stock = True
                legs = [edges[logistics._edge(a, b)] for a, b in zip(path, path[1:])]
                limit = min(remaining, *(e["remaining"] for e in legs))
                quantity = _affordable_rations(balances[source], limit, [e["distance"] for e in legs])
                if quantity:
                    trip = logistics._shipment(path, "food", quantity, edges, paths)
                    break
            else:
                return approved - remaining, "freight" if reachable_stock else "road"
        balances[trip["source"]] -= quantity + trip["cost_food"]
        for leg in trip["legs"]:
            edges[logistics._edge(leg["a"], leg["b"])]["remaining"] -= quantity
        shipments.append({**trip, "owner": nodes[target].owner, "purpose": "emergency_relief"})
        remaining -= quantity
    return approved, None


def _plan(regions, roads, depots, capacity, ordinary, rations, width):
    nodes, edges, adj, paths = _opening(regions, roads, depots, width)
    received_before, used_before, limits = _ordinary_boundary(nodes, edges, capacity, ordinary, rations)
    members = {owner: [] for owner in limits}
    gaps = {}
    for i, r in nodes.items():
        members[r.owner].append(i)
        gaps[i] = max(0, r.population - r.stock["food"] - rations[i])
    admin = {owner: limits[owner] - used_before[owner] for owner in limits}
    balances = {i: stock["food"] for i, stock in depots.items()}
    applications, shipments = [], []
    delivered = {}
    for owner, local in sorted(members.items()):
        for i in sorted(local, key=lambda k: (-Fraction(gaps[k], max(1, nodes[k].population)), -gaps[k], k)):
            r = nodes[i]
            limit = max(1, r.population // 16) if r.population else 0
            space = max(0, limit - received_before[i])
            intake = min(gaps[i], space)
            available = admin[owner]
            approved = min(intake, available)
            quantity, stop = _dispatch(i, approved, local, nodes, balances, edges, adj, paths, shipments)
            unfilled = dict.fromkeys(UNFILLED, 0)
            unfilled["handling"] = gaps[i] - intake
            unfilled["admin"] = intake - approved
            if stop is not None:
                unfilled[stop] = approved - quantity
            delivered[i] = quantity
            admin[owner] -= quantity
            applications.append({"region": i, "owner": owner, "population": r.population,
                                 "private_food": r.stock["food"], "household_rations": rations[i],
                                 "requested": gaps[i], "ordinary_received": received_before[i],
                                 "handling_limit": limit, "handling_remaining": space, "admin_available": available,
                                 "approved": approved, "dispatched": quantity, "received": quantity,
                                 "unfilled": unfilled})
    # Between ordinary and extra relief a different authorized expense may already have cleared.
    # Opening public stocks are therefore the caller's actual stocks at the latter boundary.
    receipt = {
        "version": VERSION, "applications": applications, "shipments": shipments,
        "nodes": [{"id": i, "owner": r.owner, "depot_open": depots[i].copy(),
                   "depot_close": {**depots[i], "food": balances[i]},
                   "private_food_open": r.stock["food"], "private_food_close": r.stock["food"] + delivered[i]}
                  for i, r in sorted(nodes.items())],
        "roads": [{"a": key[0], "b": key[1], "capacity": capacity[key], "remaining": e["remaining"]}
                  for key, e in sorted(edges.items())],
        "admin": [{"owner": owner, "limit": limit, "ordinary_used": used_before[owner],
                   "remaining_open": limit - used_before[owner], "used": limit - used_before[owner] - admin[owner],
                   "remaining": admin[owner]} for owner, limit in sorted(limits.items())],
        "delivered": sum(delivered.values()), "cost_food": sum(trip["cost_food"] for trip in shipments)}
    return receipt


def _balanced(trace):
    """Independently post actual trip quantities and costs against each local account."""
    spent, received, roads, admin = Counter(), Counter(), Counter(), Counter()
    for trip in trace["shipments"]:
        quantity = trip["quantity"]
        charge = 0
        for leg in trip["legs"]:
            fee = (quantity * leg["distance"] + 99) // 100
            _require(fee == leg["cost_food"], "per-leg fee")
            charge += fee
            roads[logistics._edge(leg["a"], leg["b"])] += quantity
        _require(charge == trip["cost_food"], "freight receipt")
        spent[trip["source"]] += quantity + charge
        received[trip["target"]] += quantity
        admin[trip["owner"]] += quantity
    for r in trace["nodes"]:
        i = r["id"]
        _require(r["private_food_close"] - r["private_food_open"] == received[i]
                 and r["depot_open"]["food"] - r["depot_close"]["food"] == spent[i]
                 and r["depot_close"]["food"] >= 0, "delivery receipts do not match food balances")
    for r in trace["applications"]:
        _require(received[r["region"]] == r["received"] == r["dispatched"] <= r["approved"]
                 and r["received"] + sum(r["unfilled"].values()) == r["requested"], "application coverage")
    for r in trace["roads"]:
        _require(r["capacity"] - roads[r["a"], r["b"]] == r["remaining"] >= 0, "road reconciliation")
    for r in trace["admin"]:
        _require(admin[r["owner"]] == r["used"] and r["remaining_open"] - r["used"] == r["remaining"] >= 0,
                 "administration reconciliation")
    _require(trace["delivered"] == sum(received.values()) and sum(spent.values()) == trace["delivered"] + trace["cost_food"],
             "world food reconciliation")


def audit_emergency_relief(regions, roads, depots, remaining_capacity, ordinary_relief, household_rations, trace, *, width):
    """Regenerate the complete receipt from the same trusted stage opening without posting."""
    expected = _plan(regions, roads, depots, remaining_capacity, ordinary_relief, household_rations, width)
    _require(canonical_line(trace) == canonical_line(expected), "receipt differs from the funded opening")
    _balanced(trace)


def execute_emergency_relief(regions, roads, depots, remaining_capacity, ordinary_relief, household_rations, *, width):
    """Return (receipt, residual capacities), committing only depot/private food on success."""
    trace = _plan(regions, roads, depots, remaining_capacity, ordinary_relief, household_rations, width)
    _balanced(trace)
    by_id = {r.id: r for r in regions}
    for r in trace["nodes"]:
        depots[r["id"]]["food"] = r["depot_close"]["food"]
        by_id[r["id"]].stock["food"] = r["private_food_close"]
    return trace, {(e["a"], e["b"]): e["remaining"] for e in trace["roads"]}
