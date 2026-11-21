"""Measure same-year meal incidence and local spending constraints from the frozen public panels."""
import argparse
from collections import Counter, defaultdict
import csv
import gzip
import hashlib
from itertools import groupby
import json
from operator import itemgetter
from pathlib import Path
from tempfile import TemporaryDirectory

from experiments.publication import publish_file


ARMS=("B","E","F")
GROUPS=("farm","industry","consumer")
ROLES=("receivers","donor_only","other","world")
KEY=("seed","arm","year")
REG=("region","owner","food_need","food_eaten","direct_eaten_delta","aid_sent","aid_received",
     *(g+s for g in GROUPS for s in ("_members","_direct")))
COUNTRY=("owner","aid_sent","aid_received","actual_debit","approved_donor_budget","approved_donor_unspent_budget",
         "planned_budget","budget_overrun","aid_authorized","aid_unshipped","aid_freight_food","aid_handling_food",
         "donor_control_reserve_delta","donor_control_deficit_delta","direct_eaten_delta",
         "donor_control_population_years","donor_control_support_delta_x_members")
DIRECTION=("source","target","authorized","dispatched","unshipped","received","freight","handling","shortfall_reasons")
LIMITS=("authorized","road","stock","storage","budget")
ATTEMPT=("quantity","uncapped_quantity","budget_displaced","binding",*("limit_"+k for k in LIMITS))
FILES=("region-years.csv.gz","country-years.csv.gz","direction-years.csv.gz","aid-attempts.csv.gz")


def check(value,message):
    if not value:
        raise ValueError(message)


def panel(path,fields):
    with gzip.open(path,"rt",encoding="utf8",newline="") as stream:
        reader=csv.reader(stream)
        header=next(reader)
        arm=header.index("arm")
        keys=KEY+fields
        extract=itemgetter(*(header.index(k) for k in keys))
        for row in reader:
            if row[arm] in ARMS:
                yield dict(zip(keys,extract(row),strict=True))


def sign(counter,val):
    label="positive" if val>0 else "negative" if val<0 else "zero"
    counter[label]+=1
    if val:
        counter[label+"_units"]+=val
    counter["net"]+=val
    counter["count"]+=1


def classify_world(regions):
    changes={k:Counter() for k in ROLES}
    exposure=Counter()
    for r in regions:
        delta,eaten,need,received,sent=(int(r[k]) for k in
            ("direct_eaten_delta","food_eaten","food_need","aid_received","aid_sent"))
        check(0<=eaten<=need and 0<=eaten-delta<=need,"impossible actual or no-aid meal")
        role="receivers" if received else "donor_only" if sent else "other"
        sign(changes[role],delta)
        exposure.update(received=received,sent=sent,two_way=int(bool(received and sent)))
    sign(changes["world"],sum(changes[k]["net"] for k in ROLES[:-1]))
    if not exposure["sent"]:
        check(not exposure["received"] and all(not c["positive"] and not c["negative"] for c in changes.values()),
              "changed regional meals without aid")
    return changes,exposure


def count_attempt(r,c):
    q,uncapped,displaced=(int(r[k]) for k in ("quantity","uncapped_quantity","budget_displaced"))
    limits={k:int(r["limit_"+k]) for k in LIMITS if r["limit_"+k] not in ("",None)}
    raw=min(limits.values())
    physical=min(v for k,v in limits.items() if k!="budget")
    tied={k for k,v in limits.items() if v==raw}
    check(tied==set(r["binding"].split("|")) and q==(raw if raw>=2 else 0) and
          uncapped==(physical if physical>=2 else 0) and displaced==uncapped-q,"misreported attempt limit")
    c.update(attempts=1,ties=int(len(tied)>1),budget_tied=int("budget" in tied and len(tied)>1),
             budget_reducing=int(displaced>0),displaced_attempt_qty=displaced,minimum_lot=int(raw==1),
             zero_attempts=int(q==0))
    for k in tied:
        c["binding_"+k]+=1


def choose(cases,category,score,content):
    if category not in cases or score>cases[category][0]:
        cases[category]=(score,content)


def arm_tables():
    return dict(meals={k:Counter() for k in ROLES},exposure=Counter(),budget=Counter(),
                donor={k:Counter() for k in ("actual_meals","reserve_vs_A","deficit_vs_A")},
                origin_opinion={g:Counter() for g in GROUPS},attempts=Counter(),
                shortfalls=defaultdict(Counter),cases={})


def collect(folder):
    folder=Path(folder)
    meta=json.loads((folder/"execution.json").read_text(encoding="utf8"))
    for file in FILES:
        with (folder/file).open("rb") as f:
            check(hashlib.file_digest(f,"sha256").hexdigest()==meta["table_sha256"][file],"edited input "+file)
    data={arm:arm_tables() for arm in ARMS}
    sample_name=meta["sample"]
    for (seed,arm,year),group in groupby(panel(folder/FILES[0],REG),itemgetter(*KEY)):
        regions=list(group)
        check(len(regions)==32 and len({r["region"] for r in regions})==32,"missing region")
        out=data[arm]
        out["exposure"]["all_world_years"]+=1
        changes,exposure=classify_world(regions)
        if not exposure["received"]:
            continue
        for name,c in changes.items():
            out["meals"][name].update(c)
        out["exposure"].update(exposure)
        out["exposure"]["aid_world_years"]+=1
        for r in regions:
            if int(r["aid_sent"])>0:
                for g in GROUPS:
                    members,delta=int(r[g+"_members"]),int(r[g+"_direct"])
                    if members:
                        c=out["origin_opinion"][g]
                        sign(c,delta)
                        c.update(members=members,weighted=members*delta)
        if sample_name!="dev":
            continue
        identity={"seed":int(seed),"year":int(year)}
        world={"roles":{k:c["net"] for k,c in changes.items()},**identity,"received":exposure["received"]}
        world_delta=changes["world"]["net"]
        if world_delta<0:
            choose(out["cases"],"world_negative",-world_delta,world)
        if world_delta>0:
            choose(out["cases"],"world_positive",world_delta,world)
        for r in regions:
            amt,delta=int(r["aid_received"]),int(r["direct_eaten_delta"])
            if amt and delta<=0:
                category="region_negative" if delta else "region_zero"
                candidate={**identity,"owner":int(r["owner"]),"region":int(r["region"]),"received":amt,
                           "delta":delta,"eaten":int(r["food_eaten"]),"need":int(r["food_need"]),"world_delta":world_delta}
                choose(out["cases"],category,(-delta,amt),candidate)
    country_years=Counter()
    for r in panel(folder/FILES[1],COUNTRY):
        arm=r["arm"]
        country_years[arm]+=1
        out=data[arm]
        c=out["budget"]
        q,debit,sent,received,freight,handling,authorized=(int(r[k]) for k in ("planned_budget","actual_debit","aid_sent",
            "aid_received","aid_freight_food","aid_handling_food","aid_authorized"))
        over=int(r["budget_overrun"])
        check(debit==sent+freight and over==max(0,debit-q),"donor payments differ")
        c.update(authorized=authorized,sent=sent,received=received,freight=freight,handling=handling,
                 actual_debit=debit,approved_donor_budget=int(r["approved_donor_budget"]),approved_years=int(authorized>0),
                 overrun=over,overrun_years=int(over>0),unspent_approved=int(r["approved_donor_unspent_budget"]),
                 unshipped=int(r["aid_unshipped"]))
        if not debit:
            continue
        c["funded_donor_years"]+=1
        c["donor_support_members"]+=int(r["donor_control_population_years"])
        c["donor_support_weighted_vs_A"]+=float(r["donor_control_support_delta_x_members"])
        for field,dest in (("direct_eaten_delta","actual_meals"),("donor_control_reserve_delta","reserve_vs_A"),
                           ("donor_control_deficit_delta","deficit_vs_A")):
            sign(out["donor"][dest],int(r[field]))
    direction_totals=defaultdict(Counter)
    for r in panel(folder/FILES[2],DIRECTION):
        q,sent,net,handling,fee,left=(int(r[k]) for k in ("authorized","dispatched","received","handling","freight","unshipped"))
        check(q==sent+left and sent==net+handling,"bilateral food did not reconcile")
        direction_totals[r["arm"]].update(authorized=q,sent=sent,received=net,handling=handling,freight=fee,unshipped=left)
        if left:
            reason=r["shortfall_reasons"]
            check(bool(reason),"unexplained unshipped cargo")
            data[r["arm"]]["shortfalls"][reason].update(directions=1,units=left,zero_dispatch=int(not sent),
                                                       zero_dispatch_units=left if not sent else 0)
    for r in panel(folder/FILES[3],ATTEMPT):
        count_attempt(r,data[r["arm"]]["attempts"])
    worlds=meta["seeds"]*max(meta["horizons"])
    for arm,out in data.items():
        c=out["budget"]
        check(all(c[k]==n for k,n in direction_totals[arm].items()) and out["exposure"]["received"]==c["received"]
              and out["exposure"]["sent"]==c["sent"] and c["unshipped"]==c["authorized"]-c["sent"],
              "national, regional and bilateral aid accounts differ")
        check(out["exposure"]["all_world_years"]==worlds and country_years[arm]==worlds*8,"incomplete panel")
        out["cases"]={k:v[1] for k,v in out["cases"].items()}
    return {"sample":sample_name,"seeds":meta["seeds"],"years":max(meta["horizons"]),
            "arms":data,"source_sha256":{k:meta["table_sha256"][k] for k in FILES}}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--study",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    if args.out.exists() or args.out.is_symlink():
        raise FileExistsError(args.out)
    result={k:collect(args.study/k) for k in ("dev","holdout")}
    check(all(k==v["sample"] for k,v in result.items()),"wrong sample placement")
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=args.out.parent) as tmp:
        path=Path(tmp,"aid-diagnostics.json")
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8",newline="\n")
        publish_file(path,args.out)


if __name__=="__main__":
    main()
