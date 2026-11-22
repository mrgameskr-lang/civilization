"""Paired fixed player inputs on existing annual worlds, with cumulative checkpoint hashes."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import platform
from time import perf_counter

from civsim.model import generate_world
from civsim.peace62 import snapshot62, start62
from civsim.regions import regionalize
from civsim.storage import canonical_line
from civsim.unit_economy import AnnualUnitGame, Move, step_game

from experiments.unit_economy_metrics import civil_totals

ORDER = Move(5, 5, 4, 1)


def digest(obj):
    return sha256(canonical_line(obj)).hexdigest()


def measure(record):
    w = civil_totals(record)["world"]
    return {"eaten": w["food_eaten"], "domestic_goods": sum(w["received"].values()),
            "food_unmet": sum(r["consumption"]["food_unmet"] for r in record["regions"]),
            "population": sum(r["closing"]["population"] for r in record["countries"])}


def run_seed(seed, years=200, checkpoints=(50,100,200)):
    original = AnnualUnitGame(start62(regionalize(generate_world(seed))))
    first = step_game(original)
    initial = digest(snapshot62(original.economy))
    paths = []
    for arm in ("move","hold"):
        game = deepcopy(original)
        chain = sha256(canonical_line(first))
        totals = {k: v for k,v in measure(first).items() if k != "population"}
        results = []
        receipt = None
        for year in range(2,years+1):
            row = step_game(game, ORDER if arm=="move" and year==2 else None)
            if year==2:
                receipt = row["unit_game"]["receipt"]
            chain.update(canonical_line(row))
            now = measure(row)
            for k in totals:
                totals[k] += now[k]
            if year in checkpoints:
                results.append({"year":year, "population":now["population"], "cumulative":totals.copy(),
                                "closing_away":game.away, "annual_chain_sha256":chain.hexdigest()})
        paths.append({"arm":arm,"receipt":receipt,"checkpoints":results})
    return {"seed":seed,"sample":"development" if seed<20 else "validation",
            "opening_year2_sha256":initial,"paths":paths}


def run_study(out, workers):
    if workers < 1:
        raise ValueError("positive worker count required")
    out.mkdir(parents=True,exist_ok=False)
    start=perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_seed,seed): seed for seed in range(40)}
        for job in as_completed(futures):
            result = job.result()
            seed = result["seed"]
            (out/f"seed-{seed:02}.json").write_bytes(canonical_line(result))
            print(f"seed {seed} complete",flush=True)
    with (out/"execution.json").open("x",encoding="utf8") as stream:
        json.dump({"seeds":list(range(40)), "checkpoints":[50,100,200],"arms":["move","hold"],
                   "order_year":2,"workers":workers,"python":platform.python_version(),
                   "unique_year_steps":40*(1+2*199),"observed_arm_years":16000,
                   "wall_seconds":perf_counter()-start},stream,indent=2)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--workers",type=int,default=4)
    args=parser.parse_args()
    run_study(args.out,args.workers)
