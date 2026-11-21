"""Join the existing food-tax assessment to local purchase observations in the reference arm."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import gzip
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

from civsim.annual_game import create
from civsim.storage import canonical_line
from civsim.unit_economy import step_game
from experiments.food_assessment import food_assessment
from experiments.token_upkeep_study import ORDER, SELECTION


def observe(job):
    root, seed=job
    reference=json.loads((root/"study"/f"seed-{seed:02}.json").read_bytes())
    hashes={r["year"]:r["annual_sha256"] for r in reference["arms"]["move_on"]["checkpoints"]}
    game=create(seed)
    rows=[]
    for year in range(1,201):
        result=step_game(game,ORDER if year==2 else None,upkeep=SELECTION if year==2 else None)
        if year in hashes and sha256(canonical_line(result)).hexdigest()!=hashes[year]:
            raise ValueError("fiscal observations diverged from the reference trajectory")
        groups=result.get("unit_upkeep",{}).get("groups",[])
        levies={p["region"]:p for p in result["government"]["levies"]}
        for group in groups:
            i=group["location"]
            rows.append([seed,year,i,group["nominal"],*food_assessment(levies[i])])
    return rows


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("root",type=Path)
    cli.add_argument("--out",type=Path,required=True)
    cli.add_argument("--workers",type=int,default=5)
    args=cli.parse_args()
    args.out.mkdir(parents=True,exist_ok=False)
    start=perf_counter()
    bands={}
    with ProcessPoolExecutor(max_workers=args.workers) as pool, (args.out/"receipts.jsonl.gz").open("xb") as f:
        with gzip.GzipFile(filename="",fileobj=f,mode="wb",mtime=0) as stream:
            stream.write(canonical_line(["seed","year","region","marked","private_food","protected_floor",
                "opening_public_food","cap","baseline_assessed","conceded","refused","gross","handling","net","reason"]))
            for rows in pool.map(observe,[(args.root,seed) for seed in range(40)]):
                for r in rows:
                    stream.write(canonical_line(r))
                    k="1-50" if r[1]<=50 else "51-200"
                    bands.setdefault(k,Counter())[r[-1]]+=r[3]
    (args.out/"summary.json").write_bytes(canonical_line({"bands":bands,"weight":"marked purchase requests",
        "arm":"move_on","matched_annual_sha256":120,"workers":args.workers,"seconds":round(perf_counter()-start,3)}))


if __name__=="__main__":
    main()
