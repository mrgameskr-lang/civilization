"""Independent reconstruction of the physical, cash and demographic ledgers."""

from .model import GOODS
from .rules import POLICIES31


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


def _audit_labor(opening, trace, construction_labor=0, added_land_capacity=0):
    """Rebuild worker assignments after any construction or land improvements."""
    policy = trace.get("labor_policy")
    _check(policy in ("idle", "reallocate"), "unknown or missing labor policy")
    population = opening["population"]
    workers = population // 2 - construction_labor
    share = max(450, 760 - 220 * opening["stock"]["food"] // max(1, population))
    farmers = workers * share // 1000
    miners = (workers - farmers) // 2
    artisans = workers - farmers - miners
    capacity = 20 * _quantity(opening["land"], "land") + added_land_capacity
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


def _audit_investment(opening, closing, p):
    """Reconstruct the capital roll-forward and physical spending from opening resources."""
    inv = p.get("investment")
    _check(isinstance(inv, dict), "missing investment stages")
    policy = inv.get("policy")
    _check(policy in ("inventory", "capital"), "unknown investment policy")
    variant = inv.get("policy31")
    if variant is not None:
        _check(variant in POLICIES31 and policy == "capital", "unknown 3.1 investment policy")
    geometry = variant.split("-")[0] if variant else "fixed"
    scaled = geometry in ("scaled", "combined")
    diminishing = geometry in ("diminishing", "combined")
    # Columns are build tools, ore, workers; annual operating tools, ore.
    recipes = {"farm": (8, 8, 6, 1, 0), "industry": (12, 12, 8, 1, 1),
               "land": (10, 6, 12, 1, 0)}
    for state, key in ((opening, "opening_capital"), (closing, "closing_capital")):
        assets = state.get("capital")
        _check(isinstance(assets, dict) and assets.keys() == recipes.keys(), f"invalid {key} accounts")
        _check(assets == inv.get(key), f"unreconciled {key} snapshot")
        for kind, cohorts in assets.items():
            _check(isinstance(cohorts, list) and len(cohorts) == 8, f"invalid {kind} cohorts")
            for count in cohorts:
                _quantity(count, f"{kind} cohort count")
    book = inv.get("book")
    _check(isinstance(book, dict) and book.keys() == recipes.keys(), "invalid book value accounts")
    for key in ("built", "retired", "operated"):
        values = inv.get(key)
        _check(isinstance(values, dict) and values.keys() == recipes.keys(), f"invalid {key} ledger")
        for count in values.values():
            _quantity(count, f"{key} count")

    remaining = opening["stock"].copy()
    build_cost = dict.fromkeys(GOODS, 0)
    upkeep = dict.fromkeys(GOODS, 0)
    labor_cost = 0
    limit = (_quantity(opening["land"], "land") + 5) // 6
    project_cap = 3 if variant and variant.endswith("-multi") else 1
    _check(sum(inv["built"].values()) <= project_cap, "annual construction limit exceeded")
    for kind, (tools, ore, labor, tool_upkeep, ore_upkeep) in recipes.items():
        before, after = opening["capital"][kind], closing["capital"][kind]
        count, added = sum(before), inv["built"][kind]
        _check(count <= limit and sum(after) <= limit, f"{kind} exceeds asset limit")
        _check(policy == "capital" or count + added == 0, "inventory control owns capital")
        _check(inv["retired"][kind] == before[-1] and after == [added, *before[:-1]],
               f"{kind} vintage or retirement mismatch")
        unit_value = 12 * tools + 4 * ore + 8 * labor
        expected_book = {
            "open_eighths": unit_value * sum((8 - age) * n for age, n in enumerate(before)),
            "depreciation_eighths": unit_value * count,
            "additions_eighths": 8 * unit_value * added,
            "close_eighths": unit_value * sum((8 - age) * n for age, n in enumerate(after)),
        }
        account = book[kind]
        _check(isinstance(account, dict) and account.keys() == expected_book.keys(),
               f"{kind} book account fields")
        for field, expected in expected_book.items():
            _check(_quantity(account[field], field) == expected, f"{kind} book {field} mismatch")
        if scaled:
            active = units = 0
            size = max(1, (opening["population"] + 1999) // 2000)
            while active < count:
                required = units + size + active // 2
                if required * tool_upkeep > remaining["tools"] or required * ore_upkeep > remaining["ore"]:
                    break
                active += 1
                units = required
        else:
            active = min(count, remaining["tools"] // tool_upkeep)
            if ore_upkeep:
                active = min(active, remaining["ore"] // ore_upkeep)
            units = active
        _check(inv["operated"][kind] == active, f"unfunded or premature {kind} operation")
        remaining["tools"] -= units * tool_upkeep
        remaining["ore"] -= units * ore_upkeep
        upkeep["tools"] += units * tool_upkeep
        upkeep["ore"] += units * ore_upkeep
        if variant:
            account = inv["class_accounts"][kind]
            _check(account["upkeep_used"] == {"food": 0, "ore": units * ore_upkeep,
                                              "tools": units * tool_upkeep}, f"{kind} upkeep ledger")
            _check(account["build_used"] == {"food": 0, "ore": added * ore, "tools": added * tools}
                   and account["construction_labor"] == added * labor, f"{kind} build ledger")
        build_cost["tools"] += added * tools
        build_cost["ore"] += added * ore
        labor_cost += added * labor
    for key, expected in (("build_used", build_cost), ("upkeep_used", upkeep)):
        _goods(inv[key], key)
        _check(inv[key] == expected, f"{key} does not match asset recipes")
    _goods(inv["stock_after_upkeep"], "stock after upkeep")
    _check(inv["stock_after_upkeep"] == remaining, "stock after upkeep mismatch")
    for good in GOODS:
        remaining[good] -= build_cost[good]
    _goods(remaining, "resources after upkeep and construction")
    _goods(inv["stock_after_build"], "stock after construction")
    _check(inv["stock_after_build"] == remaining, "stock after construction mismatch")
    _check(_quantity(inv["construction_labor"], "construction labor") == labor_cost
           and labor_cost <= opening["population"] // 2, "unfunded or misposted builder labor")
    operated = inv["operated"]
    def bonus(kind, rate):
        count = operated[kind]
        amount = 4 * rate * count // (count + 3) if diminishing else rate * count
        if scaled and kind != "land":
            population = opening["population"]
            amount = amount * min(2000, population) // max(1, population)
        return amount

    extra_capacity = min(4 * opening["land"], bonus("land", 24))
    for key, expected in (("added_land_capacity", extra_capacity),
                          ("farm_multiplier", 1000 + bonus("farm", 12)),
                          ("industry_multiplier", 1000 + bonus("industry", 25))):
        _check(_quantity(inv[key], key) == expected, f"{key} requires paid opening assets")
    _audit_labor(opening, p, labor_cost, extra_capacity)

    workers = opening["population"] // 2
    anticipated_farmers = min(workers * p["farm_share"] // 1000, 24 * opening["land"])
    target_parts = {
        "farm_wear": (anticipated_farmers + 29) // 30, "trade_buffer": opening["population"] // 40,
        "project_buffer": 12 if opening["land"] and workers >= 6 else 0,
        "replacement_buffer": (30 * limit + 7) // 8,
    }
    target = sum(target_parts.values())
    _check(inv["target_components"] == target_parts and inv["tool_target"] == target,
           "tool replacement or reserve target mismatch")
    if any(inv["built"].values()):
        _check(remaining["tools"] >= target_parts["farm_wear"], "construction spent farm tool reserve")
    if variant:
        _check(inv["forecast_horizon"] == 5 and inv["class_limit"] == limit, "investment forecast bounds")
        forecast_limits = {"food": opening["population"] + opening["population"] // 8,
                           "ore": opening["population"] // 20, "tools": target}
        _check(inv["forecast_limits"] == forecast_limits, "investment valuation limits")
        _audit_selection(inv, recipes, workers, project_cap, target_parts["farm_wear"], opening, scaled)
    _audit_investment_output(opening, p, remaining, target)


def _audit_selection(inv, recipes, workers, project_cap, wear, opening, scaled):
    """Replay the annual project queue and its diminishing material and labor budget."""
    rounds = inv["selection_rounds"]
    _check(1 <= len(rounds) <= project_cap, "invalid number of investment rounds")
    stock = inv["stock_after_upkeep"].copy()
    planned = dict.fromkeys(recipes, 0)
    for index, proposal in enumerate(rounds):
        _check(proposal["stock"] == stock and proposal["workers"] == workers
               and proposal["planned"] == planned, "selection round opening budget")
        candidates = proposal["candidates"]
        _check(candidates.keys() == recipes.keys(), "missing project comparison")
        if index == 0:
            _check(candidates == inv["candidates"] and proposal["forecast_base_stock"] == inv["forecast_base_stock"],
                   "opening forecast differs from first selection round")
        limits = inv["forecast_limits"]
        prices = {"food": 8, "ore": 4, "tools": 12}
        for kind, (tools, ore, labor, upkeep_tools, upkeep_ore) in recipes.items():
            entry = candidates[kind]
            stock_change = {g: min(limits[g], entry["forecast_stock"][g])
                            - min(limits[g], proposal["forecast_base_stock"][g]) for g in GOODS}
            multiple = 1
            if scaled:
                prior_count = inv["operated"][kind] + planned[kind]
                multiple = max(1, (opening["population"] + 1999) // 2000) + prior_count // 2
            gain = sum(prices[g] * stock_change[g] for g in GOODS)
            recurring = multiple * (12 * upkeep_tools + 4 * upkeep_ore)
            material = 12 * tools + 4 * ore
            net = 5 * (gain - recurring) - material - 8 * labor
            _check(entry["valued_stock_change"] == stock_change and entry["annual_gain_value"] == gain
                   and entry["annual_upkeep_value"] == recurring and entry["build_material_value"] == material
                   and entry["construction_labor_value"] == 8 * labor and entry["net_value"] == net,
                   f"{kind} candidate valuation")
            conditions = {"class_limit": sum(opening["capital"][kind][:-1]) + planned[kind] >= inv["class_limit"],
                          "workers": workers < labor, "tools_after_farm_reserve": stock["tools"] < tools + wear,
                          "ore": stock["ore"] < ore, "nonpositive_return": net <= 0}
            _check(entry["constraints"] == [key for key, applies in conditions.items() if applies],
                   f"{kind} candidate constraints")
        eligible = [k for k in recipes if not candidates[k]["constraints"]]
        chosen = max(eligible, key=lambda k: candidates[k]["net_value"], default=None)
        _check(proposal["selected"] == chosen, "selected project differs from highest eligible net value")
        if chosen is None:
            _check(index == len(rounds) - 1, "empty selection did not terminate the queue")
            break
        tools, ore, labor, *_ = recipes[chosen]
        stock["tools"] -= tools
        stock["ore"] -= ore
        workers -= labor
        _check(stock["tools"] >= wear and stock["ore"] >= 0 and workers >= 0, "overdrawn project budget")
        planned[chosen] += 1
    _check(rounds[-1]["selected"] is None or len(rounds) == project_cap, "project queue stopped early")
    _check(planned == inv["built"] and stock == inv["stock_after_build"], "selection postings differ from construction")


def _audit_investment_output(opening, p, remaining, target):
    """Check actual output against paid equipment, labor, reserves and input caps."""
    inv = p["investment"]
    skill = opening["productivity"] * opening["technology"]
    active = p["active_labor"]
    need = (p["active_farmers"] + 29) // 30
    wear = min(need, remaining["tools"])
    equipment = 1000 + 150 * wear // max(1, need)
    food = (active["farm"] * 32 * skill * opening["fertility"] * opening["soil"]
            * p["climate"] * equipment * inv["farm_multiplier"] // (10 * 1000**7))
    mine = active["mine"] * skill * opening["ore_grade"] * inv["industry_multiplier"] // (2 * 1000**4)
    factory = active["factory"] * skill * inv["industry_multiplier"] // (3 * 1000**3)
    ore = min(mine, opening["deposit"])
    available_ore = remaining["ore"] + ore
    tool_gap = max(0, target - (remaining["tools"] - wear))
    tools = min(factory, available_ore // 2, tool_gap)
    output = p["produced"]
    for key, expected in (("equipment", equipment), ("mining_capacity", mine), ("factory_capacity", factory),
                          ("ore_available", available_ore), ("factory_ore_limit", available_ore // 2)):
        _check(_quantity(p[key], key) == expected, f"unfunded or incorrect {key}")
    _check(output == {"food": food, "ore": ore, "tools": tools}, "output exceeds or differs from capacity")
    sector_used = {"food": 0, "ore": 2 * output["tools"], "tools": wear}
    _goods(inv["sector_used"], "sector inputs")
    _check(p["tool_need"] == need and inv["sector_used"] == sector_used, "sector input mismatch")
    _check(all(p["used"][g] == inv["upkeep_used"][g] + inv["build_used"][g] + sector_used[g] for g in GOODS),
           "investment and sector inputs do not reconcile to total use")


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
        _goods(p["produced"], "production")
        _goods(p["used"], "production input")
        if "capital" in o or "capital" in end or "investment" in p:
            _check("settlement_order" in record["market"], "missing v3 settlement order")
            _audit_investment(o, end, p)
        elif "settlement_order" in record["market"]:
            _audit_labor(o, p)
        else:
            _check("labor_policy" not in p, "missing settlement order for versioned labor trace")
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
        before_meals = stock[i]["food"]
        carry = before_meals - eaten - spoiled
        _check(_quantity(need, "food need") == o["population"] and eaten == min(need, before_meals)
               and spoiled == (before_meals - eaten) // 12
               and u["used"] == {"food": eaten + spoiled, "ore": 0, "tools": 0},
               f"country {i}: food allocation")
        _check(_quantity(u["opening_food"], "opening food") == before_meals
               and _quantity(u["closing_food"], "closing food") == carry
               and _quantity(u["food_unmet"], "unmet need") == need - eaten,
               f"country {i}: food carry or unmet need")
        _check(d["food_need"] == need and d["food_eaten"] == eaten
               and d["food_shortage"] == need - eaten and d["food_reserve"] == carry,
               f"country {i}: consumption to demography boundary")
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

