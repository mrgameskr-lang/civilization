"""Local capital accounts, soil management and two scopes of equipment service."""

from collections import defaultdict
from dataclasses import replace

from .economy import BASE_PRICES, produce_sectors
from .investment import ASSETS, HORIZON, LIFE, RECIPES, _book_value, _candidate, _forecast, _spend_upkeep, _target
from .model import GOODS
from .rules import Rules
from .research71 import FARM_BONUS


LOCAL_RULES = Rules("reallocate", investment="capital")
BONUS = {"farm": 12, "industry": 25}


def _care_plan(farmland, soil, stock, workers, enabled):
    capacity = min((farmland + 7)//8, stock["ore"], stock["tools"], workers//4)
    potential = 8 * min(farmland, 8*capacity) // max(1, farmland) if enabled and soil < 950 else 0
    packages = (potential * farmland + 63)//64
    return {"enabled": enabled, "packages": packages, "treated_tiles": min(farmland, 8*packages),
            "workers": 4*packages, "used": {"food": 0, "ore": packages, "tools": packages}}


def _plan(r, climate, care_enabled, workers, farm_bonus):
    opening = r.stock.copy()
    cohorts = r.capital
    operated, upkeep = _spend_upkeep(r, cohorts)
    after_upkeep = r.stock.copy()
    care = _care_plan(r.farmland, r.soil, r.stock, workers, care_enabled)
    workers -= care["workers"]
    for g in GOODS:
        r.stock[g] -= care["used"][g]
    after_care = r.stock.copy()
    # The shared planner treats its land argument as cultivable area.
    view = replace(r, land=r.farmland)
    class_limit = (r.land + 5)//6
    parts = _target(view, workers, class_limit)
    target = sum(parts.values())
    limits = {"food": r.population + r.population//8, "ore": r.population//20, "tools": target}
    base = _forecast(view, climate, LOCAL_RULES, workers, target, operated, farm_bonus)
    proposals = {k: _candidate(view, k, climate, LOCAL_RULES, workers, target, operated, base, limits,
                               parts["farm_wear"], class_limit, farm_bonus) for k in ASSETS}
    eligible = [k for k in ASSETS if not proposals[k]["constraints"]]
    chosen = max(eligible, key=lambda k: proposals[k]["net_value"]) if eligible else None
    built = {k: int(k == chosen) for k in ASSETS}
    build_cost = dict.fromkeys(GOODS, 0)
    labor = 0
    if chosen:
        recipe = RECIPES[chosen]
        build_cost.update(ore=recipe.build_ore, tools=recipe.build_tools)
        labor = recipe.workers
        for g in GOODS:
            r.stock[g] -= build_cost[g]
    r.capital = {k: [built[k], *cohorts[k][:-1]] for k in ASSETS}
    plan = {
        "policy": "capital", "opening_capital": cohorts, "closing_capital": {k: v.copy() for k,v in r.capital.items()},
        "operated": operated, "built": built, "retired": {k: cohorts[k][-1] for k in ASSETS},
        "book": {k: _book_value(RECIPES[k], cohorts[k], built[k], r.capital[k]) for k in ASSETS},
        "construction_labor": labor, "build_used": build_cost, "upkeep_used": upkeep,
        "stock_after_upkeep": after_upkeep, "stock_after_care": after_care, "stock_after_build": r.stock.copy(),
        "class_limit": class_limit, "target_components": parts, "tool_target": target,
        "forecast_horizon": HORIZON, "forecast_limits": limits, "forecast_base_stock": base["closing_stock"],
        "candidates": proposals,
    }
    return opening, plan, care


def _allocate(owners, operating, scope):
    """Distribute indivisible permille bonus points, preserving each country's budget."""
    effects = {}
    for regions in owners.values():
        for uid, _, _ in regions:
            effects[uid] = {"scope": scope, **{field: {} for field in (
                "host_bonus", "owner_bonus_pool", "eligible_regions", "recipient_rank", "applied_bonus", "unallocated")}}
        for k, rate in BONUS.items():
            pool = sum(rate * operating[uid][k] for uid, _, _ in regions)
            eligible = sorted(uid for uid, workers, farm in regions if workers and (k != "farm" or farm))
            ranks = {uid: i for i, uid in enumerate(eligible)}
            count = len(eligible)
            share, remainder = divmod(pool, max(1, count))
            for uid, _, _ in regions:
                host = rate * operating[uid][k]
                rank = ranks.get(uid, -1)
                applied = host if scope == "regional" else (share + int(rank < remainder) if rank >= 0 else 0)
                for field, value in (("host_bonus", host), ("owner_bonus_pool", pool), ("eligible_regions", count),
                                     ("recipient_rank", rank), ("applied_bonus", applied),
                                     ("unallocated", pool if scope == "national" and not count else 0)):
                    effects[uid][field][k] = value
    return effects


def _finish(r, opening, plan, care, effect, climate, workers, level):
    workers -= plan["construction_labor"] + care["workers"]
    field_capacity = 20*r.farmland
    added = min(4*r.farmland, 24*plan["operated"]["land"])
    multipliers = {k: 1000 + effect["applied_bonus"][k] for k in BONUS}
    bonus = FARM_BONUS * (level or 0)
    multipliers["farm"] += bonus
    reference_view = replace(r, stock=r.stock.copy())
    reference = produce_sectors(reference_view, climate, LOCAL_RULES, workers=workers,
                                land_capacity=field_capacity, tool_target=plan["tool_target"], farm_multiplier=1000+bonus)
    p = produce_sectors(r, climate, LOCAL_RULES, workers=workers, land_capacity=field_capacity+added,
                        tool_target=plan["tool_target"], farm_multiplier=multipliers["farm"],
                        industry_multiplier=multipliers["industry"])
    natural = r.soil if r.farmland else p["soil_before"]
    recovery = min(max(0, 1000-natural), 8*care["treated_tiles"]//max(1, r.farmland))
    r.soil = natural + recovery
    care.update(natural_soil=natural, recovery=recovery, closing_soil=r.soil)
    gains = {g: p["produced"][g] - p["used"][g] - reference["produced"][g] + reference["used"][g] for g in GOODS}
    plan.update(sector_used=p["used"], reference_output=reference["produced"], reference_used=reference["used"],
                added_land_capacity=added, farm_multiplier=multipliers["farm"], industry_multiplier=multipliers["industry"],
                net_output_gain=gains, gross_gain_value=sum(BASE_PRICES[g]*gains[g] for g in GOODS))
    p.update(opening_stock=opening, soil_after=r.soil, farmland=r.farmland, investment=plan, soil_care=care,
             capital_effect=effect, used={g: sum(post[g] for post in
                 (plan["upkeep_used"], care["used"], plan["build_used"], plan["sector_used"])) for g in GOODS})
    if level is not None:
        numerator = (p["active_farmers"] * 32 * r.productivity * r.technology * r.fertility *
                     p["soil_before"] * climate * p["equipment"])
        p.update(farm_tech_level=level, food_without_tech=numerator*(multipliers["farm"]-bonus)//(10*1000**7))
    return p


def _private_workers(population, assigned):
    if type(assigned) is not int or not 0 <= assigned <= population//2:
        raise ValueError("unfunded public labor")
    return population//2 - assigned


def produce_regions(regions, climate_by_owner, investment_scope="regional", soil_care=True, *, public_labor=None,
                    farm_levels=None):
    """Plan from local opening stocks first; commit all regions together after production."""
    if investment_scope not in ("regional", "national") or type(soil_care) is not bool:
        raise ValueError("expected regional/national investment scope and boolean soil_care")
    originals = {r.id: r for r in regions}
    if farm_levels is not None and (farm_levels.keys() != originals.keys() or
                                    any(type(v) is not int or v not in (0, 1) for v in farm_levels.values())):
        raise ValueError("field-trial levels must cover actual regions and be zero or one")
    public_labor = {} if public_labor is None else public_labor
    if public_labor.keys() - originals.keys():
        raise ValueError("public labor assigned to unknown region")
    if len(originals) != len(regions):
        raise ValueError("duplicate region ID")
    working, plans, operating, owners = {}, {}, {}, defaultdict(list)
    for uid, source in originals.items():
        if (not 0 <= source.farmland <= source.land or source.owner not in climate_by_owner
                or type(climate_by_owner[source.owner]) is not int or climate_by_owner[source.owner] < 0):
            raise ValueError("invalid regional land or missing owner climate")
        balances = (source.population, source.cash, source.deposit, *source.stock.values())
        if set(source.stock) != set(GOODS) or any(type(q) is not int or q < 0 for q in balances):
            raise ValueError("invalid opening resource or population")
        if set(source.capital) != set(ASSETS):
            raise ValueError("invalid opening asset classes")
        for ages in source.capital.values():
            if (len(ages) != LIFE or any(type(q) is not int or q < 0 for q in ages)
                    or sum(ages) > (source.land + 5) // 6):
                raise ValueError("invalid opening asset cohorts")
        r = replace(source, stock=source.stock.copy(), capital={k:v.copy() for k,v in source.capital.items()})
        working[uid] = r
        workers = _private_workers(r.population, public_labor.get(uid, 0))
        level = farm_levels[uid] if farm_levels is not None else 0
        plans[uid] = _plan(r, climate_by_owner[r.owner], soil_care, workers, FARM_BONUS*level)
        operating[uid] = plans[uid][1]["operated"]
        owners[r.owner].append((uid, workers, r.farmland))
    effects = _allocate(owners, operating, investment_scope)
    traces = {uid: _finish(r, *plans[uid], effects[uid], climate_by_owner[r.owner],
                           r.population//2 - public_labor.get(uid, 0),
                           None if farm_levels is None else farm_levels[uid]) for uid,r in working.items()}
    for uid, source in originals.items():
        r = working[uid]
        source.stock, source.capital, source.soil, source.deposit = r.stock, r.capital, r.soil, r.deposit
    return traces


def _equal(actual, expected, field):
    if actual != expected:
        raise ValueError(f"regional production mismatch: {field}")


def _check_fields(actual, expected, stage):
    for key, value in expected.items():
        _equal(actual[key], value, f"{stage}.{key}")


def _physical(state, opening, workers, climate, capacity, farm_factor, industry_factor, target):
    """Separate, read-only calculation from primary factors rather than posted outputs."""
    share = max(450, 760 - 220*opening["food"]//max(1,state["population"]))
    farmers = workers*share//1000
    miners = (workers-farmers)//2
    artisans = workers-farmers-miners
    original = {"farm": farmers, "mine": miners, "factory": artisans}
    active = min(farmers, capacity)
    overflow = farmers-active
    reassigned = {"mine": overflow//2, "factory": overflow-overflow//2}
    miners += reassigned["mine"]
    artisans += reassigned["factory"]
    labor = {"farm": active, "mine": miners, "factory": artisans}
    wear_need = (active+29)//30
    wear = min(wear_need, opening["tools"])
    equipment = 1000 + 150*wear//max(1,wear_need)
    skill = state["productivity"]*state["technology"]
    food = (active*32*skill*state["fertility"]*state["soil"]*climate*equipment*farm_factor)//(10*1000**7)
    mining = miners*skill*state["ore_grade"]*industry_factor//(2*1000**4)
    ore = min(mining, state["deposit"])
    factory = artisans*skill*industry_factor//(3*1000**3)
    raw = opening["ore"]+ore
    tools = min(factory, raw//2, max(0,target-(opening["tools"]-wear)))
    produced = {"food": food, "ore": ore, "tools": tools}
    used = {"food": 0, "ore": tools*2, "tools": wear}
    after = {g: opening[g]+produced[g]-used[g] for g in GOODS}
    return {
        "workers": workers, "land_capacity": capacity, "farm_share": share,
        "labor_before": original, "reassigned": reassigned, "labor": labor, "active_labor": labor,
        "active_farmers": active, "idle_before": overflow, "idle_after": 0,
        "tool_need": wear_need, "equipment": equipment, "mining_capacity": mining, "factory_capacity": factory,
        "ore_available": raw, "factory_ore_limit": raw//2, "erosion": 8*active//max(1,capacity),
        "produced": produced, "used": used, "closing_stock": after,
    }


def _check_host(s, end, p, climate, care_enabled, workers, farm_bonus):
    farmland, area, opening = s["farmland"], s["land"], s["stock"]
    if not 0 <= farmland <= area or set(opening) != set(GOODS):
        raise ValueError("invalid regional opening stocks or land")
    if any(type(q) is not int or q < 0 for q in (*opening.values(), s["population"], s["cash"], s["deposit"])):
        raise ValueError("invalid regional opening quantity")
    for key in s.keys()-{"stock","deposit","soil","capital"}:
        _equal(end[key], s[key], f"fixed regional state {key}")
    plan, care = p["investment"], p["soil_care"]
    paid = opening.copy()
    operated = {}
    cap = (area+5)//6
    cohorts = s["capital"]
    _equal(set(cohorts), set(ASSETS), "asset classes")
    for k in ASSETS:
        ages = cohorts[k]
        if len(ages) != LIFE or any(type(n) is not int or n<0 for n in ages) or sum(ages)>cap:
            raise ValueError("invalid regional opening cohort")
        n = min(sum(ages), paid["tools"])
        if k == "industry":
            n = min(n, paid["ore"])
            paid["ore"] -= n
        paid["tools"] -= n
        operated[k] = n
    upkeep = {g: opening[g]-paid[g] for g in GOODS}
    _check_fields(plan, {"policy":"capital", "opening_capital":cohorts, "operated":operated,
                         "class_limit":cap, "upkeep_used":upkeep,"stock_after_upkeep":paid}, "investment")
    possible = min((farmland+7)//8, workers//4, paid["ore"], paid["tools"])
    gain = (min(8*possible,farmland)*8//max(1,farmland)) if care_enabled and s["soil"]<950 else 0
    packages = (gain*farmland+63)//64
    care_used = {"food":0, "ore":packages, "tools":packages}
    _check_fields(care, {"enabled":care_enabled, "packages":packages, "treated_tiles":min(farmland,8*packages),
                         "workers":4*packages,"used":care_used}, "soil care")
    workers -= 4*packages
    local = {g: paid[g]-care_used[g] for g in GOODS}
    share = max(450,760-220*opening["food"]//max(1,s["population"]))
    parts = {"farm_wear":(min(workers*share//1000,24*farmland)+29)//30, "trade_buffer":s["population"]//40,
             "project_buffer":12 if farmland and workers>=6 else 0,"replacement_buffer":(30*cap+7)//8}
    target = sum(parts.values())
    limits = {"food":s["population"]+s["population"]//8, "ore":s["population"]//20,"tools":target}
    _check_fields(plan, {"stock_after_care":local, "target_components":parts,"tool_target":target,
                         "forecast_limits":limits,"forecast_horizon":5}, "planning")

    def forecast(equipment):
        return _physical(s,local,workers,climate,20*farmland+min(4*farmland,24*equipment["land"]),
                         1000+farm_bonus+12*equipment["farm"],1000+25*equipment["industry"],target)["closing_stock"]

    base = forecast(operated)
    _equal(plan["forecast_base_stock"],base,"base forecast")
    recipes = {"farm":(8,8,6,12),"industry":(12,12,8,16),"land":(10,6,12,12)}
    scores = {}
    for k,(tools,ore,labor,annual) in recipes.items():
        alternative = forecast({**operated,k:operated[k]+1})
        changes = {g:min(limits[g],alternative[g])-min(limits[g],base[g]) for g in GOODS}
        value = 8*changes["food"]+4*changes["ore"]+12*changes["tools"]
        material = tools*12+ore*4
        score = 5*(value-annual)-material-8*labor
        reasons = []
        if sum(cohorts[k][:-1]) >= cap:
            reasons.append("class_limit")
        if workers < labor:
            reasons.append("workers")
        if local["tools"] < tools + parts["farm_wear"]:
            reasons.append("tools_after_farm_reserve")
        if local["ore"] < ore:
            reasons.append("ore")
        if score <= 0:
            reasons.append("nonpositive_return")
        _check_fields(plan["candidates"][k], {"forecast_stock":alternative,"valued_stock_change":changes,
                      "annual_gain_value":value,"build_material_value":material,"annual_upkeep_value":annual,
                      "construction_labor_value":8*labor,"net_value":score,"constraints":reasons}, "candidate "+k)
        if not reasons:
            scores[k] = score
    selected = max(scores,key=scores.get) if scores else None
    built = {k:int(selected==k) for k in ASSETS}
    tools,ore,labor,_ = recipes.get(selected,(0,0,0,0))
    build_used = {"food":0,"ore":ore,"tools":tools}
    closing_capital = {k:[built[k],*cohorts[k][:-1]] for k in ASSETS}
    after_build = {g:local[g]-build_used[g] for g in GOODS}
    _check_fields(plan, {"built":built,"retired":{k:cohorts[k][-1] for k in ASSETS},
                         "build_used":build_used,"stock_after_build":after_build,"construction_labor":labor,
                         "closing_capital":closing_capital}, "construction")
    _equal(end["capital"], closing_capital, "end capital")
    for k,(tools,ore,builders,_) in recipes.items():
        cost = 12*tools+4*ore+8*builders
        _equal(plan["book"][k], {
            "open_eighths":sum((8-i)*count*cost for i,count in enumerate(cohorts[k])),
            "close_eighths":sum((8-i)*count*cost for i,count in enumerate(closing_capital[k])),
            "additions_eighths":8*built[k]*cost, "depreciation_eighths":sum(cohorts[k])*cost,
        },"regional book "+k)
    return operated, workers-labor, after_build, target


def audit_production(opening, closing, traces, climate_by_owner, investment_scope="regional", soil_care=True,
                     *, public_labor=None, farm_levels=None):
    """Verify saved country-group effects and every local sector using independent formulas."""
    before, after, rows = ({int(i):v for i,v in source.items()} for source in (opening, closing, traces))
    climate_by_owner = {int(owner): weather for owner, weather in climate_by_owner.items()}
    public_labor = {} if public_labor is None else {int(i): n for i, n in public_labor.items()}
    if public_labor.keys() - before.keys():
        raise ValueError("unknown public work crew")
    if before.keys()!=after.keys() or before.keys()!=rows.keys() or investment_scope not in ("regional","national"):
        raise ValueError("inconsistent regional production boundaries or investment scope")
    prepared, owners = {}, defaultdict(list)
    for uid,s in before.items():
        _equal(s["id"],uid,"region ID")
        owners[s["owner"]].append(uid)
        workers = _private_workers(s["population"], public_labor.get(uid, 0))
        level = farm_levels[uid] if farm_levels is not None else 0
        prepared[uid] = _check_host(s,after[uid],rows[uid],climate_by_owner[s["owner"]],soil_care,workers,FARM_BONUS*level)
    for owner,ids in owners.items():
        eligible = {k:sorted(i for i in ids if before[i]["population"]//2 > public_labor.get(i, 0)
                             and (k=="industry" or before[i]["farmland"]>0))
                    for k in BONUS}
        budget = {k:sum(prepared[i][0][k] for i in ids)*rate for k,rate in BONUS.items()}
        for uid in ids:
            s,p,end = before[uid],rows[uid],after[uid]
            plan,care,effect = p["investment"],p["soil_care"],p["capital_effect"]
            operated,workers,stock,target = prepared[uid]
            _equal(effect["scope"],investment_scope,"service scope")
            applied={}
            for k,rate in BONUS.items():
                roster=eligible[k]
                rank=roster.index(uid) if uid in roster else -1
                host=rate*operated[k]
                share=host
                if investment_scope=="national":
                    share=0 if rank<0 else (budget[k] + len(roster) - 1 - rank)//len(roster)
                applied[k]=share
                for name,expected in (("host_bonus",host),("owner_bonus_pool",budget[k]),("eligible_regions",len(roster)),
                                      ("recipient_rank",rank),("applied_bonus",share),
                                      ("unallocated",budget[k] if investment_scope=="national" and not roster else 0)):
                    _equal(effect[name][k],expected,name+"."+k)
            extra = min(4*s["farmland"],24*operated["land"])
            cap=20*s["farmland"]
            climate=climate_by_owner[owner]
            bonus = FARM_BONUS * (farm_levels[uid] if farm_levels is not None else 0)
            actual=_physical(s,stock,workers,climate,cap+extra,1000+bonus+applied["farm"],1000+applied["industry"],target)
            reference=_physical(s,stock,workers,climate,cap,1000+bonus,1000,target)
            if farm_levels is not None:
                if type(p.get("farm_tech_level")) is not int or type(p.get("food_without_tech")) is not int:
                    raise ValueError("field-trial production quantities must be integers")
                untreated = (_physical(s,stock,workers,climate,cap+extra,1000+applied["farm"],1000+applied["industry"],target)
                             if bonus else actual)
                _check_fields(p, {"farm_tech_level":farm_levels[uid], "food_without_tech":untreated["produced"]["food"]},
                              "agricultural technique")
            sector=actual.pop("used")
            _check_fields(p,actual,"posted sector")
            differences={g:actual["produced"][g]-sector[g]-reference["produced"][g]+reference["used"][g] for g in GOODS}
            _check_fields(plan, {"sector_used":sector,"reference_output":reference["produced"],"reference_used":reference["used"],
                                 "farm_multiplier":1000+bonus+applied["farm"],"industry_multiplier":1000+applied["industry"],
                                 "added_land_capacity":extra,"net_output_gain":differences,
                                 "gross_gain_value":sum(BASE_PRICES[g]*differences[g] for g in GOODS)},"actual equipment")
            natural = min(1150,max(550,s["soil"]+6-actual["erosion"])) if s["farmland"] else s["soil"]
            recovery = min(max(0,1000-natural),8*care["treated_tiles"]//max(1,s["farmland"]))
            _check_fields(care,{"natural_soil":natural,"recovery":recovery,"closing_soil":natural+recovery},"land condition")
            total_used={g:sector[g]+care["used"][g]+plan["upkeep_used"][g]+plan["build_used"][g] for g in GOODS}
            remaining_deposit=s["deposit"]-actual["produced"]["ore"]
            _check_fields(p,{"opening_stock":s["stock"],"used":total_used,"soil_before":s["soil"],"soil_after":natural+recovery,
                             "deposit_before":s["deposit"],"deposit_after":remaining_deposit,"climate":climate,
                             "land":s["land"],"farmland":s["farmland"],"population":s["population"],
                             "productivity":s["productivity"], "technology":s["technology"],"fertility":s["fertility"],
                             "ore_grade":s["ore_grade"], "labor_policy":"reallocate"},"region boundary")
            _check_fields(end,{"stock":actual["closing_stock"],"soil":natural+recovery,"deposit":remaining_deposit},"end state")
