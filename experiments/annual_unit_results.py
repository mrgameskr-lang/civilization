"""Summarize signed paired differences for the fixed player command and hold arms."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from statistics import median

from civsim.storage import canonical_line
from civsim.annual_game import create
from civsim.unit_economy import step_game
from experiments.annual_unit_study import ORDER, run_seed


def verify_opening(seed, full):
    game = create(seed)
    step_game(game)
    second = step_game(game,ORDER)["unit_game"]
    third = step_game(game)["unit_game"]
    if second["receipt"]!=full["paths"][0]["receipt"] or second["closing_away"]!=third["opening_away"]:
        raise ValueError(f"arrival or next opening differed at seed {seed}")
    return {"seed":seed,"moved":second["receipt"]["ok"],"year2_close":second["closing_away"],
            "year3_open":third["opening_away"]}


def summarize(directory):
    summary = {}
    for group, first in (("development",0),("validation",20)):
        reasons = Counter()
        outcomes = {}
        for seed in range(first,first+20):
            data = json.loads((directory/f"seed-{seed:02}.json").read_bytes())
            move,hold = data["paths"]
            if (data["sample"],data["seed"],move["arm"],hold["arm"])!=(group,seed,"move","hold"):
                raise ValueError("unpaired seed")
            reasons[move["receipt"]["reason"]] += 1
            for year,a,b in zip((50,100,200),move["checkpoints"],hold["checkpoints"],strict=True):
                if not (a["year"]==b["year"]==year and b["closing_away"]==[]):
                    raise ValueError("invalid checkpoint")
                at_year = outcomes.setdefault(year,{"present_at_4":0,"deltas_by_seed":{}})
                at_year["present_at_4"] += sum(n for h,loc,n in a["closing_away"] if (h,loc)==(5,4))
                delta = {key:a["cumulative"][key]-b["cumulative"][key] for key in a["cumulative"]}
                delta["population"]=a["population"]-b["population"]
                at_year["deltas_by_seed"][seed]=delta
        for values in outcomes.values():
            paired=values["deltas_by_seed"]
            for field in ("eaten","domestic_goods","food_unmet","population"):
                numbers=[delta[field] for delta in paired.values()]
                values[field]={"min":min(numbers),"max":max(numbers),"median":median(numbers),
                               "positive":sum(n>0 for n in numbers),"negative":sum(n<0 for n in numbers),
                               "zero":numbers.count(0)}
        summary[group]={"attempts":20,"outcomes":dict(reasons),"years":outcomes}
    return summary


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study",type=Path)
    parser.add_argument("--out",type=Path,required=True)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument("--repeat-seeds",type=int,nargs="+")
    mode.add_argument("--verify-openings",action="store_true")
    args=parser.parse_args()
    if args.repeat_seeds:
        matched={}
        for seed in args.repeat_seeds:
            original=(args.study/f"seed-{seed:02}.json").read_bytes()
            repeated=canonical_line(run_seed(seed))
            if original!=repeated:
                raise ValueError(f"independent replay differed at seed {seed}")
            matched[seed]=sha256(original).hexdigest()
        result={"matched_seed_files":matched, "years":200, "arms":["move","hold"]}
    elif args.verify_openings:
        rows=[verify_opening(seed,json.loads((args.study/f"seed-{seed:02}.json").read_bytes())) for seed in range(40)]
        result={"seeds":rows,"moves":sum(r["moved"] for r in rows),
                "next_open_at_destination":sum(n for r in rows for h,loc,n in r["year3_open"] if (h,loc)==(5,4))}
    else:
        result=summarize(args.study)
    with args.out.open("xb") as stream:
        stream.write(canonical_line(result))
