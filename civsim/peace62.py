"""6.0B2 elective service, powered by the audited public-depot economy."""
from . import service62
from .government_audit import _check
from .supply62 import (_require, _stage62, advance62, snapshot62, start62 as start_public,
                       step62 as step_public, audit62 as audit_public)


def start62(world):
    sim = start_public(world)
    sim.roster = service62.start_service(world.regions)
    return sim


def step62(sim, year, arm="D"):
    _check(arm in ("A","B","C","D"), "unknown peacetime policy")
    if arm in ("A","B"):
        return step_public(sim, year, arm)
    return advance62(sim, year, arm, program=service62, mode="fixed" if arm=="C" else "adaptive")


def audit62(record, *, geography, previous_record=None):
    return audit_public(record, geography=geography, previous_record=previous_record,
                        program=service62 if "service" in record else None)


def fork_recruit62(sim, year, arm="D"):
    _check(arm in ("C","D"), "a recruitment fork requires a service arm")
    _require(sim, year, arm)
    mode = "adaptive" if arm=="D" else "fixed"
    return (_stage62(sim,year,arm,program=service62,mode=mode)[1],
            _stage62(sim,year,arm,program=service62,mode=mode,recruit=False,diagnostic="hold_recruitment")[1])
