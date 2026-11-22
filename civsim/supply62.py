"""Annual public-depot economy. Arm A delegates directly to the archived F rules."""
from copy import deepcopy
from dataclasses import dataclass, replace

from .border import border_market, move_people, validate_border_paths
from .civic_fiscal import collect_civic, respond, withheld_labor
from .collective import _commit_collective, finish_actions
from .collective_rules import mobilize_region
from .competition import _prepare, authorize_plans
from .diplomacy61 import _context, _mode, start61, step61, snapshot61
from .diplomatic_rules import finish_diplomacy
from .economy import consume
from .government import _plans
from .government_audit import _check
from .logistics import ship
from .model import climate_factor
from .politics import political_ledger
from .public_harvest import RESERVE_POLICIES
from .public_works import ROAD_BONUS, execute_relief, execute_works, residual_roads
from .regional_engine import _audit_residents, _copy, audit_borders, state
from .regional_production import audit_production, produce_regions
from .regions import audit_regions, sync_nations
from .depot_supply62 import execute_depot_supply
from .supply_audit62 import accounts62, audit62
from .supply_border62 import charge_border


@dataclass
class SupplyWorld:
    engine: object
    arm: str | None = None
    roster: dict | None = None
    unit_positions: tuple | None = None
    game_upkeep: dict | None = None
    public_farm: bool = False
    reserve_policy: str | None = None

    @property
    def world(self):
        return self.engine.world


def start62(world):
    return SupplyWorld(start61(world))


def snapshot62(sim):
    base = snapshot61(sim.engine)
    if sim.arm in (None, "A"):
        return base
    if sim.unit_positions is not None:
        base = {**base, "unit_positions":[list(row) for row in sim.unit_positions]}
    if sim.game_upkeep is not None:
        base = {**base, "game_upkeep":deepcopy(sim.game_upkeep)}
    if sim.public_farm:
        base = {**base, "public_farm":True}
    if sim.reserve_policy is not None:
        base = {**base, "reserve_policy":sim.reserve_policy}
    return {**base, "public_arm":sim.arm,
            "service_roster":[[i,n] for i,n in sorted((sim.roster or {}).items())]}


def _stage62(sim, year, arm, *, enabled=True, program=None, mode=None, recruit=True, diagnostic=None,
             unit_input=None, upkeep=None, relief_first=False, public_farm=False, reserve_policy=None):
    ctx = _context(sim.engine, year, _mode('F'), None)
    collective = sim.engine.collective
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
    service = None
    crew = dict.fromkeys(unavailable, 0)
    if program is not None:
        service = program.plan_service(local, sim.roster, ctx, mode, withheld=unavailable, recruit=recruit)
        crew = {r["id"]:r["serving"] for r in service["regions"]}
    occupied = {r.id: unavailable[r.id] + crew[r.id] for r in local}
    works,next_units,after_works,labor = execute_works(local,roads,depots,fiscal.road_units,decisions,
                                                   width=trial.width,withheld=occupied)
    supply, after_supply = execute_depot_supply(local, roads, trial.borders, depots, after_works, ctx, fiscal.previous,
                                                width=trial.width, emergency=enabled, forward=enabled)
    residual = after_supply
    unit_turn = None
    if unit_input is not None:
        from .unit_economy import absent_from_home, apply_move, begin_turn, close_turn
        _check(arm == "C" and service is not None, "annual game requires the fixed roster")
        unit_turn = begin_turn(*unit_input, service)
    if service is not None:
        options = {"away":absent_from_home(unit_turn)} if unit_turn is not None else {}
        residual = program.settle_service(service, local, depots, roads, after_supply, **options)
    climate = {n.id:climate_factor(trial.seed,year,n.id) for n in trial.nations}
    prod_open = {r.id:{**opening[r.id],"soil":r.soil} for r in local}
    reserved = {i:n+occupied[i] for i,n in labor.items()}
    prod = produce_regions(local,climate,public_labor=reserved)
    for i,n in unavailable.items():
        prod[i]["withheld_workers"]=n
    produced = {r.id:state(r) for r in local}
    audit_production(prod_open,produced,prod,climate,public_labor=reserved)
    if public_farm:
        from .public_harvest import apply_public_harvest
        harvest = apply_public_harvest(local, prod, depots, fiscal.depots, reserve_days=RESERVE_POLICIES.get(reserve_policy))
        produced = {r.id:state(r) for r in local}
    foreign = charge_border(ctx, local, trial.borders, trial.width, depots, supply)
    market = border_market(local,trial.borders,access=foreign)
    audit_borders(local,trial.borders,market,produced,{r.id:(r.stock.copy(),r.cash) for r in local})
    levies = collect_civic(local,depots,decisions,civic)
    after_move = residual
    kit = None
    if unit_turn is not None:
        after_move = residual.copy()
        apply_move(unit_turn,service,roads,depots,after_move)
    if upkeep is not None:
        from .unit_upkeep import settle
        previous = sim.game_upkeep["closing"] if sim.game_upkeep is not None else None
        if not relief_first:
            kit = settle(upkeep, previous, unit_turn, service, depots)
    admin = {r["id"]:r["admin_remaining"] for r in civic["responses"]}
    relief,left = execute_relief(local,roads,depots,decisions,after_move,admin,width=trial.width)
    if relief_first:
        kit = settle(upkeep, previous, unit_turn, service, depots, relief_first=True)
    after_emergency = left
    if reserve_policy == "emergency":
        from .emergency_relief import execute_emergency_relief
        paid = {r["id"]:r["ration_food"] for r in service["regions"]} if service else dict.fromkeys(opening, 0)
        emergency, after_emergency = execute_emergency_relief(local, roads, depots, left, relief, paid, width=trial.width)
    freight = ship(local,residual_roads(roads,after_emergency),"limited",width=trial.width)
    if service is not None:
        program.apply_service_rations(service, local)
    delivered = {r.id:r.stock.copy() for r in local}
    meals = {r.id:consume(r) for r in local}
    paths = [*roads,*trial.borders]
    vital,moves = move_people(local,meals,paths,access=foreign)
    _audit_residents(local,opening,meals,vital,moves,paths,delivered)
    if service is not None:
        program.close_service(service, vital)
    if unit_turn is not None:
        close_turn(unit_turn, service)
        if kit is not None:
            from .unit_upkeep import close
            close(kit, unit_turn, service)
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
                          "works_use":capacity-after_works[key], "supply_use":after_works[key]-after_supply[key],
                          "duty_use":after_supply[key]-residual[key], "relief_use":after_move[key]-left[key],
                          "private_use":civil["used"],"unused":civil["remaining"]})
        if unit_turn is not None:
            edge_rows[-1]["unit_use"] = residual[key]-after_move[key]
        if reserve_policy == "emergency":
            edge_rows[-1]["emergency_use"] = left[key]-after_emergency[key]
    gov = {"mode":mode_fiscal,"depots":warehouses,"levies":levies,"works":works,"relief":relief,"roads":edge_rows}
    ctx["physical"] = foreign.trace()
    record.update(government=gov,diplomacy=ctx)
    record["public_policy"] = {"model_version":"6.0B2" if program else "6.0B1", "arm":arm,
                               "supply_enabled":enabled, "recruit":recruit, "diagnostic":diagnostic}
    record["supply"] = supply
    if public_farm:
        record["public_policy"]["harvest_rule"] = harvest["version"]
        record["public_harvest"] = harvest
    if reserve_policy is not None:
        record["public_policy"]["reserve_policy"] = reserve_policy
    if reserve_policy == "emergency":
        record["emergency_relief"] = emergency
    if service is not None:
        record["service"] = service
    if unit_turn is not None:
        record["public_policy"]["unit_rule"] = unit_turn["version"]
        record["unit_game"] = unit_turn
    if kit is not None:
        record["public_policy"]["upkeep_rule"] = kit["version"]
        record["unit_upkeep"] = kit
    gov["accounts"] = accounts62(record,decisions)
    record["competition"] = election
    record["politics"] = political_ledger(record,states,recommendations,True)
    record["collective"] = civic
    finish_actions(record)
    finish_diplomacy(record)
    audit62(record, geography=source, program=program)
    fiscal.previous = {r.id:{"unmet":meals[r.id]["food_unmet"],"pop_delta":r.population-opening[r.id]["population"],
                             "food_output":prod[r.id]["produced"]["food"],"food_need":meals[r.id]["food_need"],
                             "soil_delta":r.soil-opening[r.id]["soil"]} for r in local}
    trial.year = year
    fiscal.world,fiscal.depots,fiscal.road_units,fiscal.mode = trial,depots,next_units,mode_fiscal
    fiscal.road_use = {(e["a"],e["b"]):e["capacity"]-e["unused"] for e in edge_rows}
    return fiscal,record


def _require(sim, year, arm):
    _check(type(year) is int and year == sim.world.year + 1, "expected next public-policy year")
    _check(sim.arm is None or sim.arm == arm, "cannot switch policy during a trajectory")


def advance62(sim, year, arm, *, program=None, mode=None, unit_input=None, upkeep=None, relief_first=None,
              public_farm=None, reserve_policy=None):
    _require(sim, year, arm)
    _check(reserve_policy is None or (type(reserve_policy) is str and reserve_policy in RESERVE_POLICIES),
           "unknown public reserve policy")
    _check(sim.reserve_policy is None or reserve_policy in (None, sim.reserve_policy), "reserve policy changed mid-run")
    reserve_policy = sim.reserve_policy if reserve_policy is None else reserve_policy
    if reserve_policy is not None:
        _check(public_farm is not False, "reserve policy uses public harvests")
        if public_farm is None:
            public_farm = True
    _check(public_farm is None or type(public_farm) is bool, "expected a boolean public farm selection")
    _check(not sim.public_farm or public_farm is not False, "cannot remove elected harvest rule mid-run")
    public_farm = sim.public_farm if public_farm is None else public_farm
    _check(not public_farm or arm != "A", "historical control cannot run public farms")
    _check(relief_first is None or type(relief_first) is bool, "expected a boolean relief priority")
    if sim.game_upkeep is not None:
        from .unit_upkeep import Upkeep
        carried = Upkeep(**sim.game_upkeep["selection"])
        _check(upkeep is None or upkeep == carried, "cannot replace marked pieces mid-game")
        upkeep = carried
        carried_priority = sim.game_upkeep.get("priority") == "relief_first"
        _check(relief_first is None or relief_first == carried_priority, "cannot change inventory priority mid-run")
        relief_first = carried_priority
    _check(not relief_first or upkeep is not None, "relief-first requires an inventory selection")
    _check(upkeep is None or unit_input is not None, "inventory checkout requires game locations")
    if sim.unit_positions is not None:
        _check(unit_input is not None and unit_input[0]==[list(row) for row in sim.unit_positions],
               "use the previous closing unit positions")
    elif unit_input is not None:
        _check(unit_input[0]==[], "first activation begins at home")
    if arm == "A":
        record = step61(sim.engine, year, "F")
    else:
        fiscal, record = _stage62(sim, year, arm, program=program, mode=mode, unit_input=unit_input,
                                  upkeep=upkeep, relief_first=relief_first, public_farm=public_farm,
                                  reserve_policy=reserve_policy)
        pairs = {(p["a"],p["b"]):deepcopy(p["closing"]) for p in record["diplomacy"]["pairs"]}
        _commit_collective(sim.engine.collective, fiscal, record)
        sim.engine.pairs, sim.engine.arm = pairs, "F"
        if program is not None:
            sim.roster = {r["id"]:r["closing_roster"] for r in record["service"]["regions"]}
        if unit_input is not None:
            sim.unit_positions = tuple(tuple(row) for row in record["unit_game"]["closing_away"])
        if upkeep is not None:
            sim.game_upkeep = {k:deepcopy(record["unit_upkeep"][k]) for k in ("selection","closing")}
            if relief_first:
                sim.game_upkeep["priority"] = "relief_first"
    sim.arm = arm
    sim.public_farm = public_farm
    sim.reserve_policy = reserve_policy
    return record


def step62(sim, year, arm="B"):
    _check(arm in ("A","B"), "6.0B1 arms are A and B")
    return advance62(sim, year, arm)


def fork_supply62(sim, year):
    _require(sim, year, "B")
    return (_stage62(sim, year, "B")[1],
            _stage62(sim, year, "B", enabled=False, diagnostic="hold_supply")[1])
