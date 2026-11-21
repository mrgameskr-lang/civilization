"""5.0D collective action, persistent campaigns and one-year fiscal counterfactuals."""
from copy import deepcopy
from dataclasses import dataclass, replace

from .audit import BalanceError
from .collective_rules import ACTIVE, empty_memory, mobilize_region
from .competition import _prepare, competition_snapshot, start_competition, step_competition
from .government import _advance_fiscal
from .political_rules import GROUPS
from .politics import PoliticalWorld


@dataclass(slots=True)
class CollectiveWorld:
    competition: object
    memory: dict
    enabled: bool | None = None

    @property
    def world(self):
        return self.competition.world


def start_collective(world):
    return CollectiveWorld(start_competition(world), {r.id: empty_memory() for r in world.regions})


def collective_snapshot(sim):
    return {"competition": competition_snapshot(sim.competition), "enabled": sim.enabled,
            "regions": [{"id": i, "groups": deepcopy(m)} for i, m in sorted(sim.memory.items())]}


def _closing_rows(record):
    politics = {r["id"]: r["closing"] for r in record["politics"]["regions"]}
    gov = record["government"]
    levies = {l["region"]: l for l in gov["levies"]}
    built = {i for p in gov["works"]["projects"] if p["action"] == "build" for i in p["edge"]}
    result = {}
    for r in record["collective"]["regions"]:
        i = r["id"]
        levy, observation = levies[i], politics[i]
        result[i] = {}
        for name, group in r["groups"].items():
            evidence = observation["evidence"]
            delivered = {
                "relief": observation["groups"][name]["relief_food"] > 0,
                "soil": evidence["public_soil_gain"] > 0,
                "road": i in built,
                "reserve": levy["extra_levy"]["food"] > 0,
                "defer": False,
            }
            concession = sum(levy["civic_tax"]["by_group"][name]["concession"].values()) > 0
            answered = group["action"] in ACTIVE and (concession or delivered.get(group["demand"], False))
            prior = group["prior"]
            rest = max(0, prior["rest"]-1)
            if group["action"] not in ACTIVE and prior["action"] in ACTIVE:
                rest = 1
            result[i][name] = {"action": group["action"], "demand": group["demand"],
                               "duration": group["duration"], "campaign": group["campaign"],
                               "rest": rest, "answered": answered, "opening_discontent": group["discontent"]}
    return result


def finish_actions(record):
    closing = _closing_rows(record)
    for r in record["collective"]["regions"]:
        for name, g in r["groups"].items():
            g["closing"] = closing[r["id"]][name]


def audit_actions(record, previous_record=None):
    """Reconstruct decisions from opening inputs and trace concessions/answers to real receipts."""
    ctx = record["collective"]
    places = {r["id"]: r["opening"] for r in record["regions"]}
    states = {r["id"]: r["opening"] for r in record["politics"]["regions"]}
    rows = {r["id"]: r for r in ctx["regions"]}
    if rows.keys() != places.keys() or len(rows) != len(ctx["regions"]):
        raise BalanceError("incomplete collective geography")
    suppressed = ctx["suppressed"]
    if suppressed is not None and (suppressed["region"] not in rows or suppressed["group"] not in GROUPS):
        raise BalanceError("intervention outside the population")
    previous = {}
    if previous_record is not None:
        prev = previous_record.get("collective")
        if prev is None or prev["suppressed"] is not None:
            raise BalanceError("incompatible prior collective record")
        previous = {r["id"]: {name: g["closing"] for name, g in r["groups"].items()} for r in prev["regions"]}
    closings = _closing_rows(record)
    for i, row in rows.items():
        groups = row["groups"]
        memory = {name: g["prior"] for name, g in groups.items()}
        if ((record["year"] == 1 and memory != empty_memory()) or
                (previous_record is not None and memory != previous[i])):
            raise BalanceError("campaign history differs from last closing")
        group_id = suppressed["group"] if suppressed is not None and suppressed["region"] == i else None
        expected = mobilize_region(i, places[i]["population"], states[i], memory, group_id)
        for name in GROUPS:
            expected["groups"][name]["closing"] = closings[i][name]
        if row != expected:
            raise BalanceError("collective decision or realized answer differs from its inputs")
        if (sum(g["participants"] for g in groups.values()) > places[i]["population"]
                or sum(g["withheld_workers"] for g in groups.values()) > places[i]["population"] // 2):
            raise BalanceError("mobilization exceeds the available population or labor")


def _trial(sim, year, suppress=None):
    race = sim.competition
    states = race.political.states
    if type(year) is not int or year != sim.world.year+1:
        raise ValueError("expected the next consecutive year")
    if suppress is not None and (suppress["region"] not in states or suppress["group"] not in GROUPS):
        raise ValueError("unknown intervention group")
    context = {"regions": [
        mobilize_region(r.id, r.population, states[r.id], sim.memory[r.id],
                        suppress["group"] if suppress and suppress["region"] == r.id else None)
        for r in sim.world.regions], "responses": [], "suppressed": suppress}
    election = _prepare(year, states, race.cabinets, "C", "fixed")
    fiscal = replace(race.political.fiscal)
    record = _advance_fiscal(fiscal, year, "integrated", political_open=states, feedback=True,
                             competition=election, collective=context)
    return fiscal, record


def step_collective(sim, year, enabled=True):
    if type(enabled) is not bool or sim.enabled is not None and sim.enabled != enabled:
        raise ValueError("choose one collective policy per trajectory")
    if not enabled:
        row = step_competition(sim.competition, year, "C")
        sim.enabled = False
        return row
    fiscal, row = _trial(sim, year)
    states = {r["id"]: deepcopy(r["closing"]) for r in row["politics"]["regions"]}
    cabinets = {c["id"]: deepcopy(c["closing"]) for c in row["competition"]["countries"]}
    memory = {r["id"]: {k: g["closing"].copy() for k, g in r["groups"].items()}
              for r in row["collective"]["regions"]}
    sim.competition.political = PoliticalWorld(fiscal, states, True)
    sim.competition.arm, sim.competition.tax_policy, sim.competition.cabinets = "C", "fixed", cabinets
    sim.memory, sim.enabled = memory, True
    return row


def fork_action_year(sim, year, region, group):
    """Suppress one opening decision. Recompute responses and all flows; keep source unchanged."""
    if sim.enabled is not True:
        raise ValueError("source must be an active 5.0D trajectory")
    _, actual = _trial(sim, year)
    _, suppressed = _trial(sim, year, {"region": region, "group": group})
    return actual, suppressed
