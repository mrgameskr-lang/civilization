"""Read both raw scales independently, check custody/continuity, and compare isolated runs."""
import argparse
from collections import Counter
import gzip
from hashlib import sha256
import json
from pathlib import Path

from civsim.storage import canonical_line
from experiments.reserve_relief_study import ARCHIVE, ARMS, CHECKPOINTS


def verify(study, repeat):
    execution = json.loads((study/"execution.json").read_bytes())
    seeds = execution["seeds"]
    rerun = json.loads((repeat/"execution.json").read_bytes())["seeds"]
    if sorted(seeds)!=list(range(40)) or not rerun or not set(rerun)<=set(seeds):
        raise ValueError("incomplete opening sample")
    checks, region_years = 0, 0
    repeated = {}
    expenses = {}
    coexistence = {}
    for seed in seeds:
        label = f"seed-{seed:02}"
        manifest = json.loads((study/(label+".json")).read_bytes())
        old = json.loads((ARCHIVE/(label+".json")).read_bytes())
        if old["opening_sha256"]!=manifest["opening_sha256"]:
            raise ValueError("opening hash differs")
        for arm in ("A","B","C"):
            if manifest["annual_hashes"][arm] != old["arms"][arm] or set(old["arms"][arm]) != {str(y) for y in CHECKPOINTS}:
                raise ValueError(f"archived checks differ at {seed}/{arm}")
            checks += len(CHECKPOINTS)
        names = [label+".json"]
        for arm in ARMS:
            prefix = label+"-"+arm
            rname,tname = prefix+"-regions.jsonl.gz",prefix+"-totals.jsonl.gz"
            names.extend((rname,tname))
            with gzip.open(study/rname,"rb") as local, gzip.open(study/tname,"rb") as totals:
                cols = json.loads(next(local))["columns"]
                ix = {k:i for i,k in enumerate(cols)}
                prior = None
                counted = Counter()
                for year,(line,summary) in enumerate(zip(local,totals,strict=True),1):
                    rows = json.loads(line)
                    s = json.loads(summary)
                    if [r[ix["region"]] for r in rows] != list(range(32)) or s["year"]!=year:
                        raise ValueError("regional coverage differs")
                    close = []
                    by_owner = [Counter() for _ in range(8)]
                    for i,r in enumerate(rows):
                        def get(k):
                            return r[ix[k]]
                        if get("year") != year:
                            raise ValueError("out-of-order region")
                        for side,keys in (("open",("owner","population","private_open","public_open")),
                                          ("close",("owner","closing_population","private_close","public_close"))):
                            v = tuple(get(k) for k in keys)
                            if side=="open" and prior is not None and prior[i]!=v:
                                raise ValueError(f"discontinuous boundary {seed}/{arm}/{year}/{i}")
                            if side=="close":
                                close.append(v)
                        if (get("food_need") != get("food_eaten")+get("food_unmet") or
                                get("eligible_piece_years") < get("paid_sets") or get("paid_sets") < 0):
                            raise ValueError("meals or resource issues differ")
                        band = (year-1)//50
                        bucket = coexistence.setdefault(f"{manifest['sample']}/{arm}/{band*50+1}-{band*50+50}",Counter())
                        bucket["region_years"] += 1
                        gap, stock = get("food_unmet"), get("public_close")
                        if gap:
                            bucket["shortage_region_years"] += 1
                            if stock:
                                bucket["shortage_with_closing_local_reserve"] += 1
                                bucket["unmet_in_those_regions"] += gap
                                bucket["closing_food_in_those_regions"] += stock
                                if get("pre_extra_public"):
                                    bucket["also_stocked_before_extra"] += 1
                        fiscal = by_owner[get("owner")]
                        for k in ("food_need","food_eaten","food_unmet","deaths","public_close","closing_population",
                                  "emergency_received_food","ordinary_received_food","eligible_piece_years","paid_sets"):
                            fiscal[k] += get(k)
                    prior = close
                    country = {r["owner"]:r for r in s["countries"]}
                    if set(country)!=set(range(8)):
                        raise ValueError("country coverage differs")
                    world = sum(by_owner,Counter())
                    for receipt,account in [(t,country[i]) for i,t in enumerate(by_owner)]+[(world,s["world"])]:
                        if any(receipt[k]!=account[k] for k in by_owner[0]):
                            raise ValueError("regional and national totals differ")
                    counted.update({k:s["world"][k] for k in ("eligible_piece_years","paid_sets")})
                    if year in CHECKPOINTS:
                        key = f"{manifest['sample']}/{arm}/{year}"
                        expenses.setdefault(key,Counter()).update(counted)
                    region_years += len(rows)
                if year!=200:
                    raise ValueError("incomplete annual trajectory")
        if seed in rerun:
            for name in names:
                original = sha256((study/name).read_bytes()).hexdigest()
                if sha256((repeat/name).read_bytes()).hexdigest()!=original:
                    raise ValueError(f"independent repeat differs: {name}")
                repeated[name] = original
    return {"pr25_annual_hashes":checks,"opening_hashes":len(seeds),"regional_rows_checked":region_years,
            "repeat_seeds":rerun,"byte_identical_files":repeated,"cumulative_existing_issue":expenses,
            "unmet_and_closing_public_food":coexistence}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for opt in ("study","repeat","out"):
        p.add_argument("--"+opt,type=Path,required=True)
    a=p.parse_args()
    result=verify(a.study,a.repeat)
    with a.out.open("xb") as f:
        f.write(canonical_line(result))
    print(f"Verified {result['regional_rows_checked']} regional rows and {result['pr25_annual_hashes']} archived annual hashes")


if __name__=="__main__":
    main()
