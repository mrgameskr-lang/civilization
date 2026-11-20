"""Spatial annual transitions with local working states and transactional publication."""
from dataclasses import dataclass, fields, replace
from typing import Literal

from .audit import BalanceError
from .border import border_market, move_people, validate_border_paths
from .economy import BASE_PRICES, consume
from .logistics import ship
from .model import GOODS, climate_factor
from .regional_production import audit_production, produce_regions
from .regions import audit_regions, sync_nations


@dataclass(frozen=True, slots=True)
class RegionalPolicy:
    logistics: Literal["limited", "unlimited"] = "limited"
    investment_scope: Literal["regional", "national"] = "regional"
    soil_care: bool = True
    closed_roads: tuple[tuple[int, int], ...] = ()

    def __post_init__(self):
        if self.logistics not in ("limited", "unlimited") or self.investment_scope not in ("regional", "national"):
            raise ValueError("unknown regional policy")
        if type(self.soil_care) is not bool or not isinstance(self.closed_roads, tuple):
            raise ValueError("invalid soil or road policy")
        for edge in self.closed_roads:
            if (type(edge) is not tuple or len(edge) != 2 or any(type(i) is not int for i in edge)
                    or not 0 <= edge[0] < edge[1]):
                raise ValueError("road closure needs an ordered pair of distinct region IDs")
        if tuple(sorted(set(self.closed_roads))) != self.closed_roads:
            raise ValueError("road closures must be unique and sorted")


def state(region):
    # Physical membership and road paths live once in world.json.
    row = {f.name: getattr(region, f.name) for f in fields(region) if f.name != "members"}
    row["stock"] = region.stock.copy()
    row["capital"] = {k: ages.copy() for k, ages in region.capital.items()}
    return row


def _copy(region):
    return replace(region, stock=region.stock.copy(), capital={k: v.copy() for k, v in region.capital.items()})


def _check(condition, message):
    if not condition:
        raise BalanceError(message)


def audit_borders(regions, borders, market, production_close, transport_open):
    stock = {i: r["stock"].copy() for i, r in production_close.items()}
    cash = {i: r["cash"] for i, r in production_close.items()}
    by_id = {r.id: r for r in regions}
    routes = {tuple(sorted((b.a, b.b))): b for b in borders}
    free = {key: road.capacity for key, road in routes.items()}
    quote = {q["region"]: q for q in market["quotes"]}
    for i, region in by_id.items():
        p = region.population
        targets = {"food": p + p//8, "ore": p//20, "tools": p//40}
        prices = {g: max(b//4, min(4*b, b*targets[g]//max(1, stock[i][g]))) for g,b in BASE_PRICES.items()}
        _check(quote[i]["targets"] == targets and quote[i]["prices"] == prices, "border quote")
    for t in market["trades"]:
        a, b, g, q = t["seller"], t["buyer"], t["good"], t["quantity"]
        key = tuple(sorted((a, b)))
        _check(key in routes and by_id[a].owner != by_id[b].owner and g in GOODS, "invalid border pair")
        _check(type(q) is int and 0 < q <= free[key], "border road over capacity")
        fee = (q * routes[key].distance + 99) // 100
        price = (quote[a]["prices"][g] + quote[b]["prices"][g]) // 2
        _check(t["distance"] == routes[key].distance and t["cost_food"] == fee, "border freight cost")
        _check(t["unit_price"] == price and t["value"] == price*q and cash[b] == t["buyer_cash_before"]
               and cash[b] >= q*price, "border settlement")
        _check(stock[a][g] - quote[a]["targets"][g] >= q and quote[b]["targets"][g] - stock[b][g] >= q,
               "border excess supply or demand")
        stock[a][g] -= q
        stock[b][g] += q
        stock[a]["food"] -= fee
        _check(stock[a]["food"] >= by_id[a].population, "border freight spent local rations")
        cash[a] += price*q
        cash[b] -= price*q
        free[key] -= q
    for i in stock:
        _check(transport_open[i] == (stock[i], cash[i]), "border posting differs from next stage")


def _audit_residents(regions, opening, meals, vital, moves, roads, delivered):
    edges = {tuple(sorted((e.a, e.b))): e.distance for e in roads}
    inbound = dict.fromkeys(opening, 0)
    outbound = inbound.copy()
    for move in moves:
        a, b, q = move["source"], move["target"], move["people"]
        _check(edges.get(tuple(sorted((a, b)))) == move["distance"] and type(q) is int and q > 0,
               "migration outside a passable road")
        inbound[b] += q
        outbound[a] += q
    for r in regions:
        i, p = r.id, opening[r.id]["population"]
        meal, d, stock = meals[i], vital[i], delivered[i]
        eaten = min(p, stock["food"])
        spoil = (stock["food"] - eaten) // 12
        _check(meal["food_eaten"] == eaten and meal["food_need"] == p and meal["food_unmet"] == p-eaten
               and meal["food_spoiled"] == spoil, "regional consumption")
        _check(r.stock == {**stock, "food": stock["food"] - eaten - spoil}, "regional goods after meals")
        births, deaths = 28*eaten//1000, (12*p + 110*(p-eaten))//1000
        _check(d["births"] == births and d["deaths"] == deaths and d["immigrants"] == inbound[i]
               and d["emigrants"] == outbound[i] and outbound[i] <= d["requested_departures"]
               and inbound[i] <= d["host_capacity"] and r.population == p+births-deaths+inbound[i]-outbound[i],
               "regional population balance")


def audit_national_year(record, *, private_transfers=None):
    """Post flows to independent opening country accounts, then match consolidated closes."""
    groups = {c["id"]: [] for c in record["countries"]}
    for r in record["regions"]:
        _check(r["owner"] in groups and r["opening"]["owner"] == r["closing"]["owner"] == r["owner"],
               "unknown or changing region owner")
        groups[r["owner"]].append(r)
    for c in record["countries"]:
        group = groups[c["id"]]
        _check(bool(group), "empty country account")
        for boundary in ("opening", "closing"):
            country = c[boundary]
            locals_ = [r[boundary] for r in group]
            _check(all(country[k] == sum(r[k] for r in locals_)
                       for k in ("population", "deposit", "cash", "land", "farmland"))
                   and all(country["stock"][g] == sum(r["stock"][g] for r in locals_) for g in GOODS),
                   "country endpoint disagrees with regional quantities")
            _check(country["soil"] == sum(r["soil"]*r["land"] for r in locals_)//country["land"]
                   and all(country["capital"][k] == [sum(ages) for ages in zip(
                       *(r["capital"][k] for r in locals_), strict=True)] for k in country["capital"]),
                   "country endpoint disagrees with regional soil or capital")
    balances = {c["id"]: {**c["opening"]["stock"], "cash": c["opening"]["cash"],
                          "population": c["opening"]["population"], "deposit": c["opening"]["deposit"]}
                for c in record["countries"]}
    owners = {r["id"]: r["owner"] for r in record["regions"]}
    if private_transfers is not None:
        for region, transfer in private_transfers.items():
            for good in GOODS:
                balances[owners[region]][good] += transfer[good]
    for r in record["regions"]:
        b = balances[r["owner"]]
        prod, meal, d = r["production"], r["consumption"], r["demography"]
        for good in GOODS:
            b[good] += prod["produced"][good] - prod["used"][good] - meal["used"][good]
        b["deposit"] -= prod["produced"]["ore"]
        b["population"] += d["births"] - d["deaths"]
    for t in record["border_market"]["trades"]:
        seller, buyer = balances[owners[t["seller"]]], balances[owners[t["buyer"]]]
        seller[t["good"]] -= t["quantity"]
        buyer[t["good"]] += t["quantity"]
        seller["food"] -= t["cost_food"]
        seller["cash"] += t["value"]
        buyer["cash"] -= t["value"]
    for s in record["domestic"]["shipments"]:
        owner = owners[s["source"]]
        _check(owners[s["target"]] == owner, "domestic shipment crossed a national boundary")
        balances[owner]["food"] -= s["cost_food"]
    for m in record["moves"]:
        balances[owners[m["source"]]]["population"] -= m["people"]
        balances[owners[m["target"]]]["population"] += m["people"]
    for c in record["countries"]:
        close, balance = c["closing"], balances[c["id"]]
        _check(close["stock"] == {g: balance[g] for g in GOODS}
               and all(close[k] == balance[k] for k in ("cash", "population", "deposit")),
               f"independent national flow balance failed: {c['id']}")


def step_regional(world, year, policy=RegionalPolicy(), *, diagnose_capacity=False):
    if type(year) is not int or year != world.year + 1:
        raise ValueError("expected the next consecutive year")
    audit_regions(world)
    validate_border_paths(world.regions, world.borders, world.width)
    closed = set(policy.closed_roads)
    if not closed.issubset({tuple(sorted((r.a, r.b))) for r in world.roads}):
        raise ValueError("closure specifies a nonexistent domestic road")
    roads = [r for r in world.roads if tuple(sorted((r.a, r.b))) not in closed]
    trial = replace(world, regions=[_copy(r) for r in world.regions], nations=[_copy(n) for n in world.nations])
    local = trial.regions
    opening = {r.id: state(r) for r in local}
    climate = {n.id: climate_factor(world.seed, year, n.id) for n in trial.nations}
    prod = produce_regions(local, climate, policy.investment_scope, policy.soil_care)
    produced = {r.id: state(r) for r in local}
    audit_production(opening, produced, prod, climate, policy.investment_scope, policy.soil_care)
    market = border_market(local, world.borders)
    before_ship = {r.id: (r.stock.copy(), r.cash) for r in local}
    audit_borders(local, world.borders, market, produced, before_ship)
    if diagnose_capacity:
        shadow = [replace(r, stock=r.stock.copy()) for r in local]
        other_mode = "unlimited" if policy.logistics == "limited" else "limited"
        ship(shadow, roads, other_mode, width=world.width)
    freight = ship(local, roads, policy.logistics, width=world.width)
    delivered = {r.id: r.stock.copy() for r in local}
    meals = {r.id: consume(r) for r in local}
    available_roads = [*roads, *world.borders]
    vital, moves = move_people(local, meals, available_roads)
    _audit_residents(local, opening, meals, vital, moves, available_roads, delivered)
    sync_nations(trial)
    audit_regions(trial)
    _check(sum(n.cash for n in trial.nations) == sum(n.cash for n in world.nations), "world cash changed")
    record = {"year": year,
              "countries": [{"id": n.id, "opening": state(old), "closing": state(n)}
                            for old, n in zip(world.nations, trial.nations, strict=True)],
              "regions": [{"id": r.id, "owner": r.owner, "opening": opening[r.id], "climate": climate[r.owner],
                           "production": prod[r.id], "consumption": meals[r.id], "demography": vital[r.id],
                           "closing": state(r)} for r in local],
              "border_market": market, "domestic": freight, "moves": moves}
    if diagnose_capacity:
        record["capacity_diagnostic"] = [{"region": r.id, "actual_unmet": meals[r.id]["food_unmet"],
                                          "other_unmet": max(0, opening[r.id]["population"] - r.stock["food"])}
                                         for r in shadow]
    audit_national_year(record)
    world.regions, world.nations, world.year = local, trial.nations, year
    return record
