"""Domestic political salience of actual international public-food deliveries."""
from collections import Counter


def observe_aid(closing, opening, shipments):
    """Adjust bounded attitudes at exposed warehouses using last year's policy signals."""
    released, received = Counter(), Counter()
    for s in shipments:
        released[s["source"]] += s["quantity"] + s["cost_food"]
        received[s["target"]] += s["received"]
    for i in sorted(released.keys() | received.keys()):
        state = closing[i]
        people = max(1, state["population"])
        incoming = min(250, 1000*received[i]//people)
        outgoing = min(250, 1000*released[i]//people)
        state["evidence"]["foreign_aid"] = {"released_food": released[i], "received_food": received[i],
                                            "incoming_permille": incoming, "outgoing_permille": outgoing}
        for name, group in state["groups"].items():
            prior = opening[i]["groups"][name]
            signals = prior["signals"]
            net = incoming*signals["reserve"] - outgoing*max(signals[a] for a in ("relief", "reserve", "defer"))
            magnitude = min(12, abs(net)//4000) if prior["members"] and group["members"] else 0
            change = magnitude if net > 0 else -magnitude
            support = min(1000, max(0, group["support"]+change))
            group["foreign_aid_support_delta"] = support-group["support"]
            group["support"] = support
            group["discontent"] = min(1000, max(0, group["discontent"]-change))
            if change and group["demand"] != "none":
                signal = group["signals"][group["demand"]]
                group["pressure"] = min(1000, (signal+group["discontent"]+max(0,500-support))//2
                                         + 12*min(8,group["age"]-1))
