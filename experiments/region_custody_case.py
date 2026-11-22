"""Playback of annual-unit/1 for checking meal custody and the three separate population views."""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from civsim.annual_game import create
from civsim.postings65 import advance_postings, audit_postings
from civsim.regional_custody import audit_meal_custody, position_exits
from civsim.resident_exits import audit_resident_exits
from civsim.storage import canonical_line
from civsim.unit_economy import Move, audit_game, location_totals, step_game
from experiments.unit_economy_metrics import civil_totals

ORDER = Move(5,5,4,1)


def digest(obj):
    return sha256(canonical_line(obj)).hexdigest()


def observe(record, game, office_book, prior=None):
    audit_game(record,game.economy.world,previous=prior)
    duty=record["service"]
    offices, next_book=advance_postings(office_book,duty,year=record["year"])
    audit_postings(offices,duty)
    turn=record["unit_game"]
    measures=civil_totals(record)
    custody=audit_meal_custody(record)
    rows=audit_resident_exits(record["regions"],duty["regions"])
    depots={r["region"]:r for r in record["government"]["depots"]}
    output={
        "year":record["year"], "annual_sha256":digest(record),
        "opening_away":turn["opening_away"],"closing_away":turn["closing_away"],
        "opening_location_totals":location_totals(record,"opening"),
        "closing_location_totals":location_totals(record,"closing"),
        "administrative_affiliations":offices["closing"],
        "roster_accounts":rows,"location_exit_receipts":position_exits(turn,duty["regions"]),
        "public_warehouses":[{"region":i,"opening":d["opening"],"closing":d["closing"]} for i,d in sorted(depots.items())],
        "home_meal_receipts":custody,"private_deliveries_and_meals":measures,
        "one_way":turn["receipt"],"road":next(e for e in record["government"]["roads"] if (e["a"],e["b"])==(4,5)),
    }
    return output,next_book


def run_case():
    game=create(0)
    first=step_game(game)
    first_data,offices=observe(first,game,{})
    result={"rule":"annual-unit/1","seed":0,"common_first_year":first_data,"paths":{}}
    for name,order in (("move",ORDER),("hold",None)):
        fork=deepcopy(game)
        record=step_game(fork,order)
        second,book=observe(record,fork,offices,first)
        third,_=observe(step_game(fork),fork,book,record)
        if second["closing_away"]!=third["opening_away"]:
            raise ValueError("position discontinuity")
        result["paths"][name]=[second,third]
    return result


def shrinking_home():
    game=create(2)
    offices={}
    prior=None
    trace=[]
    for year in range(1,6):
        record=step_game(game,Move(7,7,4,1) if year==2 else None)
        data,offices=observe(record,game,offices,prior)
        trace.append({"year":year,"annual_sha256":data["annual_sha256"],
                      "home7":next(r for r in data["roster_accounts"] if r["home"]==7),
                      "locations":data["closing_away"],"receipt":data["one_way"],
                      "exits":[r for r in data["location_exit_receipts"] if r["home"]==7]})
        prior=record
    last=trace[-1]["home7"]
    if not trace[1]["receipt"]["ok"] or last["roster_close"]>=last["roster_open"]:
        raise ValueError("missing observed registration decline")
    return {"seed":2,"trace":trace}


def stocked_destination():
    game=create(0)
    opening=step_game(game)
    control=deepcopy(game)
    result={"seed":0,"opening_year1_sha256":digest(opening),"paths":{}}
    for label,fork,order in (("move",game,Move(5,5,7,1)),("hold",control,None)):
        prior=opening
        trace=[]
        for command in (order,None):
            row=step_game(fork,command)
            audit_game(row,fork.economy.world,previous=prior)
            receipts=audit_meal_custody(row)
            trace.append({"year":row["year"],"receipt":row["unit_game"]["receipt"],
                          "opening_away":row["unit_game"]["opening_away"],"closing_away":row["unit_game"]["closing_away"],
                          "local_warehouse":next(r["public_before_relief"] for r in receipts if r["home"]==7),
                          "delivery_and_meals":civil_totals(row)["world"],"annual_sha256":digest(row)})
            prior=row
        result["paths"][label]=trace
    return result


if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    target=cli.add_mutually_exclusive_group(required=True)
    target.add_argument("--out",type=Path)
    target.add_argument("--verify",type=Path)
    mode=cli.add_mutually_exclusive_group()
    mode.add_argument("--shrinking-home",action="store_true")
    mode.add_argument("--stocked-destination",action="store_true")
    args=cli.parse_args()
    probe=shrinking_home if args.shrinking_home else stocked_destination if args.stocked_destination else run_case
    data=canonical_line(probe())
    if args.out:
        args.out.parent.mkdir(parents=True,exist_ok=True)
        with args.out.open("xb") as stream:
            stream.write(data)
    elif args.verify.read_bytes()!=data:
        raise ValueError("observed annual records changed")
    print(json.dumps({"bytes":len(data),"sha256":sha256(data).hexdigest(),"world_years_executed":5}))
