"""Audit one unchanged, one relief-first and one public-harvest path on each paired opening."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
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
from civsim.unit_economy import audit_game, step_game
from experiments import food_flow as flow
from experiments.token_upkeep_study import ORDER, SELECTION

ARCHIVE = Path(__file__).resolve().parents[1] / "examples" / "relief-priority-v1" / "study"
CHECKPOINTS = (50, 100, 200)
ARMS = ("A", "B", "C")
LEGACY = {"A":"move_on", "B":"relief_first"}
EXTRA_COLUMNS = ("marked_piece_turns", "paid_piece_turns")


def digest(value):
    return sha256(canonical_line(value)).hexdigest()


def advance(game, year, arm):
    first = year == 2
    return step_game(game, ORDER if first else None, upkeep=SELECTION if first else None,
                     relief_first=True if first and arm == "B" else None,
                     public_farm=True if first and arm == "C" else None)


def extract(record):
    rows = flow.region_rows(record)
    totals = flow.aggregate(rows)
    groups = {g["location"]:g for g in record.get("unit_upkeep", {}).get("groups", ())}
    by_owner = {r["owner"]:r for r in totals["countries"]}
    for r in [totals["world"], *totals["countries"]]:
        r.update(dict.fromkeys(EXTRA_COLUMNS, 0))
    region_col, owner_col = flow.COLUMNS.index("region"), flow.COLUMNS.index("owner")
    extended = []
    for row in rows:
        group = groups.get(row[region_col], {})
        counts = (group.get("nominal", 0), group.get("supplied", 0))
        extended.append([*row, *counts])
        for field, count in zip(EXTRA_COLUMNS, counts, strict=True):
            totals["world"][field] += count
            by_owner[row[owner_col]][field] += count
    return extended, totals


@contextmanager
def compressed(path):
    with path.open("xb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", compresslevel=4, mtime=0) as stream:
            yield stream


def run_seed(seed, directory):
    archived = json.loads((ARCHIVE / f"seed-{seed:02}.json").read_bytes())
    original = create(seed)
    first = step_game(original)
    opening = digest(snapshot62(original.economy))
    if archived["opening_sha256"] != opening:
        raise ValueError(f"archived opening differs on seed {seed}")
    result = {"seed":seed, "sample":"development" if seed < 20 else "validation",
              "opening_sha256":opening, "arms":{}}
    for arm in ARMS:
        game = deepcopy(original)
        path = {}
        prefix = f"seed-{seed:02}-{arm}"
        with compressed(directory / (prefix+"-regions.jsonl.gz")) as regions, compressed(directory / (prefix+"-totals.jsonl.gz")) as totals:
            regions.write(canonical_line({"columns":[*flow.COLUMNS, *EXTRA_COLUMNS],
                                          "schema":"food-flow/1", "seed":seed, "arm":arm}))
            for year in range(1, 201):
                record = first if year == 1 else advance(game, year, arm)
                rows, summary = extract(record)
                regions.write(canonical_line(rows))
                totals.write(canonical_line(summary))
                if year in CHECKPOINTS:
                    value = digest(record)
                    if arm in LEGACY:
                        old = archived["arms"][LEGACY[arm]]["checkpoints"][CHECKPOINTS.index(year)]
                        if old["year"] != year or old["annual_sha256"] != value:
                            raise ValueError(f"base annual record differs at {seed}/{arm}/{year}")
                    path[str(year)] = value
        result["arms"][arm] = path
    with (directory / f"seed-{seed:02}.json").open("xb") as file:
        file.write(canonical_line(result))
    return seed


def small_case(seed):
    original = create(seed)
    first = step_game(original)
    result = {"seed":seed, "year":2, "opening_sha256":digest(snapshot62(original.economy)),
              "columns":[*flow.COLUMNS, *EXTRA_COLUMNS], "arms":{}}
    for arm in ARMS:
        game = deepcopy(original)
        record = advance(game, 2, arm)
        audit_game(record, game.economy.world, first)
        rows, totals = extract(record)
        result["arms"][arm] = {"regional_rows":rows, "totals":totals, "annual_sha256":digest(record)}
        if arm == "C":
            result["arms"][arm]["crop_receipts"] = record["public_harvest"]["regions"]
        next_turn = advance(game, 3, arm)
        audit_game(next_turn, game.economy.world, record)
        if ("public_harvest" in next_turn) != (arm == "C"):
            raise ValueError("harvest rule not carried into year three")
    baseline, farm = (result["arms"][arm] for arm in ("A", "C"))
    harvest = farm["crop_receipts"]
    if not any(r["food_public"] for r in harvest):
        raise ValueError("no public ownership was exercised in this opening")
    if any(r["food_private"] + r["food_public"] != r["food_total"] for r in harvest):
        raise ValueError("harvest crop does not reconcile")
    result["year_two_C_minus_A"] = {k:v-baseline["totals"]["world"][k]
        for k,v in farm["totals"]["world"].items() if type(v) is int}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--small", action="store_true", help="run audited seed 0, years 1–3 only")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(40)))
    args = parser.parse_args()
    if args.small:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        case = small_case(0)
        with args.out.open("xb") as stream:
            stream.write(canonical_line(case))
        print("passed: common opening, three audited year-two paths and next-year continuity")
        return
    if args.workers < 1 or len(args.seeds) != len(set(args.seeds)) or not set(args.seeds) <= set(range(40)):
        parser.error("specify a positive worker count and unique study seeds between 0 and 39")
    args.out.mkdir(parents=True, exist_ok=False)
    start = perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        jobs = [pool.submit(run_seed, seed, args.out) for seed in args.seeds]
        for job in as_completed(jobs):
            print(f"completed seed {job.result()}", flush=True)
    completed = {"seeds":args.seeds, "arms":ARMS, "checkpoints":CHECKPOINTS, "workers":args.workers,
                 "python":platform.python_version(), "elapsed_seconds":round(perf_counter()-start, 2),
                 "world_years":len(args.seeds)*3*200, "engine_steps":len(args.seeds)*(1+3*199),
                 "archive_openings_verified":len(args.seeds), "archive_annual_hashes_verified":len(args.seeds)*6}
    (args.out / "execution.json").write_bytes(canonical_line(completed))


if __name__ == "__main__":
    main()
