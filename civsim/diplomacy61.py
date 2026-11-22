"""6.0A.1. Isolate three diplomatic instruments without changing the 6.0A controls."""
from copy import deepcopy
from dataclasses import replace
from itertools import combinations

from .audit import BalanceError
from .border import border_market, move_people, validate_border_paths
from .civic_fiscal import collect_civic, respond, withheld_labor
from .collective import _commit_collective, finish_actions
from .collective_rules import mobilize_region
from .competition import _prepare, authorize_plans
from .diplomacy import _diplomatic_year, diplomacy_snapshot, start_diplomacy
from .diplomatic_rules import (_choices, _close_pair, _countries, _direction, _empty_pair, _movements,
                               _plan_aid, audit_diplomatic_rules, finish_diplomacy, prepare_diplomacy)
from .economy import consume
from .government import _plans
from .government_audit import country_accounts
from .logistics import ship
from .model import climate_factor
from .politics import political_ledger
from .public_works import ROAD_BONUS, execute_relief, execute_works, residual_roads
from .regional_engine import _audit_residents, _copy, audit_borders, state
from .regional_production import audit_production, produce_regions
from .regions import audit_regions, sync_nations


ARMS = ("A","B","C","D","E","F")
LEGACY = {"A":"C","E":"D"}


def start61(world):
    return start_diplomacy(world)


def snapshot61(sim):
    return diplomacy_snapshot(sim)


def _check(value,message):
    if not value:
        raise BalanceError("6.0A.1: "+message)


def _mode(arm,suppression=None):
    _check(arm in ARMS,"unknown instrument configuration")
    return {"arm":arm,"aid":arm in ("B","E","F"),"export":arm in ("C","E","F"),
            "migration":arm in ("D","E","F"),"capped":arm=="F","suppress_aid":suppression}


def _activate(pairs,countries,mode):
    """Start from treaties alone. Generate applications/offers only in arms that can act on them."""
    by_id = {n["id"]:n for n in countries}
    if mode["export"] or mode["migration"]:
        for row in pairs:
            old = row["opening"]
            for i,d in enumerate(row["policy"]["directions"]):
                n,o = d["source"],d["target"]
                full = _direction(by_id[n],by_id[o],old,old["last"][i],old["last"][1-i],
                                  d["border_capacity"],d["border_distance"],"D")
                if mode["export"]:
                    d["trade_limit_permille"] = full["trade_limit_permille"]
                if mode["migration"]:
                    d["migration_limit_permille"] = full["migration_limit_permille"]
                    d["migration_accept_permille"] = full["migration_accept_permille"]
    if mode["aid"]:
        _plan_aid(pairs,by_id)
    suppression = mode["suppress_aid"]
    if suppression is not None:
        _check(mode["aid"] and isinstance(suppression,list) and len(suppression)==2
               and all(type(n) is int for n in suppression),"invalid suppressed direction")
        ok = any([d["source"],d["target"]]==suppression and d["aid_accepted"] and d["aid_quantity"]>=2
                 for r in pairs for d in r["policy"]["directions"])
        _check(ok,"suppression requires an approved positive shipment")
    return pairs


def _context(sim,year,mode,intervention):
    ctx = prepare_diplomacy(sim.collective,year,"C",sim.pairs)
    _activate(ctx["pairs"],ctx["countries"],mode)
    ctx.update(arm="D",phase61=mode,intervention=intervention)
    return ctx


def audit_fiscal61(record,previous_record=None,*,geography=None):
    from .aid_budget61 import audit_fiscal61 as audit
    audit(record,previous_record=previous_record,geography=geography)


def _stage_selective(sim,year,mode,intervention):
    """Stage on copied financial/physical state. Commit only after the complete specialized audit."""
    from .aid_budget61 import BudgetFlows
    ctx = _context(sim,year,mode,intervention)
    collective = sim.collective
    race = collective.competition
    states = race.political.states
    fiscal = replace(race.political.fiscal)
    source = fiscal.world
    audit_regions(source)
    validate_border_paths(source.regions,source.borders,source.width)
    trial = replace(source,regions=[_copy(r) for r in source.regions],nations=[_copy(n) for n in source.nations])
    local,roads = trial.regions,trial.roads
    opening = {r.id:state(r) for r in local}
    depots = {i:s.copy() for i,s in fiscal.depots.items()}
    civic = {"regions":[mobilize_region(r.id,r.population,states[r.id],collective.memory[r.id],None) for r in local],
             "responses":[],"suppressed":None}
    election = _prepare(year,states,race.cabinets,"C","fixed")
    mode_fiscal = "integrated"
    economic = _plans(source,fiscal,mode_fiscal)
    decisions,recommendations = authorize_plans(economic,states,election)
    unavailable = withheld_labor(local,civic)
    for owner,plan in decisions.items():
        voices = [r for r in civic["regions"] if r["owner"]==owner]
        decisions[owner],response = respond(plan,voices)
        civic["responses"].append(response)
    works,next_units,residual,labor = execute_works(local,roads,depots,fiscal.road_units,decisions,
                                                   width=trial.width,withheld=unavailable)
    climate = {n.id:climate_factor(trial.seed,year,n.id) for n in trial.nations}
    prod_open = {r.id:{**opening[r.id],"soil":r.soil} for r in local}
    reserved = {i:n+unavailable.get(i,0) for i,n in labor.items()}
    prod = produce_regions(local,climate,public_labor=reserved)
    for i,n in unavailable.items():
        prod[i]["withheld_workers"]=n
    produced = {r.id:state(r) for r in local}
    audit_production(prod_open,produced,prod,climate,public_labor=reserved)
    foreign = BudgetFlows(ctx,local,trial.borders,trial.width)
    foreign.send_aid(depots)
    market = border_market(local,trial.borders,access=foreign)
    audit_borders(local,trial.borders,market,produced,{r.id:(r.stock.copy(),r.cash) for r in local})
    levies = collect_civic(local,depots,decisions,civic)
    admin = {r["id"]:r["admin_remaining"] for r in civic["responses"]}
    relief,left = execute_relief(local,roads,depots,decisions,residual,admin,width=trial.width)
    freight = ship(local,residual_roads(roads,left),"limited",width=trial.width)
    delivered = {r.id:r.stock.copy() for r in local}
    meals = {r.id:consume(r) for r in local}
    paths = [*roads,*trial.borders]
    vital,moves = move_people(local,meals,paths,access=foreign)
    _audit_residents(local,opening,meals,vital,moves,paths,delivered)
    warehouses = []
    for r in local:
        remaining = depots[r.id]
        loss = remaining["food"]//12
        remaining["food"] -= loss
        warehouses.append({"region":r.id,"owner":r.owner,"opening":fiscal.depots[r.id].copy(),
                           "spoil_food":loss,"closing":remaining.copy()})
    sync_nations(trial)
    audit_regions(trial)
    record = {"year":year,"countries":[{"id":n.id,"opening":state(old),"closing":state(n)}
                                       for old,n in zip(source.nations,trial.nations,strict=True)],
              "regions":[{"id":r.id,"owner":r.owner,"opening":opening[r.id],"climate":climate[r.owner],
                          "production":prod[r.id],"consumption":meals[r.id],"demography":vital[r.id],
                          "closing":state(r)} for r in local],"border_market":market,"domestic":freight,"moves":moves}
    edge_rows = []
    civil_edges = {(e["a"],e["b"]):e for e in freight["roads"]}
    for e in roads:
        key = e.a,e.b
        capacity = e.capacity+ROAD_BONUS*fiscal.road_units[key]
        civil = civil_edges[key]
        edge_rows.append({"a":e.a,"b":e.b,"owner":local[e.a].owner,"base":e.capacity,
                          "opening_units":fiscal.road_units[key],"closing_units":next_units[key],
                          "capacity":capacity,"next_capacity":e.capacity+ROAD_BONUS*next_units[key],
                          "works_use":capacity-residual[key],"relief_use":residual[key]-left[key],
                          "private_use":civil["used"],"unused":civil["remaining"]})
    gov = {"mode":mode_fiscal,"depots":warehouses,"levies":levies,"works":works,"relief":relief,"roads":edge_rows}
    ctx["physical"] = foreign.trace()
    record.update(government=gov,diplomacy=ctx)
    gov["accounts"] = country_accounts(record,decisions)
    record["competition"] = election
    record["politics"] = political_ledger(record,states,recommendations,True)
    record["collective"] = civic
    finish_actions(record)
    finish_diplomacy(record)
    audit_fiscal61(record,geography=source)
    fiscal.previous = {r.id:{"unmet":meals[r.id]["food_unmet"],"pop_delta":r.population-opening[r.id]["population"],
                             "food_output":prod[r.id]["produced"]["food"],"food_need":meals[r.id]["food_need"],
                             "soil_delta":r.soil-opening[r.id]["soil"]} for r in local}
    trial.year = year
    fiscal.world,fiscal.depots,fiscal.road_units,fiscal.mode = trial,depots,next_units,mode_fiscal
    fiscal.road_use = {(e["a"],e["b"]):e["capacity"]-e["unused"] for e in edge_rows}
    return fiscal,record


def _stage(sim,year,arm,*,suppression=None,intervention=None):
    if arm in LEGACY and intervention is None:
        return _diplomatic_year(sim,year,LEGACY[arm])
    return _stage_selective(sim,year,_mode(arm,suppression),intervention)


def _next(sim,year,arm):
    _check(type(year) is int and year==sim.world.year+1,"expected the next consecutive year")
    _check(arm in ARMS and (sim.arm is None or sim.arm==arm),"cannot switch the trajectory configuration")


def step61(sim,year,arm):
    _next(sim,year,arm)
    fiscal,record = _stage(sim,year,arm)
    closing = {(p["a"],p["b"]):deepcopy(p["closing"]) for p in record["diplomacy"]["pairs"]}
    _commit_collective(sim.collective,fiscal,record)
    sim.arm,sim.pairs = arm,closing
    return record


def fork61(sim,year,arm,*,suppress_aid=None,capped=None):
    _next(sim,year,arm)
    _check((suppress_aid is None)!=(capped is None),"choose exactly one counterfactual")
    if suppress_aid is not None:
        _check(isinstance(suppress_aid,(tuple,list)) and len(suppress_aid)==2,"expected donor and recipient")
        suppression = list(suppress_aid)
        mode = arm
        change = {"kind":"suppress_aid61","source":suppression[0],"target":suppression[1]}
    else:
        _check(type(capped) is bool and (arm,capped) in (("E",True),("F",False)),
               "compare the two full-instrument arms with an alternative physical cap")
        suppression = None
        mode = "F" if capped else "E"
        change = {"kind":"aid_cap61","base_arm":arm,"capped":capped}
    _,regular = _stage(sim,year,arm)
    _,changed = _stage(sim,year,mode,suppression=suppression,intervention=change)
    return regular,changed


def _record_arm(record):
    ctx = record["diplomacy"]
    if "phase61" in ctx:
        return ctx["phase61"]["arm"]
    _check(ctx["arm"] in ("C","D"),"unrecognized legacy control")
    return "A" if ctx["arm"]=="C" else "E"


def _validate_configuration(ctx):
    cfg,change = ctx["phase61"],ctx["intervention"]
    arm,suppression = cfg["arm"],cfg["suppress_aid"]
    _check(cfg==_mode(arm,suppression) and all(type(cfg[k]) is bool for k in ("aid","export","migration","capped")),
           "activation metadata inconsistent with arm")
    if suppression is not None:
        _check(isinstance(suppression,list) and len(suppression)==2 and cfg["aid"]
               and all(type(x) is int for x in suppression),"malformed aid suppression")
        _check(change=={"kind":"suppress_aid61","source":suppression[0],"target":suppression[1]},
               "suppression lacks its signed direction")
    elif change is not None:
        base = "E" if arm=="F" else "F"
        _check(arm in ("E","F") and change=={"kind":"aid_cap61","base_arm":base,"capped":cfg["capped"]}
               and type(change["capped"]) is bool,"invalid cost-cap fork metadata")
        return base
    else:
        _check(arm in ("B","C","D","F"),"compatibility controls must retain the original annual schema")
    return arm


def audit_rules61(record,previous_record=None):
    ctx = record["diplomacy"]
    if "phase61" not in ctx:
        if previous_record is not None:
            _check(_record_arm(record)==_record_arm(previous_record),"legacy control changed configuration")
        return audit_diplomatic_rules(record,previous_record)
    year = record["year"]
    base = _validate_configuration(ctx)
    _check(ctx["arm"]=="D" and ctx["year"]==year,"invalid international ledger version or year")
    memories = {(r["a"],r["b"]):r["opening"] for r in ctx["pairs"]}
    nation_ids = sorted(n["id"] for n in record["countries"])
    _check(list(memories)==list(combinations(nation_ids,2)) and len(memories)==len(ctx["pairs"]),
           "missing or duplicated country pair")
    if year==1:
        _check(all(m==_empty_pair(*k) for k,m in memories.items()),"non-neutral initial diplomatic memory")
    if previous_record is not None:
        prior = previous_record["diplomacy"]
        _check(previous_record["year"]+1==year and _record_arm(previous_record)==base
               and prior["intervention"] is None,"incompatible prior observation")
        _check(memories=={(p["a"],p["b"]):p["closing"] for p in prior["pairs"]},"broken diplomatic memory")
    owners = {r["id"]:r["owner"] for r in record["regions"]}
    borders = [{"a":e["a"],"b":e["b"],"owner_a":owners[e["a"]],"owner_b":owners[e["b"]],
                "capacity":e["capacity"],"distance":e["distance"]} for e in ctx["physical"]["roads"]]
    _check(sorted(ctx["borders"],key=lambda e:(e["a"],e["b"]))==sorted(borders,key=lambda e:(e["a"],e["b"])),
           "opening border assumptions differ from the physical network")
    camps = {r["id"]:{k:g["prior"] for k,g in r["groups"].items()} for r in record["collective"]["regions"]}
    evidence = _countries([r["opening"] for r in record["regions"]],
                          {d["region"]:d["opening"] for d in record["government"]["depots"]},
                          {r["id"]:r["opening"] for r in record["politics"]["regions"]},
                          {r["id"]:r["opening"] for r in record["competition"]["countries"]},camps,memories)
    _check(evidence==ctx["countries"],"opening national observations differ")
    choices = _choices(year,"C",memories,evidence,borders,None)
    _activate(choices,evidence,ctx["phase61"])
    flows,events = _movements(record),[]
    for actual,expected in zip(ctx["pairs"],choices,strict=True):
        expected["flows"],expected["closing"],emitted = _close_pair(expected,flows,year)
        _check(actual==expected,"opening policy, realized flows or closing memory differs")
        events.extend(emitted)
    _check(events==ctx["events"],"diplomatic events differ from receipts")
