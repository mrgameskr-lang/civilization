"""Development-only 5C paths with endogenous economic feedback under the seven preregistered rules."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack, contextmanager
import csv
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import time
from unittest.mock import patch

from civsim import competition, competition_rules
from civsim.fiscal_policy import ACTIONS
from civsim.model import generate_world
from civsim.regions import regionalize
from civsim.storage import canonical_line
from experiments.election_diagnostics5d import TABLES, VARIANTS, _publish


def _without_performance(group, incumbent):
    values = {f: sum(competition_rules.PLATFORMS[f][a]*group["signals"][a] for a in ACTIONS)//12
              for f in competition_rules.FACTIONS}
    return values,0


@contextmanager
def _worker_settings(variant):
    """Restore all rule bindings before this worker accepts the next independent path."""
    programs = {f:dict(zip(ACTIONS,weights,strict=True))
                for f,weights in zip(competition_rules.FACTIONS,TABLES[variant.table],strict=True)}
    with ExitStack() as stack:
        for module in (competition,competition_rules):
            stack.enter_context(patch.object(module,"TERM",variant.term))
            stack.enter_context(patch.object(module,"SEATS",variant.seats))
        stack.enter_context(patch.object(competition_rules,"PLATFORMS",programs))
        if not variant.performance:
            stack.enter_context(patch.object(competition_rules,"_preference",_without_performance))
        yield


def _path(job):
    seed, variant, horizons = job
    with _worker_settings(variant):
        sim = competition.start_competition(regionalize(generate_world(seed)))
        initial = hashlib.sha256(canonical_line(competition.competition_snapshot(sim))).hexdigest()
        digest = hashlib.sha256()
        cumulative = Counter()
        checkpoints = []
        for y in range(1,max(horizons)+1):
            row = competition.step_competition(sim,y,"C","fixed")
            digest.update(canonical_line(row))
            for r in row["regions"]:
                c = r["consumption"]
                cumulative.update(food_need=c["food_need"],food_unmet=c["food_unmet"])
            for r in row["competition"]["countries"]:
                e = r["election"]
                cumulative.update(elections=int(e["election"]),turnovers=int(e["turnover"]),
                                  installations=int(e["installation"]))
                if e["election"]:
                    cumulative.update(vote_mutualists=e["vote_points"]["mutualists"],
                                      participation_points=e["participation_points"])
            if y in horizons:
                checkpoints.append({"year":y,"population":sum(c["closing"]["population"] for c in row["countries"]),
                                    **cumulative,"years_sha256":digest.hexdigest()})
        return {"seed":seed,"variant":variant.name,"initial_sha256":initial,"checkpoints":checkpoints}


def run(out, workers, verify=False):
    out = Path(out)
    if not 1<=workers<=28:
        raise ValueError("workers must be 1 to 28")
    if not verify and os.path.lexists(out):
        raise FileExistsError(out)
    if verify and not out.is_file():
        raise FileNotFoundError(out)
    horizons = (50,100,200)
    jobs = [(s,v,horizons) for s in range(4) for v in VARIANTS]
    # Even a one-worker run stays outside the caller's Python process.
    with ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context("spawn")) as pool:
        trials = list(pool.map(_path,jobs))
    ref = Path(__file__).resolve().parents[1]/"examples"/"phase5c"/"study"/"dev"/"runs.csv"
    with ref.open(encoding="utf-8",newline="") as f:
        archived = {(int(r["seed"]),int(r["year"])):r for r in csv.DictReader(f) if r["arm"]=="C"}
    for r in trials:
        for c in r["checkpoints"]:
            old = archived[r["seed"],c["year"]]
            if old["initial_sha256"]!=r["initial_sha256"]:
                raise ValueError("different initial stock, map or cabinets")
            if r["variant"]=="reference" and (
                    old["years_sha256"]!=c["years_sha256"] or int(old["final_population"])!=c["population"]
                    or int(old["food_deficit"])!=c["food_unmet"] or int(old["turnovers"])!=c["turnovers"]):
                raise ValueError("5C economic control differs from its archived path")
    doc = {"sample":"development seeds 0–3","years":200,"horizons":horizons,"world_years":4*len(VARIANTS)*200,
           "model":"5C C fixed taxes, seven election specifications, endogenous economics and politics",
           "settings":[vars(v) for v in VARIANTS],"archived_reference_checkpoints_matched":12,"trials":trials}
    raw = (json.dumps(doc,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode("utf-8")
    if verify:
        if raw!=out.read_bytes():
            raise ValueError("independent economic feedback replay differs")
    else:
        _publish(out,raw)
    return hashlib.sha256(raw).hexdigest()


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",required=True,type=Path)
    parser.add_argument("--workers",type=int,default=4)
    parser.add_argument("--verify",action="store_true")
    a=parser.parse_args()
    started=time.perf_counter()
    sha=run(a.out,a.workers,a.verify)
    print(f"28 trajectories, 84 checkpoints, 12 archived controls matched, SHA-256 {sha}, {time.perf_counter()-started:.2f} s")
