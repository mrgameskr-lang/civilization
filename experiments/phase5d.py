"""Matched 5.0D mobilization paths, fiscal incidence, episodes and interventions."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import csv
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
from statistics import fmean
from tempfile import TemporaryDirectory
import time

from civsim.model import GOODS, generate_world
from civsim.regions import regionalize
from civsim.storage import canonical_line
from experiments.phase5a import _rates, _ratio, _read, _sha, _write, disparity
from experiments.phase5b import _allocations, choice_key
from experiments.phase5c import GROUPS, Tenure


ARMS=("off","on")
TYPES=("petition","protest","strike","refusal")
RESPONSES=("maintain","reprioritize","tax_adjust","compromise","defer")
ARCHIVE=Path(__file__).resolve().parents[1]/"examples/phase5c/study"
FLOWS=("assessed","concession","refused","paid")
TAX=tuple(k+"_"+g for k in FLOWS for g in GOODS)
EVENT=("seed","year","owner","region","group","action","demand","duration","demand_age","members","participants",
       "withheld_workers","pre_support","pre_discontent","pre_pressure","pre_shortage_permille","pre_fiscal_burden",
       "pre_levy_value","pre_food_unmet",
       "closing_support","next_closing_support","answered","response","response_targeted","project_targeted","tax_targeted","plan_changed",
       "food_output","food_need","food_unmet",*TAX)
ACTION_AMOUNTS=("group_years","participant_years","withheld_workers","started","completed","completed_duration",
                "weighted_pre_support","weighted_pre_discontent","weighted_pre_pressure","weighted_pre_shortage",
                "weighted_pre_burden","weighted_support_change","responded_years","answered_years","followup_weight",
                "weighted_followup_change",*TAX)
DELTAS=("final_population","food_need","food_deficit","deficit_share","within_country_ration_disparity","food_output",
        "ore_output","tools_output","final_soil","relief_food","public_labor","withheld_workers",
        "paid_food","paid_ore","paid_tools","world_freight_food","turnovers","economic_choice_changed")


class Spells:
    def __init__(self):
        self.action=None
        self.demand=None
        self.current=0
        self.completed=[]
        self.last_year=0

    def observe(self,year,action,demand=None):
        if year!=self.last_year+1: raise ValueError("spell observations must be consecutive")
        self.last_year=year
        action=action if action in TYPES else None
        ended=None
        if (action,demand)!=(self.action,self.demand):
            if self.current:
                ended=(self.action,self.current)
                self.completed.append(self.current)
            self.current=0
        self.action=action
        self.demand=demand
        if action: self.current+=1
        return ended


def _credit(counter,event):
    n=event["participants"]
    counter.update(group_years=1,participant_years=n,withheld_workers=event["withheld_workers"],
                   started=int(event["duration"]==1),weighted_pre_support=n*event["pre_support"],
                   weighted_pre_discontent=n*event["pre_discontent"],weighted_pre_pressure=n*event["pre_pressure"],
                   weighted_pre_shortage=n*event["pre_shortage_permille"],weighted_pre_burden=n*event["pre_fiscal_burden"],
                   weighted_support_change=n*(event["closing_support"]-event["pre_support"]),
                   responded_years=event["response_targeted"],answered_years=event["answered"])
    counter.update({k:event[k] for k in TAX})


def _json(path,data):
    path.write_text(json.dumps(data,indent=2,ensure_ascii=False)+"\n",encoding="utf8",newline="\n")


def _goods(tax):
    return {k+"_"+g:tax[k][g] for k in FLOWS for g in GOODS}


def _rate(column,numerator,denominator):
    return {column:numerator/denominator if denominator else None}


def _seed(job):
    from civsim.collective import collective_snapshot,start_collective,step_collective
    from civsim.competition import competition_snapshot
    seed,horizons,folder=job
    data={k:[] for k in ("runs","countries","regions","actions","responses","cases")}
    ref={}
    with (Path(folder)/f"events-{seed:03d}.csv").open("x",encoding="utf8",newline="") as stream:
        events=csv.DictWriter(stream,fieldnames=EVENT)
        for arm in ARMS:
            sim=start_collective(regionalize(generate_world(seed)))
            init_sha=_sha(collective_snapshot(sim))
            init_5c=_sha(competition_snapshot(sim.competition))
            world=sim.competition.world
            initial_pop=sum(r.population for r in world.regions)
            initial_cash=sum(r.cash for r in world.regions)
            stock={g:sum(r.stock[g] for r in world.regions) for g in GOODS}
            digest=hashlib.sha256()
            places,nations,summary=defaultdict(Counter),defaultdict(Counter),defaultdict(Counter)
            spells=defaultdict(Spells)
            group_exposures=Counter()
            response_totals=defaultdict(Counter)
            tenures=defaultdict(Tenure)
            pending={}
            extreme={}
            for year in range(1,max(horizons)+1):
                record=step_collective(sim,year,enabled=arm=="on")
                digest.update(canonical_line(record))
                gov=record["government"]
                accounts={a["id"]:a for a in gov["accounts"]}
                cabinets={c["id"]:c for c in record["competition"]["countries"]}
                politics={r["id"]:r for r in record["politics"]["regions"]}
                recs={c["id"]:c["recommendation"] for c in record["politics"]["countries"]}
                levies={l["region"]:l for l in gov["levies"]}
                civic=record.get("collective")
                if bool(civic)!=(arm=="on"): raise ValueError("incorrect intervention record boundary")
                actions={r["id"]:r["groups"] for r in civic["regions"]} if civic else {}
                responses={r["id"]:r for r in civic["responses"]} if civic else {}
                rations={r["id"]:(r["owner"],r["consumption"]["food_need"],r["consumption"]["food_eaten"])
                         for r in record["regions"]}
                world_gap,national_gap=disparity(rations)
                funds=_allocations(record)
                for r in record["regions"]:
                    i=r["id"]
                    owner,need,eaten=rations[i]
                    prod,meal=r["production"],r["consumption"]
                    inc=Counter({**funds[i],"food_need":need,"food_eaten":eaten,"food_deficit":need-eaten,
                           "absolute_world_ration_gap":world_gap[i],"absolute_national_ration_gap":national_gap[i],
                           "births":r["demography"]["births"],"deaths":r["demography"]["deaths"],
                           "withheld_workers":prod["withheld_workers"] if civic else 0,"active_group_years":0,"participant_years":0,
                           **{g+"_output":prod["produced"][g] for g in GOODS},
                           **{"sector_used_"+g:prod["used"][g] for g in GOODS},
                           **{"meal_used_"+g:meal["used"][g] for g in GOODS}})
                    levy=levies[i]
                    for g in GOODS:
                        inc["assessed_"+g]=levy["baseline_levy"][g] if civic else levy["levied"][g]
                        inc["concession_"+g]=levy["foregone_concession"][g] if civic else 0
                        inc["refused_"+g]=levy["refused"][g] if civic else 0
                        inc["paid_"+g]=levy["levied"][g]
                        if inc["assessed_"+g]!=sum(inc[k+"_"+g] for k in FLOWS[1:]):
                            raise ValueError("assessed taxes differ from concession, refusal and payment")
                    if civic:
                        group_tax=levy["civic_tax"]["by_group"]
                        if any(sum(group_tax[k][f][g] for k in GROUPS)!=inc[f+"_"+g] for f in FLOWS for g in GOODS):
                            raise ValueError("group tax incidence differs from region postings")
                        if sum(a["withheld_workers"] for a in actions[i].values())!=inc["withheld_workers"]:
                            raise ValueError("mobilization labor differs from production labor")
                    for g in GROUPS:
                        current=politics[i]["closing"]["groups"][g]
                        prior=politics[i]["opening"]["groups"][g]
                        group_exposures[g]+=int(prior["members"]>0)
                        inc["support_x_members"]+=current["members"]*current["support"]
                        inc["discontent_x_members"]+=current["members"]*current["discontent"]
                        pid=(i,g)
                        if pid in pending:
                            past=pending.pop(pid)
                            past["next_closing_support"]=current["support"]
                            events.writerow(past)
                            observed=summary[g,past["action"]]
                            observed["followup_weight"]+=past["participants"]
                            observed["weighted_followup_change"]+=past["participants"]*(current["support"]-past["pre_support"])
                        if not civic: continue
                        a=actions[i][g]
                        act=a["action"]
                        tracker=spells[pid]
                        done=tracker.observe(year,act,a["demand"])
                        if done:
                            summary[g,done[0]].update(completed=1,completed_duration=done[1])
                        if act not in TYPES: continue
                        if a["duration"]!=tracker.current: raise ValueError("independent episode duration mismatch")
                        reply=responses[owner]
                        project_targeted=(reply["before"]!=reply["after"] and reply["target_region"]==i
                                          and reply["target_group"]==g)
                        tax_targeted=(reply["legal_concession_permille"]>0 and reply["concession_region"]==i
                                      and reply["concession_group"]==g)
                        targeted=project_targeted or tax_targeted
                        event={"seed":seed,"year":year,"owner":owner,"region":i,"group":g,"action":act,
                               "demand":a["demand"],"duration":a["duration"],"demand_age":a["age"],"members":a["members"],
                               "participants":a["participants"],"withheld_workers":a["withheld_workers"],
                               "pre_support":a["support"],"pre_discontent":a["discontent"],"pre_pressure":a["pressure"],
                               "pre_shortage_permille":a["shortage_permille"],"pre_fiscal_burden":a["fiscal_burden"],
                               "pre_levy_value":a["levy_value"],"pre_food_unmet":politics[i]["opening"]["evidence"]["food_unmet"],
                               "closing_support":current["support"],"next_closing_support":None,
                               "answered":int(a["closing"]["answered"]),"response":reply["kind"],
                               "response_targeted":int(targeted),"project_targeted":int(project_targeted),
                               "tax_targeted":int(tax_targeted),"plan_changed":int(reply["before"]!=reply["after"]),
                               "food_output":prod["produced"]["food"],"food_need":need,"food_unmet":need-eaten,
                               **_goods(group_tax[g])}
                        _credit(summary[g,act],event)
                        inc.update(active_group_years=1,participant_years=a["participants"])
                        pending[pid]=event
                    places[i].update(inc)
                    if arm=="off":
                        ref[year,i]=(need,need-eaten,prod["produced"]["food"],funds[i]["relief_food"])
                    else:
                        base=ref[year,i]
                        diff=(need-eaten)-base[1]
                        kind="unmet_worse" if diff>0 else "unmet_better"
                        if abs(diff)>abs(extreme.get(kind,{}).get("delta",0)):
                            extreme[kind]={"seed":seed,"year":year,"kind":kind,"owner":owner,"region":i,"delta":diff,
                                "off_need":base[0],"off_unmet":base[1],"off_output":base[2],"off_relief":base[3],
                                "on_need":need,"on_unmet":need-eaten,"on_output":prod["produced"]["food"],
                                "on_relief":funds[i]["relief_food"],"withheld_workers":inc["withheld_workers"],
                                "refused_food":inc["refused_food"],"concession_food":inc["concession_food"]}
                for node in record["domestic"]["nodes"]:
                    nations[node["owner"]]["civil_freight_food"]+=node["cost_food"]
                for t in record["border_market"]["trades"]:
                    nations[rations[t["seller"]][0]]["border_freight_food"]+=t["cost_food"]
                for owner,account in accounts.items():
                    c=nations[owner]
                    c.setdefault("border_freight_food",0)
                    cab=cabinets[owner]
                    ballot=cab["election"]
                    tenures[owner].observe(year,cab["governing_faction"])
                    c.update(elections=int(ballot["election"]),installations=int(ballot["installation"]),
                             turnovers=int(ballot["turnover"]),economic_choice_changed=int(
                                 choice_key(recs[owner]["economic_choice"])!=choice_key(account["decision"])))
                    t=account["totals"]
                    c.update({k:t[k] for k in ("public_freight_food","public_spoil_food","collection_cost_food",
                                               "road_lost_units","effective_capacity","public_cargo")})
                    c.setdefault("responses_targeted",0)
                    c.setdefault("response_plan_changed",0)
                    c.setdefault("response_admin_used",0)
                    if civic:
                        reply=responses[owner]
                        kind=reply["kind"]
                        if kind not in RESPONSES: raise ValueError("unknown response")
                        ret=response_totals[kind]
                        changed=int(reply["before"]!=reply["after"])
                        ret.update(country_years=1,plan_changed=changed,posted_action_executed=t["action_executed"],
                                   petition_admin_used=reply["petition_admin_used"])
                        c.update(responses_targeted=int(kind!="maintain"),response_plan_changed=changed,
                                 response_admin_used=reply["petition_admin_used"])
                if year not in horizons: continue
                key={"seed":seed,"arm":arm,"year":year}
                by_country=defaultdict(Counter)
                for r in record["regions"]:
                    i,owner,close=r["id"],r["owner"],r["closing"]
                    stats={**places[i],"final_population":close["population"],"cash":close["cash"],
                           "farmland":close["farmland"],"soil_times_farmland":close["soil"]*close["farmland"]}
                    by_country[owner].update(stats)
                    data["regions"].append({**key,"region":i,"owner":owner,**stats,**_rates(stats)})
                total=Counter()
                for owner,a in accounts.items():
                    c={**by_country[owner],**nations[owner],**tenures[owner].snapshot(),
                       **{"public_stock_"+g:a["public_close"][g] for g in GOODS},
                       **{"private_stock_"+g:a["private_close"][g] for g in GOODS}}
                    c["world_freight_food"]=sum(c[k] for k in ("civil_freight_food","public_freight_food","border_freight_food"))
                    data["countries"].append({**key,"owner":owner,**c,**_rates(c)})
                    total.update({k:v for k,v in c.items() if k!="longest_observed_tenure"})
                    total["longest_observed_tenure"]=max(total["longest_observed_tenure"],c["longest_observed_tenure"])
                if total["cash"]!=initial_cash or initial_pop+total["births"]-total["deaths"]!=total["final_population"]:
                    raise ValueError("world cash or population balance failed")
                for g in GOODS:
                    private=stock[g]+total[g+"_output"]-total["sector_used_"+g]-total["meal_used_"+g]-total["paid_"+g]
                    public=total["paid_"+g]
                    if g=="food":
                        private+=total["relief_food"]-total["civil_freight_food"]-total["border_freight_food"]
                        public-=total["relief_food"]+total["public_freight_food"]+total["public_spoil_food"]+total["collection_cost_food"]
                    else: public-=total["works_"+g]
                    if (private,public)!=(total["private_stock_"+g],total["public_stock_"+g]):
                        raise ValueError("private and government stock identities failed")
                data["runs"].append({**key,"initial_sha256":init_sha,"initial_competition_sha256":init_5c,
                    "years_sha256":digest.hexdigest(),"initial_population":initial_pop,**total,**_rates(total),
                    "final_soil":_ratio(total["soil_times_farmland"],total["farmland"]),
                    "mean_support":_ratio(total["support_x_members"],total["food_need"]),
                    "mean_discontent":_ratio(total["discontent_x_members"],total["food_need"])})
                for g in GROUPS:
                    for act in TYPES:
                        c=summary[g,act]
                        current=[t.current for (i,group),t in spells.items() if group==g and t.action==act]
                        if c["started"]!=c["completed"]+len(current) or c["group_years"]!=c["completed_duration"]+sum(current):
                            raise ValueError("episode counts or exposure fail to reconcile")
                        data["actions"].append({**key,"group":g,"action":act,"eligible_group_years":group_exposures[g],
                            **{k:c[k] for k in ACTION_AMOUNTS},"open_spells":len(current),"open_duration":sum(current)})
                for kind in RESPONSES:
                    r=response_totals[kind]
                    data["responses"].append({**key,"response":kind,**{k:r[k] for k in (
                        "country_years","plan_changed","posted_action_executed","petition_admin_used")}})
            for e in pending.values(): events.writerow(e)
            data["cases"].extend(extreme.values())
    return data


def _event_archive(path,folder,seeds):
    with path.open("xb") as raw,gzip.GzipFile(filename="",fileobj=raw,mode="wb",compresslevel=6,mtime=0) as zipped:
        with io.TextIOWrapper(zipped,encoding="utf8",newline="") as f:
            csv.DictWriter(f,fieldnames=EVENT).writeheader()
            for s in seeds:
                with (folder/f"events-{s:03d}.csv").open(encoding="utf8",newline="") as source:
                    shutil.copyfileobj(source,f)


def run_study(output,*,sample,seeds=20,horizons=(50,100,200),workers=8,verify=None):
    output=Path(output)
    if os.path.lexists(output): raise FileExistsError(output)
    horizons=tuple(horizons)
    if (sample not in ("dev","holdout") or type(seeds) is not int or not 1<=seeds<=20 or not horizons
            or any(type(y) is not int or y<=0 for y in horizons) or len(set(horizons))!=len(horizons)
            or type(workers) is not int or workers<1): raise ValueError("invalid cohorts, horizons or workers")
    start=time.perf_counter()
    output.parent.mkdir(parents=True,exist_ok=True)
    first=0 if sample=="dev" else 20
    with TemporaryDirectory(dir=output.parent,prefix=".collective-") as temp:
        stage=Path(temp,"result")
        stage.mkdir()
        jobs=[(s,horizons,temp) for s in range(first,first+seeds)]
        if workers==1: result=list(map(_seed,jobs))
        else:
            with ProcessPoolExecutor(max_workers=min(workers,seeds)) as pool: result=list(pool.map(_seed,jobs))
        tables={k:[r for item in result for r in item[k]] for k in result[0]}
        runs=tables["runs"]
        lookup={(r["seed"],r["arm"],r["year"]):r for r in runs}
        archive={(int(r["seed"]),int(r["year"])):r for r in _read(ARCHIVE/sample/"runs.csv") if r["arm"]=="C"}
        matched=0
        paired=[]
        for r in runs:
            seed,arm,y=r["seed"],r["arm"],r["year"]
            base=lookup[seed,"off",y]
            if base["initial_sha256"]!=r["initial_sha256"]: raise ValueError("unmatched collective starting states")
            if arm=="off" and y in (50,100,200):
                old=archive[seed,y]
                if (r["initial_competition_sha256"]!=old["initial_sha256"] or r["years_sha256"]!=old["years_sha256"]):
                    raise ValueError(f"historical 5C C path mismatch at {seed}, {y}")
                matched+=1
            if arm=="on": paired.append({"seed":seed,"year":y,**{"delta_"+k:r[k]-base[k] for k in DELTAS}})
        means=[]
        for arm in ARMS:
            for y in horizons:
                g=[r for r in runs if r["arm"]==arm and r["year"]==y]
                sums=Counter()
                for r in g: sums.update({k:v for k,v in r.items() if isinstance(v,(int,float))})
                means.append({"arm":arm,"year":y,"seeds":len(g),
                              **{k:fmean(r[k] for r in g) for k in sums if k not in ("seed","year")},
                              **{"pooled_"+k:v for k,v in _rates(sums).items()}})
        _event_archive(stage/"events.csv.gz",Path(temp),range(first,first+seeds))
        for name in ("runs","countries","regions","actions","responses"): _write(stage/(name+".csv"),tables[name])
        _write(stage/"means.csv",means)
        _write(stage/"paired.csv",paired)
        _json(stage/"cases.json",tables["cases"])
        manifest={}
        for p in sorted(stage.iterdir()):
            b=p.read_bytes()
            manifest[p.name]=hashlib.sha256(b).hexdigest()
            if verify and (Path(verify)/p.name).read_bytes()!=b: raise ValueError("replay differs in "+p.name)
        meta={"sample":sample,"first_seed":first,"seeds":seeds,"workers":min(workers,seeds),"horizons":horizons,
              "paths":seeds*2,"annual_transitions":seeds*2*max(horizons),"archived_5c_checkpoints":matched,
              "replayed_checkpoints":len(runs) if verify else 0,"table_sha256":manifest,"python":platform.python_version(),
              "wall_seconds":time.perf_counter()-start}
        _json(stage/"execution.json",meta)
        if os.path.lexists(output): raise FileExistsError(output)
        stage.rename(output)
    return meta


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out",required=True,type=Path)
    p.add_argument("--sample",required=True,choices=("dev","holdout"))
    p.add_argument("--seeds",type=int,default=20)
    p.add_argument("--workers",type=int,default=8)
    p.add_argument("--horizons",default="50,100,200")
    p.add_argument("--verify-against",type=Path)
    args=p.parse_args()
    print(json.dumps(run_study(args.out,sample=args.sample,seeds=args.seeds,workers=args.workers,
                               horizons=tuple(int(y) for y in args.horizons.split(",")),verify=args.verify_against)))


if __name__=="__main__": main()
