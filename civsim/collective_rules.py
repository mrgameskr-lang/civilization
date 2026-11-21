"""Lagged civic choices by representative groups; every number is an integer."""
from .political_rules import GROUPS

ACTIVE = ("petition", "protest", "strike", "refusal")


def empty_memory():
    return {group: {"action": "none", "demand": "none", "duration": 0, "campaign": 0,
                    "rest": 0, "answered": False, "opening_discontent": 0} for group in GROUPS}


def _choice(name, g, members, workers, hunger, motive, prior):
    continuing = prior["action"] in ACTIVE
    if continuing and prior["answered"] and (g["discontent"] <= prior["opening_discontent"]
                                              or g["demand"] != prior["demand"]):
        return "accept", "delivered_and_reviewed"
    if prior["rest"] or prior["campaign"] >= 6:
        return "none", "recovery_interval"
    if (members < 8 or g["demand"] == "none" or g["age"] < 2 or g["discontent"] < 35
            or g["support"] > 530 or motive < 65):
        return "none", "insufficient_joint_claim"
    if not continuing or g["demand"] != prior["demand"]:
        return "petition", "new_persistent_claim"
    if prior["action"] == "petition" or motive < 135:
        if motive >= 95 and g["discontent"] >= 70:
            return "protest", "continuing_unsettled_claim"
        return "petition", "renewed_petition"
    if g["levy_value"] > 0 and g["fiscal_burden"] >= max(8, g["discontent"] // 8):
        return "refusal", "observed_tax_incidence"
    if name != "consumer" and workers and hunger < 450 and motive >= 150:
        return "strike", "limited_affordable_stoppage"
    return "protest", "continued_public_claim"


def mobilize_region(region, population, observation, memory, suppress=None):
    """Read opening residents and the previous political journal, never current-year flows."""
    previous_population = observation["population"]
    groups = observation["groups"]
    producers = groups["farm"]["members"] + groups["industry"]["members"]
    hunger = observation["evidence"].get("shortage_permille", 0)
    rows = {}
    for name in GROUPS:
        g, prior = groups[name], memory[name]
        members = g["members"] * min(population, previous_population) // max(1, previous_population)
        workers = (min(members, (population // 2) * g["members"] // max(1, producers))
                   if name != "consumer" else 0)
        motive = (2*g["discontent"] + g["pressure"] + max(0, 500-g["support"])) // 4
        action, reason = _choice(name, g, members, workers, hunger, motive, prior)
        participants = 0
        if action in ACTIVE:
            participants = members * min(300, max(40, motive)) // 1000
            if participants == 0:
                action, reason = "none", "less_than_one_participant"
        if suppress == name:
            if action not in ACTIVE:
                raise ValueError("intervention requires a naturally active group")
            action, reason, participants = "none", "suppressed_for_one_year", 0
        withheld = 0
        if action == "strike":
            withheld = min(workers, (participants+2)//3)
        elif action == "protest" and workers:
            withheld = min(workers, (participants+15)//16)
        duration = campaign = 0
        if action in ACTIVE:
            duration = prior["duration"]+1 if (action, g["demand"]) == (prior["action"], prior["demand"]) else 1
            campaign = prior["campaign"]+1 if prior["action"] in ACTIVE and g["demand"] == prior["demand"] else 1
        rows[name] = {"prior": prior.copy(), "action": action, "reason": reason, "duration": duration,
                      "campaign": campaign, "participants": participants, "withheld_workers": withheld,
                      "members": members, "worker_bound": workers, "motive": motive, "shortage_permille": hunger,
                      **{k: g[k] for k in ("demand", "age", "pressure", "support", "discontent", "fiscal_burden",
                                           "levy_value")}}
    return {"id": region, "owner": observation["owner"], "groups": rows}
