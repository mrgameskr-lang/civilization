"""5.0C. Aggregate elections change the authorizer of the existing fiscal ledger."""
from copy import deepcopy
from dataclasses import dataclass, replace
from types import SimpleNamespace

from .audit import BalanceError
from .competition_rules import FACTIONS, SEATS, TERM, cabinet_plan, elect, initial_cabinets
from .government import _advance_fiscal
from .political_rules import prioritize
from .politics import PoliticalWorld, political_snapshot, start_political


ARMS = ("A", "B", "C", "D")
TAX_POLICIES = ("fixed", "platform")


def _options(arm, tax_policy):
    if arm not in ARMS or tax_policy not in TAX_POLICIES or (arm in ("A", "B") and tax_policy != "fixed"):
        raise ValueError("expected A/B with fixed taxes, or C/D with fixed or platform taxes")


@dataclass(slots=True)
class CompetitionWorld:
    political: PoliticalWorld
    cabinets: dict
    arm: str | None = None
    tax_policy: str | None = None

    @property
    def world(self):
        return self.political.world


def start_competition(world):
    return CompetitionWorld(start_political(world), initial_cabinets(world))


def competition_snapshot(sim):
    return {"political": political_snapshot(sim.political),
            "cabinets": [deepcopy(sim.cabinets[i]) for i in sorted(sim.cabinets)],
            "arm": sim.arm, "tax_policy": sim.tax_policy}


def _prepare(year, states, cabinets, arm, tax_policy, keep=None):
    _options(arm, tax_policy)
    if arm in ("C", "D"):
        closing, ballots = elect(year, states, cabinets)
    else:
        closing, ballots = cabinets, dict.fromkeys(cabinets)
    if keep is not None and (type(keep) is not int or keep not in cabinets
                             or not ballots[keep] or not ballots[keep]["turnover"]):
        raise ValueError("a retention intervention requires a genuine elected-party turnover")
    countries = []
    for owner, previous in sorted(cabinets.items()):
        governing = previous["incumbent"] if owner == keep else closing[owner]["incumbent"]
        countries.append({"id": owner, "opening": deepcopy(previous), "closing": deepcopy(closing[owner]),
                          "election": ballots[owner], "governing_faction": governing,
                          "tariff": governing if tax_policy == "platform" else "caretaker",
                          "outgoing_choice": None})
    return {"arm": arm, "tax_policy": tax_policy, "countries": countries, "kept_incumbent": keep}


def _authorization(base, states, country, arm):
    if arm in ("A", "B"):
        plan, trace = prioritize(base, states)
        return plan, trace, None
    ballot = country["election"]
    governing = (country["closing"] if country["governing_faction"] == country["closing"]["incumbent"]
                 else country["opening"])
    plan, trace = cabinet_plan(base, states, governing, arm == "D")
    outgoing = None
    if ballot["installation"] or ballot["turnover"]:
        if country["opening"]["incumbent"] == governing["incumbent"]:
            outgoing = trace["political_choice"]
        else:
            _, alternative = cabinet_plan(base, states, country["opening"], arm == "D")
            outgoing = alternative["political_choice"]
    return plan, trace, outgoing


def authorize_plans(plans, states, context):
    approved, traces = {}, []
    for country in context["countries"]:
        owner = country["id"]
        approved[owner], trace, country["outgoing_choice"] = _authorization(
            plans[owner], states, country, context["arm"])
        traces.append({"id": owner, "recommendation": trace})
    return approved, traces


def audit_competition_plan(record, economic):
    owner = economic["owner"]
    context, politics = record["competition"], record["politics"]
    states = {r["id"]: r["opening"] for r in politics["regions"]}
    country = {c["id"]: c for c in context["countries"]}[owner]
    plan, trace, outgoing = _authorization(economic, states, country, context["arm"])
    recommendation = {c["id"]: c["recommendation"] for c in politics["countries"]}[owner]
    if trace != recommendation or outgoing != country["outgoing_choice"]:
        raise BalanceError("cabinet ranking or outgoing alternative differs from the fiscal menu")
    return plan


def _audit_inheritance(record, previous):
    for entries, prior, key in (
        (record["countries"], previous["countries"], "id"),
        (record["regions"], previous["regions"], "id"),
        (record["government"]["depots"], previous["government"]["depots"], "region"),
    ):
        if {r[key]: r["opening"] for r in entries} != {r[key]: r["closing"] for r in prior}:
            raise BalanceError("economic assets or population failed to carry across fiscal years")
    roads = {(e["a"], e["b"]): (e["opening_units"], e["capacity"]) for e in record["government"]["roads"]}
    prior_roads = {(e["a"], e["b"]): (e["closing_units"], e["next_capacity"]) for e in previous["government"]["roads"]}
    if roads != prior_roads:
        raise BalanceError("funded road stock failed to carry across fiscal years")


def _audit_ballot_totals(ballot, states):
    groups = ballot["ballots"]
    totals = {party: sum(g["vote_points"][party] for g in groups) for party in FACTIONS}
    participating = sum(totals.values())
    unclassified = sum(s["unclassified"] for s in states.values() if s["owner"] == ballot["owner"])
    possible = (sum(g["members"] for g in groups) + unclassified) * 1000
    if (any(sum(g["vote_points"].values()) != g["participation_points"]
            or not 0 <= g["participation_points"] <= 1000*g["members"] for g in groups)
            or totals != ballot["vote_points"] or participating != ballot["participation_points"]
            or possible != ballot["eligible_points"] or possible-participating != ballot["abstention_points"]
            or sum(ballot["seats"].values()) != (SEATS if participating else 0)):
        raise BalanceError("representative points or assembly seats do not reconcile")


def audit_cabinets(record, previous_record=None):
    ctx = record["competition"]
    if record["politics"]["feedback"] is not True:
        raise BalanceError("competition arms require an active political policy")
    countries = {c["id"]: c for c in ctx["countries"]}
    if len(countries) != len(ctx["countries"]) or set(countries) != {n["id"] for n in record["countries"]}:
        raise BalanceError("missing or duplicate national cabinet")
    prior = {i: c["opening"] for i, c in countries.items()}
    if record["year"] == 1:
        world = SimpleNamespace(nations=[SimpleNamespace(id=i) for i in countries])
        if prior != initial_cabinets(world):
            raise BalanceError("unexpected founding government")
    if previous_record is not None:
        _audit_inheritance(record, previous_record)
        prev = previous_record["competition"]
        if (ctx["arm"], ctx["tax_policy"]) != (prev["arm"], prev["tax_policy"]) or prev["kept_incumbent"] is not None:
            raise BalanceError("competition regime changed inside a trajectory")
        if prior != {c["id"]: c["closing"] for c in prev["countries"]}:
            raise BalanceError("government history does not match last year")
    states = {r["id"]: r["opening"] for r in record["politics"]["regions"]}
    expected = _prepare(record["year"], states, prior, ctx["arm"], ctx["tax_policy"], ctx["kept_incumbent"])
    past_elections = max(0, (record["year"] - 2) // TERM) if ctx["arm"] in ("C", "D") else 0
    last_election = 1 + TERM * past_elections if past_elections else 0
    for c in expected["countries"]:
        actual = countries[c["id"]]
        if (actual["opening"]["elections"] != past_elections
                or actual["opening"]["last_election"] != last_election):
            raise BalanceError("cabinet history differs from the election calendar")
        if actual["election"] is not None:
            _audit_ballot_totals(actual["election"], states)
        if any(c[k] != actual[k] for k in ("opening", "closing", "election", "governing_faction", "tariff")):
            raise BalanceError("election, political authority or tax schedule differs from opening data")


def _annual_trial(sim, year, arm, tax_policy, keep=None):
    if type(year) is not int or year != sim.world.year+1:
        raise ValueError("expected the next consecutive year")
    politics = sim.political
    context = _prepare(year, politics.states, sim.cabinets, arm, tax_policy, keep)
    # Government transitions replace fiscal state fields only after their own audit.
    # Staging this outer object leaves the caller's economic and political history intact.
    fiscal = replace(politics.fiscal)
    row = _advance_fiscal(fiscal, year, "integrated", political_open=politics.states,
                          feedback=True, competition=context)
    return fiscal, row


def step_competition(sim, year, arm, tax_policy="fixed"):
    if sim.arm is not None and (sim.arm, sim.tax_policy) != (arm, tax_policy):
        raise ValueError("choose one treatment and tax policy per trajectory")
    fiscal, row = _annual_trial(sim, year, arm, tax_policy)
    states = {r["id"]: deepcopy(r["closing"]) for r in row["politics"]["regions"]}
    cabinets = {c["id"]: deepcopy(c["closing"]) for c in row["competition"]["countries"]}
    sim.political = PoliticalWorld(fiscal, states, True)
    sim.cabinets, sim.arm, sim.tax_policy = cabinets, arm, tax_policy
    return row


def fork_election_year(sim, year, owner, arm="C", tax_policy="fixed"):
    """One-year measured interventions. The political world is never advanced."""
    if (sim.arm, sim.tax_policy) != (arm, tax_policy):
        raise ValueError("the election fork must share its source treatment")
    _, elected = _annual_trial(sim, year, arm, tax_policy)
    _, retained = _annual_trial(sim, year, arm, tax_policy, keep=owner)
    return elected, retained


def fork_tax_year(sim, year, arm="C"):
    """Vary only the standing levy schedule on one shared opening and one election."""
    if arm not in ("C", "D") or sim.arm != arm:
        raise ValueError("a tax comparison requires an established competitive path")
    return tuple(_annual_trial(sim, year, arm, policy)[1] for policy in TAX_POLICIES)
