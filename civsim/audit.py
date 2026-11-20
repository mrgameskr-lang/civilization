"""Independent reconstruction of the physical, cash and demographic ledgers."""

from .model import GOODS


class BalanceError(ValueError):
    """A stage of the simulated year failed a model invariant."""


def _check(condition, message):
    if not condition:
        raise BalanceError(message)


def _quantity(value, label, minimum=0):
    _check(type(value) is int and value >= minimum, f"{label}: invalid quantity {value!r}")
    return value


def _goods(values, label):
    _check(set(values) == set(GOODS), f"{label}: missing or unknown good")
    for g, qty in values.items():
        _quantity(qty, f"{label}.{g}")


def _audit_labor(opening, trace):
    """Rebuild v2 worker assignments from opening population, stock, land and policy."""
    policy = trace.get("labor_policy")
    _check(policy in ("idle", "reallocate"), "unknown or missing labor policy")
    population = opening["population"]
    workers = population // 2
    share = max(450, 760 - 220 * opening["stock"]["food"] // max(1, population))
    farmers = workers * share // 1000
    miners = (workers - farmers) // 2
    artisans = workers - farmers - miners
    capacity = 20 * _quantity(opening["land"], "land")
    active_farmers = min(farmers, capacity)
    surplus = farmers - active_farmers
    moved = surplus if policy == "reallocate" else 0
    to_mine = moved // 2
    to_factory = moved - to_mine
    counts = {
        "population": population, "workers": workers, "farm_share": share,
        "land": opening["land"], "land_capacity": capacity, "active_farmers": active_farmers,
        "idle_before": surplus, "idle_after": surplus - moved,
    }
    for key, expected in counts.items():
        _check(_quantity(trace.get(key), key) == expected, f"labor: {key} mismatch")
    active = {"farm": active_farmers, "mine": miners + to_mine, "factory": artisans + to_factory}
    assignments = {
        "labor_before": {"farm": farmers, "mine": miners, "factory": artisans},
        "reassigned": {"mine": to_mine, "factory": to_factory},
        "active_labor": active,
        "labor": {**active, "farm": farmers - moved},
    }
    for name, expected in assignments.items():
        actual = trace.get(name)
        _check(isinstance(actual, dict) and actual.keys() == expected.keys(), f"labor: {name} sectors")
        for sector, count in expected.items():
            _check(_quantity(actual[sector], sector) == count, f"labor: {name}.{sector} mismatch")


def observed_events(countries, moves):
    """Deterministic observations with the same units as their underlying evidence."""
    events = []
    for c in countries:
        meal = c["consumption"]
        unmet = meal["food_need"] - meal["food_eaten"]
        if unmet:
            events.append({"kind": "food_shortage", "country": c["id"], "unmet": unmet,
                           "needed": meal["food_need"], "eaten": meal["food_eaten"]})
        if c["opening"]["deposit"] > 0 and c["closing"]["deposit"] == 0:
            events.append({"kind": "deposit_exhausted", "country": c["id"],
                           "ore_extracted": c["production"]["produced"]["ore"]})
    events.extend({"kind": "migration", **move} for move in moves)
    return events


def audit(record):
    """Rebuild balances from individual postings; reject a failed year before publication."""
    countries = record["countries"]
    rows = {c["id"]: c for c in countries}
    _check(len(rows) == len(countries), "duplicate country ID")
    stock, cash = {}, {}
    for i, c in rows.items():
        o, end, p = c["opening"], c["closing"], c["production"]
        _check(i == o["id"] == end["id"], f"country {i}: identity")
        for name, state in (("opening", o), ("closing", end)):
            _goods(state["stock"], f"country {i} {name} stock")
            for field in ("cash", "deposit", "population"):
                _quantity(state[field], f"country {i} {name} {field}")
        if "settlement_order" in record["market"]:
            _audit_labor(o, p)
        else:
            _check("labor_policy" not in p, "missing settlement order for versioned labor trace")
        _goods(p["produced"], "production")
        _goods(p["used"], "production input")
        stock[i] = {g: o["stock"][g] + p["produced"][g] - p["used"][g] for g in GOODS}
        _goods(stock[i], "after production")
        _check(o["deposit"] - p["produced"]["ore"] == end["deposit"], f"country {i}: deposit")
        _check(o["stock"] == p["opening_stock"] and stock[i] == p["closing_stock"],
               f"country {i}: production boundary")
        cash[i] = o["cash"]
        market_open = record["market"]["opening"][str(i)]
        _check(market_open == {"stock": stock[i], "cash": cash[i]}, f"country {i}: market boundary")

    for t in record["market"]["trades"]:
        s, b, g = t["seller"], t["buyer"], t["good"]
        _check(s != b and s in rows and b in rows and g in GOODS, "trade counterparties or good")
        qty = _quantity(t["quantity"], "trade quantity", 1)
        cost = qty * _quantity(t["unit_price"], "trade price", 1)
        _check(cost == t["value"] and cash[b] == t["buyer_cash_before"], "trade valuation")
        _check(stock[s][g] >= qty and cash[b] >= cost, "trade exceeds stock or cash")
        stock[s][g] -= qty
        stock[b][g] += qty
        cash[s] += cost
        cash[b] -= cost

    incoming, outgoing = dict.fromkeys(rows, 0), dict.fromkeys(rows, 0)
    for m in record["moves"]:
        source, target = m["source"], m["target"]
        _check(source in rows and target in rows and source != target, "migration counterparties")
        count = _quantity(m["people"], "people moving", 1)
        incoming[target] += count
        outgoing[source] += count

    for i, c in rows.items():
        o, end, u, d = c["opening"], c["closing"], c["consumption"], c["demography"]
        _goods(u["used"], "consumption")
        need, eaten = u["food_need"], _quantity(u["food_eaten"], "food eaten")
        spoiled = _quantity(u["food_spoiled"], "food spoiled")
        _check(need == o["population"] and eaten == min(need, stock[i]["food"])
               and eaten + spoiled == u["used"]["food"], f"country {i}: food allocation")
        for g in GOODS:
            _check(stock[i][g] - u["used"][g] == end["stock"][g], f"country {i}: {g} balance")
        _check(cash[i] == end["cash"], f"country {i}: cash balance")
        births = _quantity(d["births"], "births")
        deaths = _quantity(d["deaths"], "deaths")
        _check(deaths <= o["population"], f"country {i}: excess deaths")
        residents = o["population"] + births - deaths
        _check(outgoing[i] <= residents and outgoing[i] == d["emigrants"] and
               incoming[i] == d["immigrants"], f"country {i}: migration balance")
        _check(end["population"] == residents + incoming[i] - outgoing[i],
               f"country {i}: population balance")

    _check(record["events"] == observed_events(countries, record["moves"]), "event evidence mismatch")

