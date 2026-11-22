"""Follow the smoke case into the following year's decisions and zero-grant desks."""
import argparse
from copy import deepcopy
from pathlib import Path

from civsim.annual_game import create, play
from .crisis73 import command_for
from .crisis73_fork import pair_for, trace
from .research71 import digest, write_json


def access(row, key):
    pair = pair_for(row, "diplomacy", key)
    rules = ("source", "target", "trade_limit_permille", "migration_limit_permille", "migration_accept_permille",
             "aid_quantity")
    return {"agreement_active": pair["policy"]["agreement_active"],
            "directions": [{k: d[k] for k in rules} for d in pair["policy"]["directions"]]}


def follow():
    game = create(0)
    for y in range(1, 6):
        play(game, command_for("crisis", y))
    forks = {}
    for name, command in (("normal", None), ("held_year6", {"move": None, "hold_response": True})):
        copy = deepcopy(game)
        result = []
        for year in (6, 7):
            row = play(copy, command if year == 6 else None)
            pair = trace(row, (2, 3))
            empty = [trace(row, (p["a"], p["b"])) for p in row["crisis"]["pairs"] if
                     p["staffed"] and not p["goods_released"] and not p["people_released"]]
            pair["access_decisions"] = access(row, (2, 3))
            result.append({"region_pair_evidence": pair, "record_sha256": digest(row),
                           "desks_without_grants": [{"a": e["pair"]["a"], "b": e["pair"]["b"],
                                "workers": e["pair"]["workers"], "road": e["pair"]["road"],
                                "receipt_count": sum(map(len, e["attempts_on_road"].values())),
                                "pointer": e["pair_pointer"]} for e in empty]})
        forks[name] = result
    return {"seed": 0, "country_pair": [2, 3], "resume_normal_decisions_year": 7, "forks": forks}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    write_json(args.out, follow())
