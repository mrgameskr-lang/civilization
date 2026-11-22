"""Fixed player inputs. Fork the same generated opening; never tune commands to a seed."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import platform
from time import perf_counter

from civsim.annual_game import create
from civsim.peace62 import snapshot62
from civsim.storage import canonical_line
from civsim.unit_economy import Move, step_game
from civsim.unit_upkeep import Upkeep

ARMS = ("move_off", "move_on", "hold_on")
ORDER = Move(5, 5, 7, 2)
SELECTION = Upkeep(5, 2)


def measure(row):
    regions = row["regions"]
    gov = row["government"]
    groups = row.get("unit_upkeep", {}).get("groups", [])
    return {
        "eaten": sum(r["consumption"]["food_eaten"] for r in regions),
        "unmet": sum(r["consumption"]["food_unmet"] for r in regions),
        "private_delivered": sum(row["domestic"]["delivered"].values()),
        "road_used": sum(e["capacity"] - e["unused"] for e in gov["roads"]),
        "relief_delivered": gov["relief"]["delivered"],
        "kit_food": sum(g["food"] for g in groups),
        "kit_tools": sum(g["tools"] for g in groups),
        "marked_turns": sum(g["nominal"] for g in groups),
        "paid_turns": sum(g["supplied"] for g in groups),
    }


def run_seed(seed, checkpoints=(50, 100, 200)):
    original = create(seed)
    first = step_game(original)
    result = {"seed":seed, "sample":"development" if seed < 20 else "validation",
              "opening_sha256":sha256(canonical_line(snapshot62(original.economy))).hexdigest(), "arms":{}}
    for arm in ARMS:
        game = deepcopy(original)
        totals = measure(first)
        path = {"checkpoints":[]}
        for year in range(2, max(checkpoints) + 1):
            row = step_game(game, ORDER if year == 2 and arm != "hold_on" else None,
                            upkeep=SELECTION if year == 2 and arm != "move_off" else None)
            if year == 2:
                path["move_receipt"] = row["unit_game"]["receipt"]
            for k, v in measure(row).items():
                totals[k] += v
            if year in checkpoints:
                stocks = row["government"]["depots"]
                path["checkpoints"].append({
                    "year":year, "cumulative":totals.copy(),
                    "closing_stock":{g:sum(d["closing"][g] for d in stocks) for g in ("food","ore","tools")},
                    "population":sum(n["closing"]["population"] for n in row["countries"]),
                    "cash":sum(n["closing"]["cash"] for n in row["countries"]),
                    "away":game.away, "marked":game.economy.game_upkeep,
                    "annual_sha256":sha256(canonical_line(row)).hexdigest(),
                })
        result["arms"][arm] = path
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    start = perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        jobs = [pool.submit(run_seed, s) for s in range(40)]
        for job in as_completed(jobs):
            record = job.result()
            with (args.out / f"seed-{record['seed']:02}.json").open("xb") as f:
                f.write(canonical_line(record))
            print(f"seed {record['seed']} complete", flush=True)
    with (args.out / "execution.json").open("xb") as f:
        f.write(canonical_line({"seeds":list(range(40)), "checkpoints":[50,100,200], "arms":ARMS,
                                "world_year_steps":40*(1+3*199), "workers":args.workers,
                                "seconds":round(perf_counter()-start,3), "python":platform.python_version()}))


if __name__ == "__main__":
    main()
