"""Suppress one naturally mobilized group for one year on the original development opening."""
import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from civsim.model import GOODS, generate_world
from civsim.regions import regionalize
from experiments.phase5a import _sha
from experiments.phase5d import TYPES, _goods
from experiments.publication import publish_file


def choose(events):
    selected={}
    for e in events:
        act=e["action"]
        if act not in TYPES: continue
        if act=="refusal":
            score=sum(w*int(e["refused_"+g]) for g,w in zip(GOODS,(8,4,12),strict=True))
        elif act=="petition":
            score=int(e["response_targeted"])
        else:
            score=int(e["withheld_workers"])
        rank=(score,int(e["participants"]),-int(e["year"]),-int(e["seed"]),-int(e["region"]))
        if act not in selected or rank>selected[act][0]:
            selected[act]=(rank,e)
    return {k:v[1] for k,v in selected.items()}


def _view(record,i,group):
    reg=next(r for r in record["regions"] if r["id"]==i)
    owner=reg["owner"]
    p=reg["production"]
    section=record["collective"]
    g=next(r["groups"][group] for r in section["regions"] if r["id"]==i)
    response=next(r for r in section["responses"] if r["id"]==owner)
    levy=next(r for r in record["government"]["levies"] if r["region"]==i)
    national=next(r for r in record["countries"] if r["id"]==owner)["closing"]
    account=next(r for r in record["government"]["accounts"] if r["id"]==owner)
    political=next(r for r in record["politics"]["regions"] if r["id"]==i)
    member=political["closing"]["groups"][group]
    paths=record["domestic"]["shipments"]
    nodes=[r for r in record["regions"] if r["owner"]==owner]
    measures={"members":g["members"],"participants":g["participants"],"withheld_workers":g["withheld_workers"],
              "regional_withheld_total":p["withheld_workers"],"regional_population":reg["closing"]["population"],
              "regional_food_need":reg["consumption"]["food_need"],"regional_food_unmet":reg["consumption"]["food_unmet"],
              **{"regional_output_"+good:p["produced"][good] for good in GOODS},
              "local_food_shipped_in":sum(t["quantity"] for t in paths if t["target"]==i and t["good"]=="food"),
              "national_population":national["population"],"national_unmet":sum(r["consumption"]["food_unmet"] for r in nodes),
              "national_food_output":sum(r["production"]["produced"]["food"] for r in nodes),
              "national_relief":account["totals"]["relief_food"],
              "national_admin_used":response["petition_admin_used"],"group_closing_support":member["support"],
              "group_closing_discontent":member["discontent"],
              **{"national_public_"+good:account["public_close"][good] for good in GOODS},
              **{"national_private_"+good:account["private_close"][good] for good in GOODS},
              **{"national_paid_"+good:account["totals"]["levied_"+good] for good in GOODS},
              **{"group_"+k:v for k,v in _goods(levy["civic_tax"]["by_group"][group]).items()}}
    return {"annual_sha256":_sha(record),"action":g["action"],"prior":g["prior"],"demand":g["demand"],
            "group_opening_support":political["opening"]["groups"][group]["support"],"response":response,
            "measure":measures}


def run_forks(study,output):
    from civsim.collective import collective_snapshot, fork_action_year, start_collective, step_collective
    study,output=Path(study),Path(output)
    if output.exists() or output.is_symlink(): raise FileExistsError(output)
    execution=json.loads((study/"execution.json").read_text(encoding="utf8"))
    if execution["sample"]!="dev": raise ValueError("select interventions from development observations")
    eventfile=study/"events.csv.gz"
    if hashlib.sha256(eventfile.read_bytes()).hexdigest()!=execution["table_sha256"][eventfile.name]:
        raise ValueError("published event file differs from its execution receipt")
    with gzip.open(eventfile,"rt",encoding="utf8",newline="") as stream: chosen=choose(csv.DictReader(stream))
    schedules={}
    for e in chosen.values():
        schedules.setdefault(int(e["seed"]),{}).setdefault(int(e["year"]),[]).append(e)
    result=[]
    for seed,years in sorted(schedules.items()):
        sim=start_collective(regionalize(generate_world(seed)))
        for y in range(1,max(years)+1):
            actual_hash=None
            for e in years.get(y,[]):
                region,group=int(e["region"]),e["group"]
                opening=_sha(collective_snapshot(sim))
                actual,other=fork_action_year(sim,y,region,group)
                if _sha(collective_snapshot(sim))!=opening: raise ValueError("fork modified its source")
                a,b=_view(actual,region,group),_view(other,region,group)
                if a["action"]!=e["action"] or b["action"]!="none" or b["measure"]["participants"]!=0:
                    raise ValueError("fork did not suppress exactly the selected natural action")
                if a["measure"]["participants"]!=int(e["participants"]): raise ValueError("chosen case differs from published event")
                def actors(record):
                    return {(r["id"],k):(g["action"],g["participants"],g["withheld_workers"])
                            for r in record["collective"]["regions"] for k,g in r["groups"].items()
                            if (r["id"],k)!=(region,group)}
                if actors(actual)!=actors(other): raise ValueError("another group's opening action changed")
                actual_hash=a["annual_sha256"]
                result.append({"seed":seed,"year":y,"region":region,"owner":int(e["owner"]),"group":group,
                    "action":e["action"],"opening_sha256":opening,"actual":a,"suppressed":b,
                    "delta_actual_minus_suppressed":{k:v-b["measure"][k] for k,v in a["measure"].items()}})
            real=step_collective(sim,y,enabled=True)
            if actual_hash is not None and _sha(real)!=actual_hash: raise ValueError("fork differs from normal execution")
    output.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as temp:
        staged=Path(temp,"case.json")
        staged.write_text(json.dumps({"development_event_sha256":execution["table_sha256"][eventfile.name],
            "missing_types":[t for t in TYPES if t not in chosen],"cases":result},indent=2,ensure_ascii=False)+"\n",
            encoding="utf8",newline="\n")
        publish_file(staged,output)
    return len(result)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--study",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    a=p.parse_args()
    print(f"{run_forks(a.study,a.out)} matched development interventions")
