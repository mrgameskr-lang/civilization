"""Predefined development case selection and same-opening diplomatic counterfactuals."""
import argparse
import csv
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from civsim.diplomacy import diplomacy_snapshot, fork_diplomacy_year, start_diplomacy, step_diplomacy
from civsim.model import generate_world
from civsim.regions import regionalize
from experiments.phase5a import _sha
from experiments.phase5d import _json
from experiments.phase6a import country_years, digest_file, physical, rates
from experiments.publication import publish_file


def choose(rows):
    """One highest-exposure and one earliest case per instrument, development records only."""
    best = {}
    def offer(kind, case, score):
        key = (case["seed"], case["year"], case["a"], case["b"], case["intervention"].get("source",-1))
        early = (case["year"],*key)
        for label, rank in (("highest_exposure",(-score,*early)),("earliest",early)):
            if (kind,label) not in best or rank<best[kind,label][0]:
                best[kind,label] = rank,{**case,"selection":label,"exposure":score}
    for r in rows:
        seed,year,a,b = (int(r[k]) for k in ("seed","year","a","b"))
        if not 0<=seed<20: raise ValueError("intervention selector received a holdout seed")
        if year==1: continue
        arm = r["arm"]
        case = {"seed":seed,"arm":arm,"year":year,"a":a,"b":b}
        if arm=="C" and int(r["agreements_started"]):
            offer("pact",{**case,"intervention":{"kind":"no_new_pact","a":a,"b":b}},
                  int(r["ab_trade_value"])+int(r["ba_trade_value"]))
        if arm!="D": continue
        for pref,s,t in (("ab_",a,b),("ba_",b,a)):
            for kind,keys,loss in (("open_trade",("trade_limit_permille",),("trade_denied",)),
                                   ("open_migration",("migration_limit_permille","migration_accept_permille"),
                                    ("exit_denied","entry_denied"))):
                if any(int(r[pref+k])<1000 for k in keys):
                    offer(kind,{**case,"intervention":{"kind":kind,"source":s,"target":t}},sum(int(r[pref+k]) for k in loss))
    return [c[1] for _,c in sorted(best.items())]


def view(record, world, a, b):
    owners = {r.id:r.owner for r in world.regions}
    edge, flow, _ = physical(record,world.borders,owners)
    countries = country_years(record, flow)
    section = record["diplomacy"]
    pair = next(p for p in section["pairs"] if (p["a"],p["b"])==(a,b))
    relevant = {k:sum(c[k] for c in countries.values()) for k in
                ("closing_population","food_deficit","food_need","produced_food","export_value","aid_received","emigrants")}
    return {"annual_sha256":_sha(record),"world":relevant,
            "countries":{str(i):{**countries[i],**rates(countries[i])} for i in (a,b)},
            "ab":dict(flow[a,b]),"ba":dict(flow[b,a]),"pair":pair,
            "roads":[{"source":x,"target":y,**c} for (x,y),c in edge.items() if {owners[x],owners[y]}=={a,b}],
            "trades":[t for t in record["border_market"]["trades"] if {owners[t["seller"]],owners[t["buyer"]]}=={a,b}],
            "migrations":[t for t in record["moves"] if {owners[t["source"]],owners[t["target"]]}=={a,b}]}


def validate_intervention(actual,alternative,setting):
    """Every other opening directive and all other physical opportunities start identical."""
    p,q = actual["diplomacy"],alternative["diplomacy"]
    if p["countries"]!=q["countries"] or p["borders"]!=q["borders"]:
        raise ValueError("diplomatic intervention changed an opening input")
    kind = setting["kind"]
    changed = 0
    for x,y in zip(p["pairs"],q["pairs"],strict=True):
        if (x["a"],x["b"],x["opening"])!=(y["a"],y["b"],y["opening"]):
            raise ValueError("diplomatic intervention changed pair history")
        after = y["policy"]
        before = x["policy"].copy()
        if kind=="no_new_pact" and (x["a"],x["b"])==(setting["a"],setting["b"]):
            if not before["agreement_started"]: raise ValueError("no natural pact to withhold")
            before.update(agreement_active=False,agreement_started=False,agreement_start=0,expires_after=0)
            changed+=1
        elif kind in ("open_trade","open_migration"):
            directions = [d.copy() for d in before["directions"]]
            for d in directions:
                if (d["source"],d["target"])!=(setting["source"],setting["target"]): continue
                fields=("trade_limit_permille",) if kind=="open_trade" else ("migration_limit_permille","migration_accept_permille")
                if not any(d[k]<1000 for k in fields): raise ValueError("no natural limit to lift")
                for k in fields: d[k]=1000
                changed+=1
            before["directions"]=directions
        if before!=after: raise ValueError("fork changed another diplomatic authorization")
    if changed!=1: raise ValueError("intervention affected an unexpected number of policies")


def run_forks(study,output):
    study,output = Path(study),Path(output)
    if output.exists() or output.is_symlink(): raise FileExistsError(output)
    receipt = json.loads((study/"execution.json").read_text(encoding="utf8"))
    path = study/"pair-years.csv.gz"
    if receipt["sample"]!="dev" or digest_file(path)!=receipt["table_sha256"][path.name]:
        raise ValueError("interventions require verified development pair-years")
    with gzip.open(path,"rt",encoding="utf8",newline="") as stream: cases=choose(csv.DictReader(stream))
    schedules = {}
    for c in cases:
        schedules.setdefault((c["seed"],c["arm"]),{}).setdefault(c["year"],[]).append(c)
    results = []
    for (seed,arm),years in sorted(schedules.items()):
        world = regionalize(generate_world(seed))
        sim = start_diplomacy(world)
        for y in range(1,max(years)+1):
            actual_hash = None
            for c in years.get(y,[]):
                opening = _sha(diplomacy_snapshot(sim))
                actual,other = fork_diplomacy_year(sim,y,c["intervention"])
                if _sha(diplomacy_snapshot(sim))!=opening: raise ValueError("fork mutated the common opening")
                validate_intervention(actual,other,c["intervention"])
                av,bv = (view(row,world,c["a"],c["b"]) for row in (actual,other))
                actual_hash = av["annual_sha256"]
                results.append({**c,"opening_sha256":opening,"actual":av,"alternative":bv,
                                "world_delta_actual_minus_alternative":{k:v-bv["world"][k] for k,v in av["world"].items()}})
            standard = step_diplomacy(sim,y,arm)
            if actual_hash is not None and _sha(standard)!=actual_hash:
                raise ValueError("natural intervention branch differs from original trajectory")
    output.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as temp:
        staged = Path(temp,"cases.json")
        _json(staged,{"pair_years_sha256":receipt["table_sha256"][path.name],"cases":results})
        publish_file(staged,output)
    return len(results)


if __name__=="__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--study",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    args = p.parse_args()
    print(f"{run_forks(args.study,args.out)} same-opening development comparisons")
