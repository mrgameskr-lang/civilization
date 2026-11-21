"""6.0A. Stage physical, political and bilateral closing accounts in one transition."""
from copy import deepcopy
from dataclasses import dataclass

from .collective import CollectiveWorld, _commit_collective, _trial, collective_snapshot, start_collective, step_collective
from .diplomatic_rules import initial_pairs, prepare_diplomacy


ARMS = ("A", "B", "C", "D")


@dataclass(slots=True)
class DiplomacyWorld:
    collective: CollectiveWorld
    pairs: dict
    arm: str | None = None

    @property
    def world(self):
        return self.collective.world


def start_diplomacy(world):
    return DiplomacyWorld(start_collective(world), initial_pairs(world))


def diplomacy_snapshot(sim):
    return {"collective": collective_snapshot(sim.collective), "arm": sim.arm,
            "pairs": [{"a": a, "b": b, "state": deepcopy(state)} for (a, b), state in sorted(sim.pairs.items())]}


def _diplomatic_year(sim, year, arm, intervention=None):
    if type(year) is not int or year != sim.world.year+1:
        raise ValueError("expected the next consecutive diplomatic year")
    context = prepare_diplomacy(sim.collective, year, arm, sim.pairs, intervention=intervention)
    return _trial(sim.collective, year, diplomacy=context)


def step_diplomacy(sim, year, arm):
    if arm not in ARMS or (sim.arm is not None and sim.arm != arm):
        raise ValueError("choose one diplomatic treatment for the trajectory")
    if arm == "A":
        row = step_collective(sim.collective, year, True)
    else:
        fiscal, row = _diplomatic_year(sim, year, arm)
        closing = {(r["a"], r["b"]): deepcopy(r["closing"]) for r in row["diplomacy"]["pairs"]}
        _commit_collective(sim.collective, fiscal, row)
        sim.pairs = closing
    sim.arm = arm
    return row


def fork_diplomacy_year(sim, year, intervention):
    """Change one naturally applicable decision for this year. Neither branch advances the caller."""
    if sim.arm not in ("C", "D") or not isinstance(intervention, dict) or not intervention:
        raise ValueError("a fork requires an established treaty path and one specified intervention")
    _, actual = _diplomatic_year(sim, year, sim.arm)
    _, alternative = _diplomatic_year(sim, year, sim.arm, deepcopy(intervention))
    return actual, alternative
