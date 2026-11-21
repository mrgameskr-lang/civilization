"""Three fixed player inputs on identical economic openings; stream all regional receipts."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
import gzip
from hashlib import sha256
import json
from pathlib import Path
import platform
from time import perf_counter

from civsim.annual_game import create
from civsim.peace62 import snapshot62
from civsim.storage import canonical_line
from civsim.unit_economy import step_game
from experiments import priority_evidence as fiscal
from experiments import priority_receipts as inventory
from experiments.token_upkeep_study import ORDER, SELECTION, measure

ARMS = ("move_off", "move_on", "relief_first")
YEARS = (50, 100, 200)
MISSING = ("missing_food_only", "missing_tools_only", "missing_both")
INV = {key:i for i,key in enumerate(inventory.COLUMNS)}
EXTRA = tuple(k for k in inventory.COLUMNS if k not in fiscal.COLUMNS)
COLUMNS = (*fiscal.COLUMNS, *EXTRA, "next_before_food", "next_before_tools")
FREG = fiscal.COLUMNS.index("region")


def write_regions(stream, record, cells, following, next_cells):
    data = []
    for raw in fiscal.region_rows(record, next_record=following):
        i = raw[FREG]
        r = cells[i]
        later = next_cells.get(i)
        data.append([*raw, *(r[INV[k]] for k in EXTRA),
                     later[INV["before_food"]] if later else None, later[INV["before_tools"]] if later else None])
    stream.write(json.dumps(data,separators=(",",":")).encode("utf-8") + b"\n")


def measurements(record, cells):
    totals = measure(record)
    for k in MISSING:
        totals[k] = sum(r[INV[k]] for r in cells.values())
    if totals["paid_turns"] + sum(totals[k] for k in MISSING) != totals["marked_turns"]:
        raise ValueError("missing item categories do not partition the marked turns")
    for k in ("levied_food","levied_tools","public_freight_food"):
        totals[k] = sum(a["totals"][k] for a in record["government"]["accounts"])
    return totals


def run_seed(seed, out, checkpoints=YEARS):
    original = create(seed)
    first = step_game(original)
    first_cells = inventory.checkout_rows(first)
    opening_hash = sha256(canonical_line(snapshot62(original.economy))).hexdigest()
    result = {"seed":seed,"sample":"development" if seed<20 else "validation", "opening_sha256":opening_hash, "arms":{}}
    for arm in ARMS:
        game = deepcopy(original)
        totals = measurements(first, first_cells)
        path = {"checkpoints":[]}
        previous, before = first, first_cells
        name = f"seed-{seed:02}-{arm}.jsonl.gz"
        with (out/name).open("xb") as raw, gzip.GzipFile(filename="",fileobj=raw,mode="wb",compresslevel=4,mtime=0) as stream:
            stream.write(canonical_line({"schema":"regional-budget/1", "seed":seed, "arm":arm,"columns":COLUMNS}))
            for year in range(2, max(checkpoints)+1):
                row = step_game(game,ORDER if year==2 else None,
                                upkeep=SELECTION if year==2 and arm!="move_off" else None,
                                relief_first=True if year==2 and arm=="relief_first" else None)
                cells = inventory.checkout_rows(row)
                write_regions(stream, previous, before, row, cells)
                for k, v in measurements(row,cells).items():
                    totals[k] += v
                if year==2:
                    path["move_receipt"] = row["unit_game"]["receipt"]
                if year in checkpoints:
                    stocks = row["government"]["depots"]
                    path["checkpoints"].append({
                        "year":year, "cumulative":totals.copy(),
                        "closing_stock":{k:sum(s["closing"][k] for s in stocks) for k in ("food","ore","tools")},
                        "population":sum(n["closing"]["population"] for n in row["countries"]),
                        "cash":sum(n["closing"]["cash"] for n in row["countries"]),
                        "away":game.away, "marked":game.economy.game_upkeep,
                        "annual_sha256":sha256(canonical_line(row)).hexdigest()})
                previous,before = row,cells
            write_regions(stream, previous, before, None, {})
        path["regional_ledger"] = name
        result["arms"][arm] = path
    (out/f"seed-{seed:02}.json").write_bytes(canonical_line(result))
    return seed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers",type=int,default=7)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--seeds",type=int,nargs="+",default=list(range(40)))
    args = parser.parse_args()
    if args.workers<1 or len(set(args.seeds))!=len(args.seeds):
        raise ValueError("expected positive worker count and unique seeds")
    args.out.mkdir(parents=True,exist_ok=False)
    start = perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_seed,s,args.out) for s in args.seeds]
        for task in as_completed(futures):
            print(f"seed {task.result()} complete",flush=True)
    (args.out/"execution.json").write_bytes(canonical_line({"seeds":args.seeds,"arms":ARMS,"checkpoints":YEARS,
        "workers":args.workers,"python":platform.python_version(),"seconds":round(perf_counter()-start,3),
        "world_year_steps":len(args.seeds)*(1+3*199),"regional_rows":len(args.seeds)*3*200*32}))


if __name__=="__main__":
    main()
