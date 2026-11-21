"""Optional 5.0C standing levies on privately held surplus, after border settlement."""
from .fiscal_policy import audit_collection, collect


# Denominators of the protected surplus subject to levy (food / industrial goods).
_DIVISORS = {"caretaker": (16, 5), "stewards": (24, 4), "builders": (12, 7),
             "mutualists": (12, 4), "restraint": (24, 7)}


def standing_schedule(platform):
    if not isinstance(platform, str) or platform not in _DIVISORS:
        raise ValueError("unknown levy platform")
    food, materials = _DIVISORS[platform]
    return {"platform": platform, "surplus_divisor": {"food":food, "ore":materials, "tools":materials},
            "food_population_divisor": 64}


def _schedules(regions, tariffs):
    owners = {r.owner for r in regions}
    if (not isinstance(tariffs, dict) or any(type(i) is not int for i in tariffs)
            or set(tariffs) != owners):
        raise ValueError("a standing levy platform is required for each region owner")
    return {i: standing_schedule(platform) for i, platform in tariffs.items()}


def collect_with_rates(regions, depots, decisions, mode, tariffs):
    regions = list(regions)
    return collect(regions, depots, decisions, mode, _schedules=_schedules(regions, tariffs))


def audit_collection_with_rates(regions, decisions, mode, postings, tariffs):
    regions = list(regions)
    audit_collection(regions, decisions, mode, postings, _schedules=_schedules(regions, tariffs))
