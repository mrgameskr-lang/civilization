"""Independently read published archives and verify time continuity and paired replay."""
import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from functools import partial
import gzip
from hashlib import sha256
import json
from pathlib import Path

from civsim.storage import canonical_line
from civsim.annual_game import create
from civsim.unit_economy import step_game
from experiments.food_reserve_study import ARCHIVE, ARMS, CHECKPOINTS, LEGACY, advance, digest, extract


def replay_harvest(seed, study):
    """Regenerate each C year with the full production audit and compare all published cells."""
    label = f"seed-{seed:02}"
    digests = json.loads((study/(label+".json")).read_bytes())["arms"]["C"]
    game = create(seed)
    with gzip.open(study/(label+"-C-regions.jsonl.gz"), "rb") as regions, gzip.open(study/(label+"-C-totals.jsonl.gz"), "rb") as totals:
        next(regions)
        for year in range(1, 201):
            record = step_game(game) if year == 1 else advance(game, year, "C")
            rows, summary = extract(record)
            if canonical_line(rows) != next(regions) or canonical_line(summary) != next(totals):
                raise ValueError(f"replayed harvest statistics differ at {seed}/{year}")
            if year in CHECKPOINTS and digest(record) != digests[str(year)]:
                raise ValueError(f"replayed harvest record differs at {seed}/{year}")
        if regions.read(1) or totals.read(1):
            raise ValueError("extra years after end of replay")
    return seed


def verify(study, repeat):
    published = json.loads((study/"execution.json").read_bytes())
    repeated = json.loads((repeat/"execution.json").read_bytes())
    seeds = published["seeds"]
    if sorted(seeds) != list(range(40)) or not repeated["seeds"] or not set(repeated["seeds"]) <= set(seeds):
        raise ValueError("incomplete study or empty replay sample")
    archived, compared, rows_checked, repeated_files = 0, 0, 0, {}
    payments = defaultdict(lambda:[0,0])
    for seed in seeds:
        label = f"seed-{seed:02}"
        manifest = json.loads((study/(label+".json")).read_bytes())
        old = json.loads((ARCHIVE/(label+".json")).read_bytes())
        if old["opening_sha256"] != manifest["opening_sha256"]:
            raise ValueError(f"opening mismatch: {seed}")
        for arm in ARMS:
            prefix = f"{label}-{arm}"
            if arm in LEGACY:
                for cp in old["arms"][LEGACY[arm]]["checkpoints"]:
                    if manifest["arms"][arm][str(cp["year"])] != cp["annual_sha256"]:
                        raise ValueError(f"archived digest mismatch: {prefix}")
                    archived += 1
            nominal = paid = 0
            with gzip.open(study/(prefix+"-regions.jsonl.gz"), "rb") as stream:
                columns = json.loads(next(stream))["columns"]
                ix = {k:columns.index(k) for k in ("year","region","owner","population","closing_population",
                        "public_open","public_close","private_open","private_close","marked_piece_turns","paid_piece_turns")}
                prior = None
                for year, line in enumerate(stream, 1):
                    rows = json.loads(line)
                    if len(rows) != 32 or [r[ix["region"]] for r in rows] != list(range(32)):
                        raise ValueError(f"regional coverage: {prefix}/{year}")
                    closing = []
                    for i,r in enumerate(rows):
                        if r[ix["year"]] != year:
                            raise ValueError("nonconsecutive year")
                        opening = tuple(r[ix[k]] for k in ("owner","population","private_open","public_open"))
                        if prior is not None and prior[i] != opening:
                            raise ValueError(f"discontinuous stocks or population: {prefix}/{year}/{i}")
                        closing.append(tuple(r[ix[k]] for k in ("owner","closing_population","private_close","public_close")))
                        n,q = r[ix["marked_piece_turns"]], r[ix["paid_piece_turns"]]
                        if not 0 <= q <= n:
                            raise ValueError("expense count exceeds eligible inventory")
                        nominal += n
                        paid += q
                    prior = closing
                    rows_checked += len(rows)
                    if year in CHECKPOINTS:
                        pair = payments[("development" if seed < 20 else "validation", arm, year)]
                        pair[0] += nominal
                        pair[1] += paid
                if year != 200:
                    raise ValueError(f"incomplete path: {prefix}")
        if seed in repeated["seeds"]:
            names = [label+".json", *(f"{label}-{a}-{kind}.jsonl.gz" for a in ARMS for kind in ("regions","totals"))]
            for name in names:
                a = sha256((study/name).read_bytes()).hexdigest()
                b = sha256((repeat/name).read_bytes()).hexdigest()
                if a != b:
                    raise ValueError(f"independent replay mismatch: {name}")
                repeated_files[name] = a
                compared += 1
    return {"base":"0340e0052599bdaa33fcff6daf88c011c55834b7", "openings_verified":len(seeds),
            "archived_annual_hashes":archived, "regional_rows_checked":rows_checked,
            "repeat_seeds":repeated["seeds"], "repeated_files_compared":compared, "identical_sha256":repeated_files,
            "cumulative_existing_checkout":[{"sample":s,"arm":a,"year":y,"eligible_piece_years":n,
                "paid_sets":q,"paid_share":q/n if n else None} for (s,a,y),(n,q) in sorted(payments.items())]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("study","out"):
        parser.add_argument("--"+option,type=Path,required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--repeat", type=Path)
    mode.add_argument("--replay-harvest", action="store_true")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if args.replay_harvest:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            seeds = list(pool.map(partial(replay_harvest, study=args.study), range(40)))
        result = {"policy":"C", "seeds":seeds, "world_years_replayed":200*len(seeds),
                  "regional_rows_compared":200*32*len(seeds), "annual_hashes_compared":3*len(seeds)}
    else:
        result = verify(args.study, args.repeat)
    with args.out.open("xb") as report:
        report.write(canonical_line(result))
    print(f"Verification complete. Results saved to {args.out}")


if __name__ == "__main__":
    main()
