"""Publish complete, same-opening public-supply interventions with reproducible receipts."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from civsim import supply62
from civsim.model import GOODS, generate_world
from civsim.regions import regionalize
from civsim.storage import canonical_line


def summarize(record):
    regions = record["regions"]
    roads = record["government"]["roads"]
    directions = [flow for pair in record["diplomacy"]["pairs"] for flow in pair["flows"]["directions"]]
    choices = [d for p in record["diplomacy"]["pairs"] for d in p["policy"]["directions"]]
    donors = record["diplomacy"]["physical"]["aid"]["donors"]
    service = record.get("service", {}).get("regions", [])
    return {
        "population": sum(r["closing"]["population"] for r in regions),
        "eaten": sum(r["consumption"]["food_eaten"] for r in regions),
        "unmet": sum(r["consumption"]["food_unmet"] for r in regions),
        "eaten_by_region": {r["id"]:r["consumption"]["food_eaten"] for r in regions},
        "produced": {g:sum(r["production"]["produced"][g] for r in regions) for g in GOODS},
        "public_cargo": sum(s["quantity"] for s in record["supply"]["shipments"]),
        "domestic_private_cargo": sum(s["quantity"] for s in record["domestic"]["shipments"]),
        "foreign_private_cargo": sum(sum(d["goods"].values()) for d in directions),
        "public_edge_load": sum(r["supply_use"] for r in roads),
        "private_edge_load": sum(r["private_use"] for r in roads),
        "aid_authorized": sum(d["aid_quantity"] for d in choices),
        "aid_sent": sum(d["aid_sent"] for d in directions),
        "aid_received": sum(d["aid_received"] for d in directions),
        "aid_freight": sum(d["aid_freight"] for d in directions),
        "aid_handling": sum(d["aid_handling"] for d in directions),
        "internal_aid_freight": sum(d["internal_freight"] for d in donors),
        "aid_budget": sum(d["planned_budget"] for d in donors),
        "aid_debit": sum(d["actual_debit"] for d in donors),
        "service": {k:sum(r[k] for r in service) for k in
                    ("enrolled","serving","available","ration_food","tools_used","travel_food","closing_roster")},
    }


def sha(data):
    return hashlib.sha256(data).hexdigest()


def publish(output, engine, fork, cases, arm):
    output = Path(output)
    if os.path.lexists(output):
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as staging:
        folder = Path(staging)/"forks"
        folder.mkdir()
        receipts = []
        for seed, year in cases:
            world = regionalize(generate_world(seed))
            sim = engine.start62(world)
            previous = None
            for t in range(1,year):
                previous = engine.step62(sim,t,arm)
            opening = canonical_line(engine.snapshot62(sim))
            actual, held = fork(sim,year)
            if canonical_line(engine.snapshot62(sim))!=opening:
                raise ValueError("intervention changed opening state")
            if [p["policy"] for p in actual["diplomacy"]["pairs"]]!=[p["policy"] for p in held["diplomacy"]["pairs"]]:
                raise ValueError("opening diplomatic approvals differ")
            if actual!=engine.step62(sim,year,arm):
                raise ValueError("ordinary branch differs from normal engine")
            path = folder/f"seed{seed}-year{year}.jsonl.gz"
            cases_bytes = [canonical_line(r) for r in (actual,held)]
            with path.open("xb") as raw, gzip.GzipFile(filename="",mode="wb",fileobj=raw,mtime=0) as stream:
                for data in cases_bytes:
                    engine.audit62(json.loads(data),geography=world,previous_record=previous)
                    stream.write(data)
            receipts.append({"seed":seed,"year":year,"arm":arm,"file":path.name,"file_sha256":sha(path.read_bytes()),
                             "opening_sha256":sha(opening),"ordinary_sha256":sha(cases_bytes[0]),
                             "held_sha256":sha(cases_bytes[1]),"ordinary":summarize(actual),"held":summarize(held)})
        (folder/"summary.json").write_bytes(canonical_line(receipts))
        folder.rename(output)
    return receipts


def run_cli(engine, fork, cases, arm):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True)
    args = parser.parse_args()
    for r in publish(args.out,engine,fork,cases,arm):
        print(r["file"], r["file_sha256"])


if __name__=="__main__":
    run_cli(supply62,supply62.fork_supply62,[(0,4),(1,5),(2,42)],"B")
