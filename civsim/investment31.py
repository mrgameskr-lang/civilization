"""Matched alternatives to the v3.0 capital rule; all values are integer units."""

from dataclasses import fields, replace

from .economy import BASE_PRICES, produce_sectors
from .investment import ASSETS, HORIZON, RECIPES, WORKER_VALUE, InvestingNation, _book_value, _target
from .model import GOODS, Nation


STANDARD_POPULATION = 2000
MULTI_PROJECT_LIMIT = 3


def _material(ore=0, tools=0):
    return {"food": 0, "ore": ore, "tools": tools}


def _effects(n, mode, operating):
    bonus = {}
    for key, rate in (("farm", 12), ("industry", 25), ("land", 24)):
        count = operating[key]
        amount = rate * count
        if mode in ("diminishing", "combined"):
            amount = 4 * amount // (count + 3)
        if mode in ("scaled", "combined") and key != "land":
            amount = amount * min(n.population, STANDARD_POPULATION) // max(1, n.population)
        bonus[key] = amount
    return {"land_capacity": 20*n.land + min(4*n.land, bonus["land"]),
            "farm_multiplier": 1000 + bonus["farm"], "industry_multiplier": 1000 + bonus["industry"]}


def _upkeep_multiplier(population, mode, rank):
    if mode in ("scaled", "combined"):
        scale = max(1, (population + STANDARD_POPULATION - 1) // STANDARD_POPULATION)
        return scale + (rank - 1) // 2
    return 1


def _maintain(n, mode):
    operated = dict.fromkeys(ASSETS, 0)
    by_class = {k: _material() for k in ASSETS}
    for k, recipe in RECIPES.items():
        for rank in range(1, sum(n.capital[k]) + 1):
            multiplier = _upkeep_multiplier(n.population, mode, rank)
            tools, ore = recipe.upkeep_tools * multiplier, recipe.upkeep_ore * multiplier
            if n.stock["tools"] < tools or n.stock["ore"] < ore:
                break
            operated[k] += 1
            n.stock["tools"] -= tools
            n.stock["ore"] -= ore
            by_class[k]["tools"] += tools
            by_class[k]["ore"] += ore
    return operated, by_class


def _forecast(n, climate, rules, workers, target, mode, operating):
    copy = replace(n, stock=n.stock.copy())
    return produce_sectors(copy, climate, rules, workers=workers, tool_target=target,
                           **_effects(n, mode, operating))


def _unit_value(quantities):
    return sum(quantities[g] * BASE_PRICES[g] for g in GOODS)


def _candidate(n, climate, rules, workers, mode, limits, wear, class_limit, planned, operating, base, key):
    projected = {**operating, key: operating[key] + 1}
    forecast = _forecast(n, climate, rules, workers, limits["tools"], mode, projected)
    extra = {g: min(limits[g], forecast["closing_stock"][g]) - min(limits[g], base["closing_stock"][g])
             for g in GOODS}
    recipe = RECIPES[key]
    materials = _unit_value(_material(recipe.build_ore, recipe.build_tools))
    labor_value = recipe.workers * WORKER_VALUE
    upkeep = _unit_value(_material(recipe.upkeep_ore, recipe.upkeep_tools))
    upkeep *= _upkeep_multiplier(n.population, mode, projected[key])
    gain = _unit_value(extra)
    net = HORIZON * (gain - upkeep) - labor_value - materials
    constraints = []
    if sum(n.capital[key][:-1]) + planned[key] >= class_limit:
        constraints.append("class_limit")
    if workers < recipe.workers:
        constraints.append("workers")
    if n.stock["tools"] < recipe.build_tools + wear:
        constraints.append("tools_after_farm_reserve")
    if n.stock["ore"] < recipe.build_ore:
        constraints.append("ore")
    if net <= 0:
        constraints.append("nonpositive_return")
    return {"forecast_stock": forecast["closing_stock"], "valued_stock_change": extra,
            "annual_gain_value": gain, "build_material_value": materials, "annual_upkeep_value": upkeep,
            "construction_labor_value": labor_value, "net_value": net, "constraints": constraints}


def _plan(n, climate, rules, workers, mode, limit, operated, limits, wear, class_limit):
    planned = dict.fromkeys(ASSETS, 0)
    rounds = []
    for _ in range(limit):
        operating = {k: operated[k] + planned[k] for k in ASSETS}
        base = _forecast(n, climate, rules, workers, limits["tools"], mode, operating)
        candidates = {k: _candidate(n, climate, rules, workers, mode, limits, wear, class_limit,
                                    planned, operating, base, k) for k in ASSETS}
        eligible = [k for k in ASSETS if not candidates[k]["constraints"]]
        selected = max(eligible, key=lambda k: candidates[k]["net_value"]) if eligible else None
        rounds.append({"stock": n.stock.copy(), "workers": workers, "planned": planned.copy(),
                       "forecast_base_stock": base["closing_stock"], "candidates": candidates,
                       "selected": selected})
        if selected is None:
            break
        planned[selected] += 1
        recipe = RECIPES[selected]
        n.stock["tools"] -= recipe.build_tools
        n.stock["ore"] -= recipe.build_ore
        workers -= recipe.workers
    return planned, rounds


def _net_difference(actual, reference):
    return {g: actual["produced"][g] - actual["used"][g] - reference["produced"][g] + reference["used"][g]
            for g in GOODS}


def _accounts(n, climate, rules, workers, target, mode, built, operated, paid, actual, gross_gain):
    by_class = {}
    classes_operating = sum(bool(v) for v in operated.values())
    for key, recipe in RECIPES.items():
        value = 0
        if operated[key]:
            if classes_operating == 1:
                value = gross_gain
            else:
                without = _forecast(n, climate, rules, workers, target, mode, {**operated, key: 0})
                value = _unit_value(_net_difference(actual, without))
        by_class[key] = {"build_used": _material(built[key]*recipe.build_ore, built[key]*recipe.build_tools),
                         "upkeep_used": paid[key], "construction_labor": built[key]*recipe.workers,
                         "marginal_gain_value": value}
    return by_class


def class_accounts(country_year_row, rules):
    """Return actual class costs and leave-one-class-out values from 3.1 or older records."""
    prod = country_year_row["production"]
    plan = prod.get("investment")
    if plan is None:
        return {k: {"build_used": _material(), "upkeep_used": _material(),
                    "construction_labor": 0, "marginal_gain_value": 0} for k in ASSETS}
    if "class_accounts" in plan:
        return plan["class_accounts"]
    n = Nation(**{f.name: country_year_row["opening"][f.name] for f in fields(Nation)})
    n.stock = plan["stock_after_build"]
    operated = plan["operated"]
    paid = {k: _material(operated[k]*r.upkeep_ore, operated[k]*r.upkeep_tools) for k, r in RECIPES.items()}
    actual = {"produced": prod["produced"], "used": plan["sector_used"]}
    return _accounts(n, country_year_row["climate"], rules, prod["workers"], plan["tool_target"], "fixed",
                     plan["built"], operated, paid, actual, plan["gross_gain_value"])


def produce(nation: InvestingNation, climate, rules):
    """Settle the operating and construction accounts and produce under a 3.1 rule."""
    if not isinstance(nation, InvestingNation) or rules.investment != "capital" or rules.policy31 == "off":
        raise ValueError("3.1 production requires a prepared investing nation and a 3.1 capital rule")
    mode, selection = rules.policy31.split("-")
    opening = nation.stock.copy()
    cohorts = {k: ages.copy() for k, ages in nation.capital.items()}
    initial_workers = nation.population // 2
    class_limit = (nation.land + 5) // 6
    parts = _target(nation, initial_workers, class_limit)
    target = sum(parts.values())
    limits = {"food": nation.population + nation.population // 8, "ore": nation.population // 20, "tools": target}
    operated, paid = _maintain(nation, mode)
    after_upkeep = nation.stock.copy()
    limit = 1 if selection == "single" else MULTI_PROJECT_LIMIT
    built, rounds = _plan(nation, climate, rules, initial_workers, mode, limit, operated, limits,
                          parts["farm_wear"], class_limit)
    after_build = nation.stock.copy()
    build_used = {g: after_upkeep[g] - after_build[g] for g in GOODS}
    upkeep = {g: opening[g] - after_upkeep[g] for g in GOODS}
    construction_labor = sum(built[k] * RECIPES[k].workers for k in ASSETS)
    workers = initial_workers - construction_labor
    inputs = replace(nation, stock=after_build)
    no_assets = dict.fromkeys(ASSETS, 0)
    reference = _forecast(inputs, climate, rules, workers, target, mode, no_assets)
    effects = _effects(nation, mode, operated)
    actual = produce_sectors(nation, climate, rules, workers=workers, tool_target=target, **effects)
    diff = _net_difference(actual, reference)
    gross_gain = _unit_value(diff)
    accounts = _accounts(inputs, climate, rules, workers, target, mode, built, operated, paid, actual, gross_gain)
    sector_used = actual["used"]
    nation.capital = {k: [built[k], *cohorts[k][:-1]] for k in ASSETS}
    actual.update(opening_stock=opening, used={g: sector_used[g] + build_used[g] + upkeep[g] for g in GOODS})
    actual["investment"] = {
        "policy": "capital", "policy31": rules.policy31, "opening_capital": cohorts, "operated": operated,
        "built": built, "retired": {k: cohorts[k][-1] for k in ASSETS},
        "book": {k: _book_value(RECIPES[k], cohorts[k], built[k], nation.capital[k]) for k in ASSETS},
        "closing_capital": {k: nation.capital[k].copy() for k in ASSETS},
        "upkeep_used": upkeep, "build_used": build_used, "sector_used": sector_used,
        "stock_after_upkeep": after_upkeep, "stock_after_build": after_build,
        "construction_labor": construction_labor, "class_limit": class_limit,
        "tool_target": target, "target_components": parts, "forecast_limits": limits,
        "forecast_base_stock": rounds[0]["forecast_base_stock"], "forecast_horizon": HORIZON,
        "candidates": rounds[0]["candidates"], "selection_rounds": rounds, "class_accounts": accounts,
        "farm_multiplier": effects["farm_multiplier"], "industry_multiplier": effects["industry_multiplier"],
        "added_land_capacity": effects["land_capacity"] - 20*nation.land,
        "reference_output": reference["produced"], "reference_used": reference["used"],
        "net_output_gain": diff, "gross_gain_value": gross_gain,
    }
    return actual
