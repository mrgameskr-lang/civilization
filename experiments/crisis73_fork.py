"""Locate the first paid civil response in the preregistered development search."""
from copy import deepcopy

from civsim.annual_game import create, play
from civsim.supply62 import snapshot62
from experiments.crisis73 import command_for, one_year, year_end
from experiments.research71 import digest


def pair_for(row, section, key):
    return next(p for p in row[section]["pairs"] if (p["a"], p["b"]) == key)


def trace(row, key):
    pair = pair_for(row, "crisis", key)
    dip = pair_for(row, "diplomacy", key)
    edge = set(pair["road"])
    receipts = {}
    for kind in ("trade_attempts", "migration_attempts"):
        receipts[kind] = [{"pointer": f"/diplomacy/physical/{kind}/{i}", "receipt": record}
                          for i, record in enumerate(row["diplomacy"]["physical"][kind])
                          if {record["source"], record["target"]} == edge]
    index = next(i for i, r in enumerate(row["crisis"]["pairs"]) if (r["a"], r["b"]) == key)
    economy, _ = one_year(row)
    workers = [{"region": r["id"], "private_workers": r["production"]["workers"],
                "opening_population": r["opening"]["population"], "produced": r["production"]["produced"],
                "food_unmet": r["consumption"]["food_unmet"]} for r in row["regions"] if r["id"] in edge]
    return {"year": row["year"], "record_sha256": digest(row), "pair_pointer": f"/crisis/pairs/{index}",
            "pair": pair, "local_production": workers, "attempts_on_road": receipts,
            "flows_for_pair": dip["flows"]["directions"],
            "closing_diplomacy": {k: dip["closing"][k] for k in ("trust", "relation", "tension")},
            "world": {**year_end(row), **{k: economy[k] for k in ("workers", "goods_released", "people_released",
                "unmet", "need", "quantity", "migrants", "trade_denied", "migration_denied_entry", "migration_denied_exit")}}}


def smoke():
    first_paid = None
    for seed in range(20):
        game = create(seed)
        previous = None
        quiet = None
        for year in range(1, 26):
            opening = deepcopy(game)
            command = command_for("crisis", year)
            row = play(game, command)
            if year == 1:
                if any(p["closing_level"] or p["workers"] for p in row["crisis"]["pairs"]):
                    raise ValueError("crisis or paid response without past history")
                baseline = play(create(seed), command_for("diffusion", year))
                if any(baseline[k] != row[k] for k in ("countries", "moves", "border_market")):
                    raise ValueError("quiet opening changed the economy")
                quiet = {"seed": seed, "year": year, "record_sha256": digest(row),
                         "control_sha256": digest(baseline), "pairs_considered": len(row["crisis"]["pairs"]),
                         "active_pairs": 0, "workers": 0}
            staffed = [p for p in row["crisis"]["pairs"] if p["staffed"]]
            release = [p for p in staffed if p["goods_released"] + p["people_released"]]
            if staffed and (release or first_paid is None):
                pair = (release or staffed)[0]
                key = pair["a"], pair["b"]
                opening_hash = digest(snapshot62(opening.economy))
                held_game = deepcopy(opening)
                held = play(held_game, {**(command or {"move": None}), "hold_response": True})
                active, control = trace(row, key), trace(held, key)
                if pair["workers"] != 2 or control["pair"]["workers"] or control["world"]["workers"]:
                    raise ValueError("paid desks and held response do not reconcile")
                for p in row["crisis"]["pairs"]:
                    q = pair_for(held, "crisis", (p["a"], p["b"]))
                    if p["closing_level"] != q["closing_level"]:
                        raise ValueError("holding the response changed the opening crisis judgment")
                previous_diplomacy = pair_for(previous, "diplomacy", key)
                result = {"seed": seed, "year": year, "opening_sha256": opening_hash,
                          "previous_sha256": digest(previous), "pair": list(key), "no_history_case": quiet,
                          "prior_flows": previous_diplomacy["flows"]["directions"],
                          "hold_command": {**(command or {"move": None}), "hold_response": True},
                          "normal": active, "held": control,
                          "world_difference": {k: v-control["world"][k] for k, v in active["world"].items()}}
                if release:
                    return result
                first_paid = result
            previous = row
    if first_paid:
        return first_paid
    raise ValueError("no actual paid response in seeds 0–19 through year 25; investigate before the long run")
