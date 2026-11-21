"""Compare two preference calculations on the same frozen 5.0B economic trajectories."""
import argparse
import csv
import hashlib
import json
import os
from concurrent.futures import ProcessPoolExecutor
from itertools import combinations
from pathlib import Path
from tempfile import TemporaryDirectory

from civsim.competition_rules import differentiated_observe
from civsim.fiscal_policy import ACTIONS
from civsim.model import generate_world
from civsim.political_rules import GROUPS, initial_politics
from civsim.politics import start_political, step_political
from civsim.regions import regionalize
from civsim.storage import canonical_line


def _blank():
    return {"groups":{k:{"member_years":0,"changed_member_years":0,
                         **{model:dict.fromkeys((*ACTIONS,"none"),0) for model in ("legacy","revised")}} for k in GROUPS},
            "pairs":dict.fromkeys(("all","legacy_different","revised_different","legacy_expressed",
                                  "revised_expressed","legacy_expressed_different","revised_expressed_different"),0),
            "physical":dict.fromkeys(("region_years","industry_input_short","industry_short_without_congestion"),0)}


def _record(stats, old, new):
    e = old["evidence"]
    physical = stats["physical"]
    physical["region_years"] += 1
    shortage = e["industrial_shortage_permille"]>0
    physical["industry_input_short"] += int(shortage)
    physical["industry_short_without_congestion"] += int(shortage and e["road_congestion_permille"]==0)
    local = []
    for k in GROUPS:
        a,b = old["groups"][k],new["groups"][k]
        n = a["members"]
        if n!=b["members"]:
            raise ValueError("identical physical labor must yield identical group membership")
        g = stats["groups"][k]
        g["member_years"] += n
        g["changed_member_years"] += n*int(a["demand"]!=b["demand"])
        g["legacy"][a["demand"]] += n
        g["revised"][b["demand"]] += n
        if n:
            local.append((a["demand"],b["demand"]))
    pairs = stats["pairs"]
    for left,right in combinations(local,2):
        pairs["all"] += 1
        for i,model in enumerate(("legacy","revised")):
            active = "none" not in (left[i],right[i])
            different = left[i]!=right[i]
            pairs[model+"_different"] += int(different)
            pairs[model+"_expressed"] += int(active)
            pairs[model+"_expressed_different"] += int(active and different)


def _trajectory(job):
    seed,years = job
    world = regionalize(generate_world(seed))
    simulation, revised = start_political(world),initial_politics(world)
    digest, stats = hashlib.sha256(),_blank()
    for year in range(1,years+1):
        record = step_political(simulation,year,True)
        digest.update(canonical_line(record))
        revised = differentiated_observe(record,revised)
        for r in record["politics"]["regions"]:
            _record(stats,r["closing"],revised[r["id"]])
    return {"seed":seed,"legacy_years_sha256":digest.hexdigest(),**stats}


def _add(target, additions):
    for k in target:
        if isinstance(target[k],dict):
            _add(target[k],additions[k])
        else:
            target[k] += additions[k]


def run(out, *, seeds=20, years=200, workers=4):
    if not (1<=seeds<=20 and years>=1 and workers>=1):
        raise ValueError("use the development seeds 0–19 and positive horizon/workers")
    out = Path(out)
    if os.path.lexists(out):
        raise FileExistsError(out)
    jobs = [(seed,years) for seed in range(seeds)]
    if workers==1:
        results = list(map(_trajectory,jobs))
    else:
        with ProcessPoolExecutor(max_workers=min(workers,seeds)) as pool:
            results = list(pool.map(_trajectory,jobs))
    ref = Path(__file__).resolve().parents[1]/"examples/phase5b/study/dev/runs.csv"
    with ref.open(encoding="utf-8",newline="") as stream:
        archived = {int(r["seed"]):r["years_sha256"] for r in csv.DictReader(stream)
                    if r["arm"]=="on" and int(r["year"])==years}
    totals = _blank()
    matched = 0
    for r in results:
        if archived:
            if archived[r["seed"]]!=r["legacy_years_sha256"]:
                raise ValueError("legacy trajectory differs from archived development study")
            matched += 1
        _add(totals,r)
    document = {"source":"5.0B feedback on","seeds":seeds,"years":years,"archived_hashes_matched":matched,
                "totals":totals,"trajectories":results}
    out.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=out.parent) as tmp:
        staging = Path(tmp,"preferences.json")
        staging.write_bytes((json.dumps(document,sort_keys=True,indent=2)+"\n").encode("utf-8"))
        # Windows rename is atomic and refuses an existing destination. On POSIX
        # an exclusive hard link gives the same no-overwrite publication semantics.
        if os.name=="nt":
            staging.rename(out)
        else:
            os.link(staging,out)
    return document


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--seeds",type=int,default=20)
    p.add_argument("--years",type=int,default=200)
    p.add_argument("--workers",type=int,default=4)
    args = p.parse_args()
    result = run(**vars(args))
    print(f"{result['seeds']} trajectories, {result['archived_hashes_matched']} archived hashes matched")
