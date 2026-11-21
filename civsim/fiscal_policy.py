"""National decision menus and local, in-kind tax postings for fiscal model 5.0A."""

from .economy import BASE_PRICES
from .logistics import _cost, _routes
from .model import GOODS
from .public_works import ROAD_BONUS, _affordable_rations


MODES = ("none", "relief", "infrastructure", "integrated")
ACTIONS = ("relief", "road", "soil", "reserve", "defer")
PERMITTED = {
    "none": {"defer"}, "relief": {"relief", "reserve", "defer"},
    "infrastructure": {"road", "soil", "reserve", "defer"}, "integrated": set(ACTIONS),
}


def _goods(food=0, ore=0, tools=0):
    return {"food": food, "ore": ore, "tools": tools}


def _budget(food=0, ore=0, tools=0, workers=0, admin_units=1):
    return {**_goods(food, ore, tools), "workers": workers, "admin_units": admin_units}


def _bounds(p):
    return _goods(p+p//8, p//64, p//64), _goods(p//4, p//32, p//32)


def relief_throughput(population):
    return max(1, population//32) if population > 0 else 0


def _candidate(mode, action, region, edge, qty, benefit, cost, budget, observed, reasons, loss=0):
    return {"action": action, "target_region": region, "target_edge": edge, "quantity": qty,
            "benefit_value": benefit, "cost_value": cost, "score": benefit-cost, "budget": budget,
            "inputs": observed, "constraints": reasons, "permitted": action in PERMITTED[mode], "population_loss": loss}


def _network(regions, roads, depots, road_units):
    neighbors = {r.id: [] for r in regions}
    edges = {}
    for road in roads:
        key = road.a, road.b
        if (road.a not in neighbors or road.b not in neighbors or road.a >= road.b or key in edges
                or road.distance <= 0 or road.capacity < 0):
            raise ValueError("invalid national fiscal road")
        capacity = road.capacity + ROAD_BONUS * road_units.get(key, 0)
        if not capacity:
            continue
        edges[key] = {"remaining": capacity, "distance": road.distance}
        neighbors[road.a].append(road.b)
        neighbors[road.b].append(road.a)
    result = {}
    for uid in neighbors:
        if uid in result:
            continue
        component, pending = {uid}, [uid]
        while pending:
            for other in neighbors[pending.pop()]:
                if other not in component:
                    component.add(other)
                    pending.append(other)
        food = sum(depots[i]["food"] for i in component)
        result.update(dict.fromkeys(component, food))
    return neighbors, edges, result


def _relief_forecast(target, need, depots, network):
    """Quote physical batches against opening roads and warehouses in isolation."""
    neighbors, opening, connected = network
    edges = {key: e.copy() for key, e in opening.items()}
    funds = {i: depots[i]["food"] for i in neighbors}
    allowance = min(2*need, connected[target])
    remaining, freight, trips = need, 0, []
    while remaining and allowance:
        routes = ((target,),) if funds[target] else _routes(target, neighbors, edges)
        for path in routes:
            source = path[0]
            legs = [edges[tuple(sorted(pair))] for pair in zip(path, path[1:])]
            distances = [leg["distance"] for leg in legs]
            cap = min([remaining, *(leg["remaining"] for leg in legs)])
            qty = _affordable_rations(min(allowance, funds[source]), cap, distances)
            if qty <= 0:
                continue
            fee = sum(_cost(qty, distance) for distance in distances)
            trips.append({"source": source, "path": list(path), "quantity": qty, "freight_food": fee})
            remaining -= qty
            freight += fee
            allowance -= qty + fee
            funds[source] -= qty + fee
            for leg in legs:
                leg["remaining"] -= qty
            break
        else:
            break
    return need-remaining, freight, trips


def _region_candidates(r, old, depots, network, throughput, risk, mode):
    depot = depots[r.id]
    p = r.population
    loss = max(0, -old["pop_delta"])
    unmet = old["unmet"]
    shortage = max(0, p-r.stock["food"])
    need = min(throughput, max(0, unmet), shortage)
    quantity, freight, trips = _relief_forecast(r.id, need, depots, network)
    yield _candidate(mode, "relief", r.id, None, quantity, 8*quantity, 8*freight,
                     _budget(food=quantity+freight),
                     {"previous_unmet": unmet, "connected_public_food": network[2][r.id], "throughput": throughput,
                      "opening_shortage": shortage, "estimated_routes": trips, "estimated_freight_food": freight},
                     [] if quantity else ["no_funded_prior_need"], loss)

    treated = min(12, r.farmland)
    gain = min(max(0, 1150-r.soil), 24*treated//max(1, r.farmland))
    extra_crop = old["food_output"]*gain//max(1, r.soil)
    pressure = max(unmet, old["food_need"]-old["food_output"], 0)
    reasons = []
    if not (r.soil < 950 or (r.soil < 1000 and old["soil_delta"] < 0)):
        reasons.append("soil_condition")
    if not gain:
        reasons.append("no_recovery")
    if depot["ore"] < 2 or depot["tools"] < 2 or p//2 < 4:
        reasons.append("local_materials_or_workers")
    yield _candidate(mode, "soil", r.id, None, 1, 3*8*min(pressure, extra_crop), 64,
                     _budget(ore=2, tools=2, workers=4),
                     {"soil": r.soil, "soil_delta": old["soil_delta"], "treated_tiles": treated,
                      "soil_gain": gain, "food_pressure": pressure, "extra_crop_per_year": extra_crop}, reasons, loss)

    protected, cap = _bounds(p)
    expected_surplus = max(0, r.stock["food"]+old["food_output"]-protected["food"])
    gross = min(p//16, max(0, cap["food"]-depot["food"]), expected_surplus//4)
    handling = (gross+31)//32
    stored = gross-handling
    spoil = stored//12
    insurance = stored*risk//1000
    yield _candidate(mode, "reserve", r.id, None, gross, 8*insurance, 8*(handling+spoil),
                     _budget(food=gross), {"expected_surplus": expected_surplus, "risk_permille": risk,
                     "projected_handling": handling, "projected_spoilage": spoil, "expected_usable_food": insurance},
                     [] if stored > 0 else ["no_reserve_headroom_or_surplus"], loss)


def _road_candidate(road, regions, previous, depots, road_units, road_use, mode):
    edge = (road.a, road.b)
    units = road_units.get(edge, 0)
    used = road_use.get(edge, 0)
    capacity = road.capacity + ROAD_BONUS*units
    pressure = max(previous[i]["unmet"] for i in edge)
    congestion = max(0, 4*used-3*capacity)
    directions = []
    for a, b in (edge, edge[::-1]):
        surplus = max(0, regions[a].stock["food"] + previous[a]["food_output"] - regions[a].population)
        deficit = min(previous[b]["unmet"], max(0, regions[b].population-regions[b].stock["food"]))
        cap = min(ROAD_BONUS, congestion, deficit)
        quantity = _affordable_rations(surplus, cap, [road.distance])
        directions.append({"source": a, "receiver": b, "forecast_surplus": surplus, "receiver_need": deficit,
                           "quantity": quantity, "freight_food": _cost(quantity,road.distance)})
    matched = max(directions, key=lambda d: d["quantity"]-d["freight_food"])
    benefit = 3*8*matched["quantity"]
    haul = (6*road.distance+99)//100 + (4*road.distance+99)//100
    upkeep_haul = 2*((road.distance+99)//100)
    cost = (6*4+4*12+6*8+haul*8) + 3*(4+12+8+upkeep_haul*8 + matched["freight_food"]*8)
    origins = [i for i,j in (edge,edge[::-1])
               if depots[i]["ore"]>=6 and depots[i]["tools"]>=4 and depots[i]["food"]>=haul
               and regions[j].population//2>=6]
    origin = min(origins, key=lambda i: (-(depots[i]["tools"]+depots[i]["ore"]), i)) if origins else None
    reasons = []
    if units >= 3:
        reasons.append("unit_ceiling")
    if capacity < 10 or origins == []:
        reasons.append("route_materials_or_workers")
    loss = max(max(0, -previous[i]["pop_delta"]) for i in edge)
    return _candidate(mode, "road", origin, edge, 1, benefit, cost, _budget(haul, 6, 4, 6),
                      {"distance":road.distance, "opening_units":units, "opening_capacity":capacity,
                       "previous_used":used, "previous_unmet":pressure, "congestion_units":congestion,
                       "directions": directions, "matched_source": matched["source"],
                       "matched_quantity": matched["quantity"], "matched_freight_food": matched["freight_food"],
                       "construction_freight_food":haul, "annual_upkeep_freight_food":upkeep_haul}, reasons, loss)


def decide(owner, regions, roads, depots, previous, road_units, mode, road_use=None):
    """Select one affordable positive-score program using prior observations and opening states."""
    if mode not in PERMITTED:
        raise ValueError("unknown public finance mode")
    regions = sorted(regions, key=lambda r:r.id)
    by_id = {r.id:r for r in regions}
    if len(by_id) != len(regions) or not regions or any(r.owner != owner for r in regions):
        raise ValueError("decision requires one nonempty national group with distinct region IDs")
    needed = ("unmet", "pop_delta", "food_output", "food_need", "soil_delta")
    observed = {r.id: {k:previous.get(r.id, {}).get(k,0) for k in needed} for r in regions}
    total_p = sum(r.population for r in regions)
    total_need = sum(o["food_need"] for o in observed.values())
    total_unmet = sum(o["unmet"] for o in observed.values())
    risk = min(1000, 125+1000*total_unmet//max(1,total_need))
    throughput = relief_throughput(total_p)
    roads = sorted(roads, key=lambda road: (road.a, road.b))
    network = _network(regions, roads, depots, road_units)
    candidates = []
    for r in regions:
        candidates.extend(_region_candidates(r, observed[r.id], depots, network, throughput, risk, mode))
    for road in roads:
        candidates.append(_road_candidate(road, by_id, observed, depots, road_units, road_use or {}, mode))
    defer = _candidate(mode, "defer", None, None, 0, 0, 0, _budget(admin_units=0), {}, [])
    candidates.append(defer)
    possible = [c for c in candidates if c["permitted"] and not c["constraints"] and c["score"]>0]
    def priority(c):
        target = c["target_edge"] if c["target_edge"] is not None else (c["target_region"],)
        return -c["score"], -c["population_loss"], ACTIONS.index(c["action"]), target
    chosen = min(possible,key=priority) if possible else defer
    action = chosen["action"]
    return {
        "owner": owner, "mode": mode, "action": action, "quantity": chosen["quantity"],
        "target_region":chosen["target_region"], "target_edge":chosen["target_edge"],
        "target":chosen["target_edge"] if action=="road" else chosen["target_region"],
        "admin_units": chosen["budget"]["admin_units"], "budget": chosen["budget"].copy(),
        "relief_limit": chosen["quantity"] if action == "relief" else 0, "relief_throughput": throughput,
        "selected_score": chosen["score"], "prices": BASE_PRICES.copy(), "worker_value": 8, "horizon": 3,
        "risk_permille": risk, "observations": [{"region": r.id, "population":r.population,
            "soil":r.soil, "farmland":r.farmland, "private_stock":r.stock.copy(), "depot":depots[r.id].copy(),
            "previous":observed[r.id]} for r in regions], "candidates": candidates,
    }


def _posting(r, depot, decision, mode, schedule=None):
    private, public = r.stock.copy(), depot.copy()
    protected, cap = _bounds(r.population)
    standing = _goods()
    extra = _goods()
    if mode != "none":
        for g in GOODS:
            surplus = max(0, private[g]-protected[g])
            divisor = schedule["surplus_divisor"][g] if schedule else (16 if g == "food" else 5)
            normal = surplus//divisor
            if g == "food":
                normal = min(normal, r.population//64)
            standing[g] = min(normal, max(0, cap[g]-public[g]))
        if decision["action"] == "reserve" and decision["target_region"] == r.id:
            after_levy = private["food"]-standing["food"]
            free = max(0, cap["food"]-public["food"]-standing["food"])
            gross = min(decision["quantity"], r.population//16, free, max(0, after_levy-protected["food"])//4)
            if gross >= 2:
                extra["food"] = gross
    handling = _goods(food=(extra["food"]+31)//32)
    levied = {g:standing[g]+extra[g] for g in GOODS}
    deposited = {g:levied[g]-handling[g] for g in GOODS}
    receipt = {"region":r.id,"owner":r.owner,"population":r.population,"private_open":private,"depot_open":public,
            "protected":protected,"reserve_cap":cap,"standing_levy":standing,"extra_levy":extra,
            "levied":levied,"handling_used":handling,"deposited":deposited,
            "private_close":{g:private[g]-levied[g] for g in GOODS},
            "depot_close":{g:public[g]+deposited[g] for g in GOODS}}
    if schedule is not None:
        receipt["standing_schedule"] = {**schedule, "surplus_divisor": schedule["surplus_divisor"].copy()}
    return receipt


def audit_collection(regions, decisions, mode, postings, *, _schedules=None):
    """Reconcile each transfer, its lawful ceiling and its storage loss from recorded openings."""
    if mode not in PERMITTED:
        raise ValueError("unknown public finance mode")
    regions_by_id = {r.id:r for r in regions}
    if len(postings)!=len(regions_by_id) or {t["region"] for t in postings} != regions_by_id.keys():
        raise ValueError("collection must post once per region")
    for t in postings:
        r = regions_by_id[t["region"]]
        d = decisions[r.owner]
        schedule = _schedules[r.owner] if _schedules is not None else None
        if t.get("standing_schedule") != schedule or (schedule is None and "standing_schedule" in t):
            raise ValueError("standing schedule differs from the governing platform")
        if (t["owner"],t["population"],d["owner"],d["mode"]) != (r.owner,r.population,r.owner,mode):
            raise ValueError("collection identity, population or mode differs")
        if d["action"] not in PERMITTED[mode]:
            raise ValueError("action is not available to this policy")
        protected, cap = _bounds(r.population)
        if t["protected"]!=protected or t["reserve_cap"]!=cap:
            raise ValueError("incorrect levy limits")
        for key in ("private_open","depot_open","standing_levy","extra_levy","levied","handling_used",
                    "deposited","private_close","depot_close"):
            if set(t[key])!=set(GOODS) or any(type(n) is not int or n<0 for n in t[key].values()):
                raise ValueError(f"invalid {key} balances")
        for g in GOODS:
            start, vault = t["private_open"][g], t["depot_open"][g]
            excess, space = max(0,start-protected[g]), max(0,cap[g]-vault)
            divisor = schedule["surplus_divisor"][g] if schedule else (16 if g == "food" else 5)
            permitted = min(space, excess//divisor)
            if g == "food":
                permitted = min(permitted, r.population//64)
            base = permitted if mode!="none" else 0
            supplement = 0
            if mode!="none" and g=="food" and d["action"]=="reserve" and d["target_region"]==r.id:
                maximum = min(d["quantity"], r.population//16, space-base, (excess-base)//4)
                supplement = maximum if maximum>=2 else 0
            loss = (supplement+31)//32
            total = base+supplement
            expected = (base,supplement,total,loss,total-loss,start-total,vault+total-loss)
            fields = ("standing_levy","extra_levy","levied","handling_used","deposited","private_close","depot_close")
            if tuple(t[k][g] for k in fields)!=expected:
                raise ValueError(f"incorrect collection posting in region {r.id} for {g}")


def collect(regions, depots, decisions, mode, *, _schedules=None):
    """Post-border, pre-domestic-shipment taxation; stage all transfers before changing state."""
    regions = list(regions)
    if len({r.id for r in regions})!=len(regions):
        raise ValueError("duplicate collection region")
    ordered = sorted(regions,key=lambda r:r.id)
    records = [_posting(r,depots[r.id],decisions[r.owner],mode,
                        _schedules[r.owner] if _schedules is not None else None) for r in ordered]
    audit_collection(ordered, decisions, mode, records, _schedules=_schedules)
    for r,t in zip(ordered,records,strict=True):
        r.stock = t["private_close"].copy()
        depots[r.id] = t["depot_close"].copy()
    return records
