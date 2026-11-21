"""Replay the unchanged 6.0B2 D control and publish civilian fiscal and population receipts."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import csv
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from civsim import peace62
from civsim.model import GOODS, generate_world
from civsim.regions import regionalize
from civsim.storage import canonical_line
from experiments.verify_public62 import HORIZONS, ROOT, _reference


def require(condition, message):
    if not condition:
        raise ValueError(message)


def civic_year(record):
    """Project one audited close. Addresses, household goods and warehouse custody stay distinct."""
    require(record["public_policy"]["arm"]=="D" and record["public_policy"]["diagnostic"] is None,
            "expected ordinary 6.0B2 D")
    depots = {r["region"]:r for r in record["government"]["depots"]}
    groups = {r["id"]:r["closing"]["groups"] for r in record["politics"]["regions"]}
    ballots = {r["id"]:r["election"] for r in record["competition"]["countries"]}
    accounts = {r["id"]:r for r in record["government"]["accounts"]}
    regional = []
    owned = {n["id"]:Counter() for n in record["countries"]}
    for r in record["regions"]:
        i, owner, start, end = r["id"], r["owner"], r["opening"], r["closing"]
        meal, vital = r["consumption"], r["demography"]
        require(depots[i]["owner"]==owner==end["owner"], "warehouse owner mismatch")
        require(start["population"]==meal["food_need"]==meal["food_eaten"]+meal["food_unmet"],
                "one resident meal budget per person")
        require(end["population"]==start["population"]+vital["births"]-vital["deaths"]
                +vital["immigrants"]-vital["emigrants"], "resident register mismatch")
        values = dict(population_open=start["population"],population_close=end["population"],cash=end["cash"],
                      food_need=meal["food_need"],food_eaten=meal["food_eaten"],food_unmet=meal["food_unmet"],
                      births=vital["births"],deaths=vital["deaths"],immigrants=vital["immigrants"],
                      emigrants=vital["emigrants"])
        for good in GOODS:
            values["private_"+good] = end["stock"][good]
            values["public_"+good] = depots[i]["closing"][good]
        for signal in ("support","discontent"):
            values[signal+"_points"] = sum(g["members"]*g[signal] for g in groups[i].values())
        values["members"] = sum(g["members"] for g in groups[i].values())
        regional.append(dict(region=i,owner=owner,**values))
        owned[owner].update(values)
    require(len(regional)==len(depots)==len({r["region"] for r in regional}),"incomplete regional ledger")
    national = []
    for n in record["countries"]:
        owner = n["id"]
        total, close, account = owned[owner], n["closing"], accounts[owner]
        require((total["population_close"],total["cash"])==(close["population"],close["cash"]),"country totals differ")
        for good in GOODS:
            private, public = total["private_"+good],total["public_"+good]
            require(private==account["private_close"][good]==close["stock"][good]
                    and public==account["public_close"][good] and private+public==account["combined_close"][good],
                    "public/private closing inventories differ")
        ballot = ballots[owner]
        national.append(dict(owner=owner,**total,elections=int(ballot["election"]),
                             turnovers=int(ballot["turnover"]),installations=int(ballot["installation"])))
    return regional,national


def replay(job):
    seed, expected = job
    world = regionalize(generate_world(seed))
    sim = peace62.start62(world)
    opening = hashlib.sha256(canonical_line(peace62.snapshot62(sim))).hexdigest()
    chain = hashlib.sha256()
    prior = None
    regional, national, checks = [], [], []
    totals = {n.id:Counter() for n in world.nations}
    for year in range(1,max(expected)+1):
        ledger = peace62.step62(sim,year,"D")
        peace62.audit62(ledger,geography=world,previous_record=prior)
        regions,countries = civic_year(ledger)
        for row in countries:
            totals[row["owner"]].update({k:row[k] for k in
                ("elections","turnovers","installations","food_need","food_eaten","food_unmet",
                 "support_points","discontent_points","members")})
        chain.update(canonical_line(ledger))
        if year in expected:
            require((opening,chain.hexdigest())==expected[year],f"historical mismatch at {seed}/{year}")
            checks.append(dict(seed=seed,year=year,initial_sha256=opening,years_sha256=chain.hexdigest()))
            regional.extend(dict(seed=seed,year=year,**r) for r in regions)
            national.extend(dict(seed=seed,year=year,owner=c["owner"],population_close=c["population_close"],
                                 cash=c["cash"],**totals[c["owner"]]) for c in countries)
        prior = ledger
    return checks, regional, national


def write_csv(path,rows):
    with path.open("x",encoding="utf8",newline="") as stream:
        writer = csv.DictWriter(stream,fieldnames=tuple(rows[0]),lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run(output,workers):
    require(workers>0,"workers must be positive")
    if os.path.lexists(output):
        raise FileExistsError(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    jobs, sources = [], {}
    for sample in ("dev","holdout"):
        archive, sources[sample] = _reference(ROOT/"examples/phase6b2/study",sample,("C","D"))
        for seed in sorted({k[0] for k in archive}):
            jobs.append((seed,{year:archive[seed,"D",year] for year in HORIZONS}))
    checks, regions, countries = [], [], []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for verified, local, national in pool.map(replay,jobs):
            checks.extend(verified)
            regions.extend(local)
            countries.extend(national)
    with TemporaryDirectory(dir=output.parent) as tmp:
        stage = Path(tmp)/"study"
        stage.mkdir()
        tables = {}
        for name,rows in (("checkpoints",checks),("regional-closes",regions),("country-totals",countries)):
            path = stage/(name+".csv")
            write_csv(path,rows)
            tables[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        receipt = dict(baseline="6.0B2/D",samples={"dev":[0,19],"holdout":[20,39]},world_years=len(jobs)*max(HORIZONS),
                       checkpoint_matches=len(checks),region_closes=len(regions),country_checkpoints=len(countries),
                       reference_runs_sha256=sources,table_sha256=tables)
        (stage/"receipt.json").write_bytes(canonical_line(receipt))
        stage.rename(output)
    return receipt


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers",type=int,default=6)
    parser.add_argument("--out",type=Path,required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.out,args.workers)))
