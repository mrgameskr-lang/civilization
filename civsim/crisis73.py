"""Bilateral civilian border appeals funded from the two local labor accounts."""
from collections import Counter

from .audit import BalanceError
from .civic_diplomacy63 import _signal


VERSION = "border-appeals/1"
CASES = 4
TRANSITIONS = {(0, 1): "start", (1, 2): "escalate", (2, 1): "ease", (1, 0): "resolve"}


def _observed(old):
    return [{"source": f["source"], "target": f["target"], "breach": f["agreement_breach"],
             "trade_food": f["goods"]["food"], "trade_ore": f["goods"]["ore"], "trade_tools": f["goods"]["tools"],
             "trade_denied": f["trade_denied"], "migrants": f["migrants"],
             "exit_denied": f["migration_denied_exit"], "entry_denied": f["migration_denied_entry"],
             "closing_tension": old["tension"], "closing_trust": old["trust"]} for f in old["last"]]


def closing(ledger):
    return [{"a": p["a"], "b": p["b"], "level": p["closing_level"]} for p in ledger["pairs"]]


def staff(ledger):
    workers = Counter()
    for pair in ledger["pairs"]:
        if pair["staffed"]:
            workers.update(pair["road"])
    return workers


def plan(ctx, local, borders, free, memory, hold):
    """Choose one joint desk per country after domestic labor obligations and before production."""
    owner = {r.id: r.owner for r in local}
    countries = {c["id"]: c for c in ctx["countries"]}
    roads = {}
    for e in sorted(borders, key=lambda road: (road.distance, -road.capacity, road.a, road.b)):
        if e.capacity > 0:
            endpoints = sorted((e.a, e.b), key=owner.__getitem__)
            key = tuple(owner[i] for i in endpoints)
            roads.setdefault(key, endpoints)
    prior = {(p["a"], p["b"]): p["level"] for p in memory or ()}
    if memory is not None and (list(prior) != sorted(roads) or len(memory) != len(prior)
                               or any(type(level) is not int or level not in (0, 1, 2) for level in prior.values())):
        raise BalanceError("invalid opening border crisis register")
    ledger = {"version": VERSION, "first_turn": memory is None, "hold_response": hold, "pairs": []}
    ranked = {}
    for pair in ctx["pairs"]:
        key = a, b = pair["a"], pair["b"]
        if key not in roads:
            continue
        observed = _observed(pair["opening"])
        signal = _signal(observed)
        opening = prior.get(key, 0)
        substantial = signal["breach"] or signal["substantial"] or (signal["actual_denial"] and signal["tension"] >= 125)
        level = opening
        if substantial:
            level = min(2, opening + 1)
        elif not signal["actual_denial"]:
            level = max(0, opening - 1)
        goods = sum(f["trade_denied"] for f in observed)
        people = sum(f["exit_denied"] + f["entry_denied"] for f in observed)
        road = roads[key]
        result = {"a": a, "b": b, "road": road, "evidence_year": pair["opening"]["year"],
                  "opening_level": opening, "closing_level": level,
                  "transition": TRANSITIONS.get((opening, level), "none"), "trade_denied": goods,
                  "people_denied": people, "breaches": sum(f["breach"] for f in observed),
                  "tension": signal["tension"], "trust": signal["trust"], "substantial": substantial,
                  "choices": [], "goods_released": 0, "people_released": 0}
        for i, country in enumerate(key):
            outbound, inbound = observed[i], observed[1-i]
            # Prioritize own residents' refused departures and blocked imports, while both sides
            # also value reopening a shared crossing. Scores rank cases within a country only.
            score = (goods + people + inbound["trade_denied"] + outbound["entry_denied"] +
                     outbound["exit_denied"] + 4 * inbound["breach"])
            shortage = countries[country]["shortage_permille"]
            eligible = bool(level and score and free[road[i]] >= 1 and shortage < 250)
            choice = {"country": country, "available_workers": free[road[i]], "shortage_permille": shortage,
                      "score": score, "eligible": eligible}
            result["choices"].append(choice)
            if eligible:
                rank = (-level, -score, key[1-i])
                if country not in ranked or rank < ranked[country]:
                    ranked[country] = rank
        ledger["pairs"].append(result)
    for pair in ledger["pairs"]:
        for choice, other in zip(pair["choices"], (pair["b"], pair["a"]), strict=True):
            country = choice["country"]
            choice["selected"] = country in ranked and ranked[country][2] == other
        mutual = all(c["selected"] for c in pair["choices"])
        if not pair["closing_level"]:
            response = "inactive"
        elif not pair["trade_denied"] + pair["people_denied"]:
            response = "no_new_harm"
        elif not mutual:
            response = "not_mutual"
        else:
            response = "hold" if hold else "staffed"
        pair.update(response=response, staffed=response == "staffed", workers=2 * int(response == "staffed"))
    return ledger


class Appeals:
    """Wrap the existing border executor; grants consume the same physical invoice/receipt."""
    def __init__(self, flows, ledger):
        self.flows = flows
        self.desks = {tuple(sorted(p["road"])): p for p in ledger["pairs"] if p["staffed"]}

    def __getattr__(self, name):
        return getattr(self.flows, name)

    def _grant(self, source, target, feasible, passed, field, receipt):
        desk = self.desks.get(tuple(sorted((source, target))))
        if desk is None:
            return 0
        remaining = CASES - desk["goods_released"] - desk["people_released"]
        extra = min(feasible - passed, remaining)
        desk[field] += extra
        receipt.update(ordinary_passed=passed, appeal_remaining_before=remaining, appeal_granted=extra)
        return extra

    def trade(self, seller, buyer, good, road, feasible):
        passed = self.flows.trade(seller, buyer, good, road, feasible)
        if feasible <= 0:
            return passed
        receipt = self.flows.trade_attempts[-1]
        extra = self._grant(seller, buyer, feasible, passed, "goods_released", receipt)
        self.flows.direction_used[seller, buyer] += extra
        self.flows.private_used[road.a, road.b] += extra
        receipt["quantity"] += extra
        receipt["denied"] -= extra
        return passed + extra

    def migrate(self, source, target, feasible, donor, host):
        passed = self.flows.migrate(source, target, feasible, donor, host)
        src, dst = self.flows.countries(source, target)
        if src == dst or not feasible:
            return passed
        receipt = self.flows.migration_attempts[-1]
        extra = self._grant(source, target, feasible, passed, "people_released", receipt)
        entry = min(extra, receipt["denied_entry"])
        receipt["denied_entry"] -= entry
        receipt["denied_exit"] -= extra - entry
        receipt["people"] += extra
        self.flows.exits[source, dst] += extra
        self.flows.entries[src, target] += extra
        return passed + extra
