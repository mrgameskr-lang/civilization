"""Fixed-life productive assets and demand-limited tool manufacturing."""

from dataclasses import dataclass, fields, replace

from .economy import BASE_PRICES, produce_sectors
from .model import GOODS, Nation
from .rules import Rules


ASSETS = ("farm", "industry", "land")
LIFE = 8
HORIZON = 5
WORKER_VALUE = 8


@dataclass(frozen=True, slots=True)
class Recipe:
    build_tools: int
    build_ore: int
    workers: int
    upkeep_tools: int
    upkeep_ore: int


RECIPES = {"farm": Recipe(8, 8, 6, 1, 0), "industry": Recipe(12, 12, 8, 1, 1),
           "land": Recipe(10, 6, 12, 1, 0)}


@dataclass(slots=True)
class InvestingNation(Nation):
    capital: dict[str, list[int]]


def prepare(nation: Nation) -> InvestingNation:
    """Copy every mutable field before starting a v3 trial year."""
    data = {field.name: getattr(nation, field.name) for field in fields(Nation)}
    data["stock"] = nation.stock.copy()
    capital = ({k: list(nation.capital[k]) for k in ASSETS} if isinstance(nation, InvestingNation)
               else {k: [0] * LIFE for k in ASSETS})
    return InvestingNation(**data, capital=capital)


def _target(n, workers, class_limit):
    share = max(450, 760 - 220 * n.stock["food"] // max(1, n.population))
    wear = (min(workers * share // 1000, 24 * n.land) + 29) // 30
    parts = {"farm_wear": wear, "trade_buffer": n.population // 40,
             "project_buffer": 12 if n.land > 0 and workers >= 6 else 0,
             "replacement_buffer": (30 * class_limit + LIFE - 1) // LIFE}
    return parts


def _effects(land, operating):
    return {"land_capacity": 20 * land + min(4 * land, 24 * operating["land"]),
            "farm_multiplier": 1000 + 12 * operating["farm"],
            "industry_multiplier": 1000 + 25 * operating["industry"]}


def _forecast(n, climate, rules, workers, tool_target, operating):
    forecast = replace(n, stock=n.stock.copy())
    return produce_sectors(forecast, climate, rules, workers=workers, tool_target=tool_target,
                           **_effects(n.land, operating))


def _spend_upkeep(n, opening_capital):
    used = dict.fromkeys(GOODS, 0)
    operated = {}
    for key, recipe in RECIPES.items():
        count = min(sum(opening_capital[key]), n.stock["tools"] // recipe.upkeep_tools)
        if recipe.upkeep_ore:
            count = min(count, n.stock["ore"] // recipe.upkeep_ore)
        operated[key] = count
        for good, unit_cost in (("tools", recipe.upkeep_tools), ("ore", recipe.upkeep_ore)):
            payment = count * unit_cost
            n.stock[good] -= payment
            used[good] += payment
    return operated, used


def _book_value(recipe, opening, additions, closing):
    unit_cost = (recipe.build_tools * BASE_PRICES["tools"] + recipe.build_ore * BASE_PRICES["ore"]
                 + recipe.workers * WORKER_VALUE)
    return {
        "open_eighths": unit_cost * sum((LIFE - age) * count for age, count in enumerate(opening)),
        "depreciation_eighths": unit_cost * sum(opening),
        "additions_eighths": LIFE * unit_cost * additions,
        "close_eighths": unit_cost * sum((LIFE - age) * count for age, count in enumerate(closing)),
    }


def _candidate(n, key, climate, rules, workers, target, operated, base, limits, wear, class_limit):
    recipe = RECIPES[key]
    hypothetical = {**operated, key: operated[key] + 1}
    predicted = _forecast(n, climate, rules, workers, target, hypothetical)
    marginal_stock = {g: min(limits[g], predicted["closing_stock"][g])
                      - min(limits[g], base["closing_stock"][g]) for g in GOODS}
    annual_gain = sum(marginal_stock[g] * BASE_PRICES[g] for g in GOODS)
    build_cost = recipe.build_tools * BASE_PRICES["tools"] + recipe.build_ore * BASE_PRICES["ore"]
    annual_upkeep = recipe.upkeep_tools * BASE_PRICES["tools"] + recipe.upkeep_ore * BASE_PRICES["ore"]
    labor_cost = recipe.workers * WORKER_VALUE
    net = HORIZON * (annual_gain - annual_upkeep) - build_cost - labor_cost
    constraints = []
    if sum(n.capital[key][:-1]) >= class_limit:
        constraints.append("class_limit")
    if workers < recipe.workers:
        constraints.append("workers")
    if n.stock["tools"] < recipe.build_tools + wear:
        constraints.append("tools_after_farm_reserve")
    if n.stock["ore"] < recipe.build_ore:
        constraints.append("ore")
    if net <= 0:
        constraints.append("nonpositive_return")
    return {"forecast_stock": predicted["closing_stock"], "valued_stock_change": marginal_stock,
            "annual_gain_value": annual_gain, "build_material_value": build_cost,
            "annual_upkeep_value": annual_upkeep, "construction_labor_value": labor_cost,
            "net_value": net, "constraints": constraints}


def produce(nation: InvestingNation, climate: int, rules: Rules) -> dict:
    """Pay for operating assets, choose one project, produce and advance all cohorts."""
    if rules.investment not in ("inventory", "capital"):
        raise ValueError("v3 production requires inventory or capital policy")
    if not isinstance(nation, InvestingNation):
        raise ValueError("call investment.prepare(nation) before running v3 production")
    opening = nation.stock.copy()
    cohorts = {k: list(nation.capital[k]) for k in ASSETS}
    if rules.investment == "inventory" and any(any(c) for c in cohorts.values()):
        raise ValueError("inventory-only countries cannot own capital")
    workers = nation.population // 2
    class_limit = (nation.land + 5) // 6
    parts = _target(nation, workers, class_limit)
    target = sum(parts.values())
    limits = {"food": nation.population + nation.population // 8,
              "ore": nation.population // 20, "tools": target}
    operated, upkeep = _spend_upkeep(nation, cohorts)
    after_upkeep = nation.stock.copy()
    built = dict.fromkeys(ASSETS, 0)
    construction_labor = 0
    build_used = dict.fromkeys(GOODS, 0)
    candidates = {}
    base = _forecast(nation, climate, rules, workers, target, operated)
    if rules.investment == "capital":
        for key in ASSETS:
            candidates[key] = _candidate(nation, key, climate, rules, workers, target, operated, base,
                                         limits, parts["farm_wear"], class_limit)
        eligible = [k for k in ASSETS if not candidates[k]["constraints"]]
        if eligible:
            selected = max(eligible, key=lambda k: candidates[k]["net_value"])
            built[selected] = 1
            recipe = RECIPES[selected]
            construction_labor = recipe.workers
            build_used.update(ore=recipe.build_ore, tools=recipe.build_tools)
            nation.stock["ore"] -= recipe.build_ore
            nation.stock["tools"] -= recipe.build_tools

    remaining_workers = workers - construction_labor
    reference = _forecast(nation, climate, rules, remaining_workers, target, dict.fromkeys(ASSETS, 0))
    effects = _effects(nation.land, operated)
    actual = produce_sectors(nation, climate, rules, workers=remaining_workers, tool_target=target, **effects)
    sector_used = actual["used"]
    after_build = actual["opening_stock"]
    net_change = {g: (actual["produced"][g] - sector_used[g])
                  - (reference["produced"][g] - reference["used"][g]) for g in GOODS}
    nation.capital = {k: [built[k], *cohorts[k][:-1]] for k in ASSETS}
    actual.update(opening_stock=opening, used={g: upkeep[g] + build_used[g] + sector_used[g] for g in GOODS})
    actual["investment"] = {
        "policy": rules.investment, "opening_capital": cohorts, "operated": operated,
        "built": built, "retired": {k: cohorts[k][-1] for k in ASSETS},
        "book": {k: _book_value(RECIPES[k], cohorts[k], built[k], nation.capital[k]) for k in ASSETS},
        "closing_capital": {k: list(nation.capital[k]) for k in ASSETS},
        "upkeep_used": upkeep, "build_used": build_used, "sector_used": sector_used,
        "stock_after_upkeep": after_upkeep, "stock_after_build": after_build,
        "construction_labor": construction_labor, "class_limit": class_limit,
        "tool_target": target, "target_components": parts, "forecast_limits": limits,
        "forecast_base_stock": base["closing_stock"], "forecast_horizon": HORIZON,
        "candidates": candidates, "farm_multiplier": effects["farm_multiplier"],
        "industry_multiplier": effects["industry_multiplier"],
        "added_land_capacity": effects["land_capacity"] - 20 * nation.land,
        "reference_output": reference["produced"], "reference_used": reference["used"],
        "net_output_gain": net_change, "gross_gain_value": sum(net_change[g] * BASE_PRICES[g] for g in GOODS),
    }
    return actual
