"""Paired regional reserve and relief trajectories, preserving the archived PR #25 controls."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
import json
from pathlib import Path
import platform
from time import perf_counter

from civsim.annual_game import create
from civsim.peace62 import snapshot62
from civsim.storage import canonical_line
from civsim.unit_economy import audit_game, step_game
from experiments import reserve_relief_flow as flow
from experiments.food_reserve_study import CHECKPOINTS, compressed, digest
from experiments.token_upkeep_study import ORDER, SELECTION

ARCHIVE = Path(__file__).resolve().parents[1] / "examples/food-reserve-v1/study"
ARMS = ("A", "C", "D7", "D14", "E")
POLICIES = {"D7":"7-day", "D14":"14-day", "E":"emergency"}
EXTRA = ("eligible_piece_years", "paid_sets")


def advance(game, year, arm):
    if year != 2:
        return step_game(game)
    return step_game(game, ORDER, upkeep=SELECTION, public_farm=True if arm=="C" else None,
                     reserve_policy=POLICIES.get(arm), relief_first=True if arm=="B" else None)


def extract(record):
    rows = flow.region_rows(record)
    summary = flow.aggregate(rows)
    groups = {g["location"]:g for g in record.get("unit_upkeep",{}).get("groups",[])}
    countries = {c["owner"]:c for c in summary["countries"]}
    for r in [summary["world"],*countries.values()]:
        r.update(dict.fromkeys(EXTRA, 0))
    extended = []
    region, owner = flow.COLUMNS.index("region"), flow.COLUMNS.index("owner")
    for row in rows:
        group = groups.get(row[region], {})
        n,q = group.get("nominal",0), group.get("supplied",0)
        if not 0 <= q <= n:
            raise ValueError("invalid existing inventory issue")
        extended.append([*row,n,q])
        for r in (summary["world"], countries[row[owner]]):
            r["eligible_piece_years"] += n
            r["paid_sets"] += q
    return extended, summary


def run_seed(seed, directory):
    label = f"seed-{seed:02}"
    archived = json.loads((ARCHIVE/(label+".json")).read_bytes())
    original = create(seed)
    first = step_game(original)
    opening = digest(snapshot62(original.economy))
    if opening != archived["opening_sha256"]:
        raise ValueError(f"different opening in {label}")
    result = {"seed":seed, "sample":"development" if seed<20 else "validation", "opening_sha256":opening,
              "annual_hashes":{}, "historical_hashes_checked":0}
    for arm in (*ARMS,"B"):
        game, previous = deepcopy(original), None
        hashes = {}
        if arm == "B":
            # B is a previously published ordering. Replay for compatibility only.
            for year in range(2,201):
                row = advance(game,year,arm)
                if year in CHECKPOINTS:
                    hashes[str(year)] = digest(row)
        else:
            name = label+"-"+arm
            with compressed(directory/(name+"-regions.jsonl.gz")) as local, compressed(directory/(name+"-totals.jsonl.gz")) as totals:
                local.write(canonical_line({"schema":"regional-relief/1","seed":seed,"arm":arm,
                                            "columns":[*flow.COLUMNS,*EXTRA]}))
                for year in range(1,201):
                    row = first if year==1 else advance(game,year,arm)
                    rows, stats = extract(row)
                    local.write(canonical_line(rows))
                    totals.write(canonical_line(stats))
                    if year in CHECKPOINTS:
                        audit_game(row,game.economy.world,previous)
                        hashes[str(year)] = digest(row)
                    previous = row
        if arm in archived["arms"]:
            if hashes != archived["arms"][arm]:
                raise ValueError(f"PR #25 checkpoint mismatch on {label}/{arm}")
            result["historical_hashes_checked"] += len(hashes)
        result["annual_hashes"][arm] = hashes
    with (directory/(label+".json")).open("xb") as f:
        f.write(canonical_line(result))
    return seed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(40)))
    args = parser.parse_args()
    if args.workers < 1 or len(set(args.seeds)) != len(args.seeds) or not set(args.seeds) <= set(range(40)):
        parser.error("specify positive workers and unique seeds 0 through 39")
    args.out.mkdir(parents=True, exist_ok=False)
    start = perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_seed,seed,args.out) for seed in args.seeds]
        for future in as_completed(futures):
            print(f"completed seed {future.result()}",flush=True)
    manifest = {"seeds":args.seeds,"arms":ARMS,"checkpoints":CHECKPOINTS,"compatibility_arms":["A","B","C"],
                "archived_hashes":9*len(args.seeds),"world_years_published":1000*len(args.seeds),
                "physical_steps":len(args.seeds)*(1+6*199),"regional_rows":32000*len(args.seeds),
                "workers":args.workers,"python":platform.python_version(),"seconds":round(perf_counter()-start,2)}
    (args.out/"execution.json").write_bytes(canonical_line(manifest))


if __name__ == "__main__":
    main()
