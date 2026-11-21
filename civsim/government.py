"""Annual fiscal decisions, regional public warehouses and the 4.0 real economy."""
from dataclasses import asdict, dataclass, replace

from .border import border_market, move_people, validate_border_paths
from .economy import consume
from .fiscal_policy import MODES, collect, decide
from .government_audit import audit_fiscal_year, country_accounts
from .logistics import ship
from .model import GOODS, climate_factor
from .public_works import ROAD_BONUS, execute_relief, execute_works, residual_roads
from .regional_engine import _audit_residents, _copy, audit_borders, state
from .regional_production import audit_production, produce_regions
from .regions import RegionalWorld, audit_regions, sync_nations


@dataclass(slots=True)
class FiscalWorld:
    world: RegionalWorld
    depots: dict
    road_units: dict
    previous: dict
    road_use: dict
    mode: str | None = None


def start_government(world):
    if world.year != 0:
        raise ValueError("start fiscal runs with an initial regional world")
    audit_regions(world)
    return FiscalWorld(world, {r.id: dict.fromkeys(GOODS, 0) for r in world.regions},
                       {(e.a, e.b): 0 for e in world.roads}, {}, {})


def fiscal_snapshot(sim):
    return {"regional": asdict(sim.world), "mode": sim.mode,
            "depots": [{"region": r.id, "owner": r.owner, "stock": sim.depots[r.id].copy()}
                       for r in sim.world.regions],
            "roads": [{"a": a, "b": b, "units": n, "last_use": sim.road_use.get((a, b), 0)}
                      for (a, b), n in sorted(sim.road_units.items())],
            "previous": [{"region": i, **obs} for i,obs in sorted(sim.previous.items())]}


def _plans(world, sim, mode):
    owned = {n.id: [] for n in world.nations}
    roads = {n.id: [] for n in world.nations}
    for r in world.regions:
        owned[r.owner].append(r)
    for road in world.roads:
        roads[world.regions[road.a].owner].append(road)
    return {i: decide(i, local, roads[i], sim.depots, sim.previous, sim.road_units, mode, road_use=sim.road_use)
            for i, local in owned.items()}


def step_government(sim, year, mode):
    """Commit public and private accounts together only after all independent audits pass."""
    return _advance_fiscal(sim, year, mode)


def _advance_fiscal(sim, year, mode, *, political_open=None, feedback=False, competition=None, collective=None,
                    diplomacy=None):
    source = sim.world
    if type(year) is not int or year != source.year + 1 or mode not in MODES:
        raise ValueError("expected the next year and a supported government program")
    if sim.mode is not None and mode != sim.mode:
        raise ValueError("a fiscal run keeps its selected government policy")
    audit_regions(source)
    validate_border_paths(source.regions, source.borders, source.width)
    trial = replace(source, regions=[_copy(r) for r in source.regions], nations=[_copy(n) for n in source.nations])
    local, roads = trial.regions, trial.roads
    depots = {i: goods.copy() for i, goods in sim.depots.items()}
    opening = {r.id: state(r) for r in local}
    decisions = _plans(source, sim, mode)
    if competition is not None:
        from .competition import authorize_plans
        decisions, recommendations = authorize_plans(decisions, political_open, competition)
    elif political_open is not None:
        from .politics import select_plans
        decisions, recommendations = select_plans(decisions, political_open, feedback)
    unavailable = {}
    if collective is not None:
        from .civic_fiscal import respond, withheld_labor
        if competition is None or competition["arm"]!="C" or competition["tax_policy"]!="fixed":
            raise ValueError("collective fiscal effects require the fixed-tax C economy")
        unavailable = withheld_labor(local,collective)
        collective["responses"] = []
        for owner, plan in decisions.items():
            voices = [r for r in collective["regions"] if r["owner"]==owner]
            decisions[owner], receipt = respond(plan,voices)
            collective["responses"].append(receipt)
    works, next_units, residual, labor = execute_works(local, roads, depots, sim.road_units, decisions,
                                                        width=trial.width,withheld=unavailable)
    climate = {n.id: climate_factor(trial.seed, year, n.id) for n in trial.nations}
    prod_open = {r.id: {**opening[r.id], "soil": r.soil} for r in local}
    reserved = {i:n+unavailable.get(i,0) for i,n in labor.items()}
    prod = produce_regions(local, climate, public_labor=reserved)
    if collective is not None:
        for i,n in unavailable.items():
            prod[i]["withheld_workers"]=n
    produced = {r.id: state(r) for r in local}
    audit_production(prod_open, produced, prod, climate, public_labor=reserved)
    foreign = None
    if diplomacy is not None:
        from .diplomatic_flows import ForeignFlows
        foreign = ForeignFlows(diplomacy,local,trial.borders,trial.width)
        foreign.send_aid(depots)
    market = border_market(local, trial.borders, access=foreign)
    audit_borders(local, trial.borders, market, produced, {r.id:(r.stock.copy(), r.cash) for r in local})
    if collective is not None:
        from .civic_fiscal import collect_civic
        levies = collect_civic(local,depots,decisions,collective)
    elif competition is not None and competition["tax_policy"] == "platform":
        from .tax_policy5c import collect_with_rates
        tariffs = {c["id"]: c["tariff"] for c in competition["countries"]}
        levies = collect_with_rates(local, depots, decisions, mode, tariffs)
    else:
        levies = collect(local, depots, decisions, mode)
    admin_limits = {owner: plan["relief_throughput"] if mode != "none" else 0
                    for owner, plan in decisions.items()}
    if collective is not None:
        admin_limits = {r["id"]:r["admin_remaining"] for r in collective["responses"]}
    relief, left = execute_relief(local, roads, depots, decisions, residual, admin_limits, width=trial.width)
    freight = ship(local, residual_roads(roads, left), "limited", width=trial.width)
    delivered = {r.id: r.stock.copy() for r in local}
    meals = {r.id: consume(r) for r in local}
    paths = [*roads, *trial.borders]
    vital, moves = move_people(local, meals, paths, access=foreign)
    _audit_residents(local, opening, meals, vital, moves, paths, delivered)
    warehouses = []
    for r in local:
        remaining = depots[r.id]
        loss = remaining["food"]//12
        remaining["food"] -= loss
        warehouses.append({"region":r.id, "owner":r.owner, "opening":sim.depots[r.id].copy(),
                           "spoil_food":loss, "closing":remaining.copy()})
    sync_nations(trial)
    audit_regions(trial)
    record = {"year": year,
              "countries": [{"id":n.id, "opening":state(old), "closing":state(n)}
                            for old,n in zip(source.nations,trial.nations,strict=True)],
              "regions": [{"id":r.id, "owner":r.owner, "opening":opening[r.id], "climate":climate[r.owner],
                           "production":prod[r.id], "consumption":meals[r.id], "demography":vital[r.id],
                           "closing":state(r)} for r in local],
              "border_market":market, "domestic":freight, "moves":moves}
    civil_edges = {(e["a"],e["b"]):e for e in freight["roads"]}
    edge_rows = []
    for e in roads:
        key = e.a, e.b
        capacity = e.capacity + ROAD_BONUS*sim.road_units[key]
        civil = civil_edges[key]
        edge_rows.append({"a":e.a,"b":e.b,"owner":local[e.a].owner,"base":e.capacity,
                          "opening_units":sim.road_units[key],"closing_units":next_units[key],
                          "capacity":capacity,"next_capacity":e.capacity+ROAD_BONUS*next_units[key],
                          "works_use":capacity-residual[key],"relief_use":residual[key]-left[key],
                          "private_use":civil["used"],"unused":civil["remaining"]})
    gov = {"mode":mode, "depots":warehouses, "levies":levies, "works":works, "relief":relief, "roads":edge_rows}
    record["government"] = gov
    if foreign is not None:
        diplomacy["physical"] = foreign.trace()
        record["diplomacy"] = diplomacy
    gov["accounts"] = country_accounts(record, decisions)
    if competition is not None:
        record["competition"] = competition
    if political_open is not None:
        from .politics import political_ledger
        record["politics"] = political_ledger(record, political_open, recommendations, feedback)
    if collective is not None:
        from .collective import finish_actions
        record["collective"] = collective
        finish_actions(record)
    if diplomacy is not None:
        from .diplomatic_rules import finish_diplomacy
        finish_diplomacy(record)
    audit_fiscal_year(record,geography=source)
    previous = {r.id: {"unmet":meals[r.id]["food_unmet"], "pop_delta":r.population-opening[r.id]["population"],
                       "food_output":prod[r.id]["produced"]["food"], "food_need":meals[r.id]["food_need"],
                       "soil_delta":r.soil-opening[r.id]["soil"]} for r in local}
    trial.year = year
    sim.world, sim.depots, sim.road_units = trial, depots, next_units
    sim.previous, sim.mode = previous, mode
    sim.road_use = {(e["a"],e["b"]):e["capacity"]-e["unused"] for e in edge_rows}
    return record
