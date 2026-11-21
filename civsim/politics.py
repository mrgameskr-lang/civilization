"""Version 5.0B. Lagged regional preferences can rank the funded 5.0A policy menu."""
from copy import deepcopy
from dataclasses import dataclass, replace
from types import SimpleNamespace

from .audit import BalanceError
from .government import FiscalWorld, _advance_fiscal, fiscal_snapshot, start_government
from .political_rules import GROUPS, initial_politics, observe, prioritize
from .storage import canonical_line


@dataclass(slots=True)
class PoliticalWorld:
    fiscal: FiscalWorld
    states: dict
    feedback: bool | None = None

    @property
    def world(self):
        return self.fiscal.world


def start_political(world):
    return PoliticalWorld(start_government(world), initial_politics(world))


def political_snapshot(sim):
    return {"fiscal": fiscal_snapshot(sim.fiscal), "feedback": sim.feedback,
            "regions": [deepcopy(sim.states[i]) for i in sorted(sim.states)]}


def select_plans(plans, opening, feedback):
    recommendations, approved = [], {}
    for owner, plan in plans.items():
        revised, trace = prioritize(plan, opening)
        approved[owner] = revised if feedback else plan
        recommendations.append({"id": owner, "recommendation": trace})
    return approved, recommendations


def political_ledger(record, opening, recommendations, feedback):
    closing = observe(record, opening)
    return {"feedback": feedback, "countries": recommendations,
            "regions": [{"id": r["id"], "owner": r["owner"], "opening": deepcopy(opening[r["id"]]),
                         "closing": closing[r["id"]]} for r in record["regions"]]}


def _index(rows, key):
    by_id = {r[key]: r for r in rows}
    if len(by_id) != len(rows):
        raise BalanceError("duplicate political ledger identity")
    return by_id


def audit_plan(politics, economic):
    """Reconstruct the time-t choice independently from the fiscal auditor's economic menu."""
    opening = {i: row["opening"] for i, row in _index(politics["regions"], "id").items()}
    decisions = _index(politics["countries"], "id")
    projected, trace = prioritize(economic, opening)
    saved = decisions[economic["owner"]]["recommendation"]
    if trace != saved and canonical_line(trace) != canonical_line(saved):
        raise BalanceError("political priorities disagree with opening observations")
    return projected if politics["feedback"] else economic


def audit_political_states(record, *, previous_record=None):
    politics = record["politics"]
    if type(politics["feedback"]) is not bool or record["government"]["mode"] != "integrated":
        raise BalanceError("invalid feedback setting or fiscal menu")
    areas = _index(record["regions"], "id")
    rows = _index(politics["regions"], "id")
    if rows.keys() != areas.keys() or _index(politics["countries"], "id").keys() != {
            r["owner"] for r in areas.values()}:
        raise BalanceError("incomplete political geography")
    opening = {i: row["opening"] for i, row in rows.items()}
    if record["year"] == 1:
        initial = SimpleNamespace(regions=[SimpleNamespace(**r["opening"]) for r in areas.values()])
        if opening != initial_politics(initial):
            raise BalanceError("first year must start with neutral political memory")
    else:
        for state in opening.values():
            p = state["population"]
            groups, evidence = state["groups"], state["evidence"]
            farm = evidence["labor"]["farm"]
            industry = evidence["labor"]["mine"] + evidence["labor"]["factory"]
            members = {"farm": farm, "industry": industry, "consumer": p - farm - industry}
            if (state["membership_known"] is not True or state["unclassified"] != 0
                    or set(groups) != set(GROUPS) or p != evidence["food_need"]
                    or any(type(n) is not int or n < 0 or n != groups[k]["members"] for k, n in members.items())):
                raise BalanceError("opening interest group sizes disagree with observed labor and residents")
            for g in groups.values():
                if any(type(g[k]) is not int or not 0 <= g[k] <= 1000 for k in ("support", "discontent", "pressure")):
                    raise BalanceError("political index outside its scale")
    if previous_record is not None:
        last = previous_record.get("politics")
        if last is None or last["feedback"] != politics["feedback"] or previous_record["year"]+1 != record["year"]:
            raise BalanceError("political history changed regime or year")
        prior = _index(last["regions"], "id")
        if opening != {i: entry["closing"] for i, entry in prior.items()}:
            raise BalanceError("political memory differs from prior closing")
    expected = observe(record, opening)
    for i, r in rows.items():
        if (r["owner"] != areas[i]["owner"] or opening[i]["year"] != record["year"]-1
                or opening[i]["region"] != i or opening[i]["owner"] != r["owner"]
                or r["closing"] != expected[i]):
            raise BalanceError("political state differs from realized regional flows")


def step_political(sim, year, feedback=True):
    if type(feedback) is not bool or (sim.feedback is not None and feedback != sim.feedback):
        raise ValueError("choose one boolean feedback setting for the entire trajectory")
    # The fiscal kernel works on private copies and publishes by replacing its fields.
    # Stage its outer object too, so both sets of closing accounts commit together.
    trial = replace(sim.fiscal)
    row = _advance_fiscal(trial, year, "integrated", political_open=sim.states, feedback=feedback)
    states = {r["id"]: deepcopy(r["closing"]) for r in row["politics"]["regions"]}
    sim.fiscal, sim.states, sim.feedback = trial, states, feedback
    return row
