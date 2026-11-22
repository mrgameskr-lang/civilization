"""Same-state road closure at a single harvest, retaining foreign trade in every arm."""
import argparse

from civsim.model import generate_world
from civsim.regional_engine import RegionalPolicy, step_regional
from civsim.regions import regionalize


def compare(seed):
    result = []
    for label in ("unlimited", "limited", "closed"):
        w = regionalize(generate_world(seed))
        closed = tuple(sorted((r.a, r.b) for r in w.roads)) if label == "closed" else ()
        mode = "unlimited" if label == "unlimited" else "limited"
        annual = step_regional(w, 1, RegionalPolicy(mode, closed_roads=closed))
        ledger = annual["domestic"]
        basis = [(r["id"], r["owner"], r["population"], r["opening"]) for r in ledger["nodes"]]
        if result and basis != same_opening:
            raise ValueError("production or international settlement differs before domestic dispatch")
        same_opening = basis
        result.append({"mode": label, "food_shipped": ledger["delivered"]["food"],
                       "domestic_cost_food": ledger["cost_food"], "food_output": sum(
                           r["production"]["produced"]["food"] for r in annual["regions"]),
                       "unmet": sum(r["consumption"]["food_unmet"] for r in annual["regions"]),
                       "regions_short": sum(r["consumption"]["food_unmet"] > 0 for r in annual["regions"])})
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    for row in compare(args.seed):
        print(" ".join(f"{key}={value}" for key, value in row.items()))
