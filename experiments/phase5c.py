"""Five matched electoral and fiscal policies, with a 5.0B control and paid-budget audits."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import platform
from statistics import fmean
from tempfile import TemporaryDirectory
import time

from civsim.model import GOODS, generate_world
from civsim.regions import regionalize
from civsim.storage import canonical_line
from experiments.capacity5 import RoadCapacityAudit
from experiments.phase5a import _rates, _ratio, _read, _sha, _write, disparity
from experiments.phase5b import _allocations, choice_key


ARMS = {"A":("A","fixed"),"B":("B","fixed"),"C":("C","fixed"),"D":("D","fixed"),"E":("C","platform")}
REFERENCE = {"B":"A","C":"B","D":"C","E":"C"}
GROUPS = ("farm","industry","consumer")
ACTIONS = ("relief","road","soil","reserve","defer","none")
FACTIONS = ("stewards","builders","mutualists","restraint")
ARCHIVE = Path(__file__).resolve().parents[1]/"examples/phase5b/study"
DELTAS = ("final_population","food_deficit","food_need","deficit_share","within_country_ration_disparity",
          "regional_ration_disparity","food_output","final_soil","different_pair_share","active_different_pair_share",
          "turnovers","paid_negative_projects","levied_food","public_stock_food","private_stock_food",
          "relief_food","road_built","soil_projects","total_freight_food")


class DemandProfile:
    def __init__(self):
        self.pairs = Counter(pairs=0, different=0, active_pairs=0, active_different=0)
        self.member_years = defaultdict(Counter)

    def observe(self, groups):
        live = [g for g in GROUPS if groups[g]["members"]>0]
        for j, g in enumerate(live):
            choice = groups[g]["demand"]
            self.member_years[g][choice] += groups[g]["members"]
            for other in live[j+1:]:
                second = groups[other]["demand"]
                self.pairs["pairs"] += 1
                self.pairs["different"] += int(choice!=second)
                if choice!="none" and second!="none":
                    self.pairs["active_pairs"] += 1
                    self.pairs["active_different"] += int(choice!=second)

    def summary(self, key):
        rows=[]
        for g in GROUPS:
            counts=self.member_years[g]
            count=sum(counts.values())
            active=count-counts["none"]
            shares=[n/active for a,n in counts.items() if a!="none" and n]
            rows.append({**key,"group":g,"member_years":count,"expressed_member_years":active,
                         **{a:counts[a] for a in ACTIONS},"expressed_hhi":sum(p*p for p in shares) if active else None,
                         "expressed_entropy_bits":-sum(p*math.log2(p) for p in shares) if active else None})
        return rows


class Tenure:
    def __init__(self):
        self.party = "caretaker"
        self.spell = 0
        self.finished = []
        self.last_year = 0

    def observe(self, year, party):
        if year != self.last_year+1:
            raise ValueError("tenure requires consecutive years")
        if party != self.party:
            if self.spell:
                self.finished.append(self.spell)
            self.party, self.spell = party, 0
        if party != "caretaker":
            self.spell += 1
        self.last_year = year

    def snapshot(self):
        return {"completed_spells":len(self.finished),"completed_tenure_years":sum(self.finished),
                "open_spells":int(self.spell>0),"open_tenure_years":self.spell,
                "longest_observed_tenure":max([self.spell,*self.finished])}


def _spending(government):
    """Only the current discretionary order; mandatory maintenance is a separate appropriation."""
    out={a["id"]:Counter(food_delivered=0, freight_food=0, works_ore=0,works_tools=0,workers=0,
                         extra_levy_food=0,handling_food=0) for a in government["accounts"]}
    for w in government["works"]["projects"]:
        if w["action"]!="service":
            out[w["owner"]].update(works_ore=w["used"]["ore"],works_tools=w["used"]["tools"],workers=w["workers"])
    for s in government["works"]["shipments"]:
        if s["purpose"]!="service":
            out[s["owner"]]["freight_food"]+=s["cost_food"]
    for s in government["relief"]["shipments"]:
        out[s["owner"]].update(food_delivered=s["quantity"],freight_food=s["cost_food"])
    for l in government["levies"]:
        out[l["owner"]].update(extra_levy_food=l["extra_levy"]["food"],handling_food=l["handling_used"]["food"])
    return out


def _occupancy(c):
    return {"different_pair_share":_ratio(c["different"],c["pairs"]),
            "active_different_pair_share":_ratio(c["active_different"],c["active_pairs"])}


def _json(path,data):
    path.write_text(json.dumps(data,indent=2,ensure_ascii=False)+"\n",encoding="utf8",newline="\n")


def _descriptor(choice):
    return {"action":choice["action"],"region":choice["target_region"],
            "edge":"-".join(map(str,choice["target_edge"] or []))}


ELECTION_FIELDS = ("seed","arm","year","owner","prior_party","new_party","installation","turnover",
                   "eligible_points","participation_points","abstention_points","outgoing_action","outgoing_region",
                   "outgoing_edge","selected_action","selected_region","selected_edge","choice_changed",
                   *("votes_"+f for f in FACTIONS),*("seats_"+f for f in FACTIONS))
NEGATIVE_FIELDS = ("seed","arm","year","owner","party","economic_score","action","region","edge","executed",
                   "food_delivered","freight_food","works_ore","works_tools","workers","extra_levy_food","handling_food")


def _election(year,key,cab,account,totals,parties,events):
    trace=cab["election"]
    leader=cab["governing_faction"]
    if trace is None:
        return
    for f in FACTIONS:
        parties[f]["incumbent_years"]+=int(leader==f)
        parties[f]["support_vote_points"]+=trace["vote_points"][f]
        parties[f]["participation_points"]+=trace["participation_points"]
    if sum(trace["vote_points"].values())!=trace["participation_points"]:
        raise ValueError("party support points differ from participation")
    if not trace["election"]:
        return
    selected=_descriptor(account["decision"])
    prior=cab["outgoing_choice"]
    changed=prior is not None and choice_key(prior)!=choice_key(account["decision"])
    totals.update(elections=1,zero_participation_elections=int(trace["participation_points"]==0),
                  installations=int(trace["installation"]),turnovers=int(trace["turnover"]),
                  turnover_choice_changes=int(trace["turnover"] and changed))
    for f in FACTIONS:
        parties[f].update(ballot_vote_points=trace["vote_points"][f],ballot_participation=trace["participation_points"],
                          seats_awarded=trace["seats"][f],elections_won=int(leader==f and trace["participation_points"]>0))
    old=_descriptor(prior) if prior is not None else {"action":"","region":None,"edge":""}
    events.append({**key,"year":year,"owner":cab["id"],"prior_party":trace["previous_incumbent"],"new_party":leader,
                   "installation":int(trace["installation"]),"turnover":int(trace["turnover"]),
                   **{k:trace[k] for k in ("eligible_points","participation_points","abstention_points")},
                   **{"outgoing_"+k:v for k,v in old.items()},**{"selected_"+k:v for k,v in selected.items()},
                   "choice_changed":int(changed) if prior is not None else None,
                   **{"votes_"+f:trace["vote_points"][f] for f in FACTIONS},
                   **{"seats_"+f:trace["seats"][f] for f in FACTIONS}})


def _seed(job):
    from civsim.competition import competition_snapshot, start_competition, step_competition
    seed, horizons=job
    data={k:[] for k in ("runs","countries","regions","preferences","parties","elections","negative","cases")}
    references={}
    for arm,(mode,tax) in ARMS.items():
        world=regionalize(generate_world(seed))
        sim=start_competition(world)
        initial=competition_snapshot(sim)
        initial_sha=_sha(initial)
        political_sha=_sha(initial["political"])
        digest,projection=hashlib.sha256(),hashlib.sha256()
        capacity=RoadCapacityAudit(world)
        initial_stock={g:sum(r.stock[g] for r in world.regions) for g in GOODS}
        initial_pop=sum(r.population for r in world.regions)
        initial_cash=sum(r.cash for r in world.regions)
        key={"seed":seed,"arm":arm}
        prefs=DemandProfile()
        regions,countries=defaultdict(Counter),defaultdict(Counter)
        tenures=defaultdict(Tenure)
        party=defaultdict(lambda:defaultdict(Counter))
        last_policy={}
        examples={}
        worst=0
        for year in range(1,max(horizons)+1):
            record=step_competition(sim,year,mode,tax_policy=tax)
            digest.update(canonical_line(record))
            if arm=="A":
                projection.update(canonical_line({k:v for k,v in record.items() if k!="competition"}))
            physical=capacity.observe(record)
            competition=record["competition"]
            gov=record["government"]
            accounts={a["id"]:a for a in gov["accounts"]}
            recommendations={r["id"]:r["recommendation"] for r in record["politics"]["countries"]}
            states={r["id"]:r["closing"]["groups"] for r in record["politics"]["regions"]}
            spending=_spending(gov)
            allocations=_allocations(record)
            rations={r["id"]:(r["owner"],r["consumption"]["food_need"],r["consumption"]["food_eaten"])
                     for r in record["regions"]}
            between,within=disparity(rations)
            for r in record["regions"]:
                i=r["id"]
                owner,need,eaten=rations[i]
                prefs.observe(states[i])
                p,m=r["production"],r["consumption"]
                crops=p["produced"]
                regions[i].update({"food_need":need,"food_eaten":eaten,"food_deficit":need-eaten,
                                   "absolute_world_ration_gap":between[i],"absolute_national_ration_gap":within[i],
                                   "births":r["demography"]["births"],"deaths":r["demography"]["deaths"],
                                   **{g+"_output":crops[g] for g in GOODS},
                                   **{"sector_used_"+g:p["used"][g] for g in GOODS},
                                   **{"meal_used_"+g:m["used"][g] for g in GOODS},**allocations[i]})
                current={"need":need,"unmet":need-eaten,"food_output":crops["food"],
                         "levied_food":allocations[i]["levied_food"],"relief_food":allocations[i]["relief_food"]}
                if arm in ("A","B","C"): references[arm,year,i]=current
                if arm in REFERENCE:
                    base=references[REFERENCE[arm],year,i]
                    adverse=current["unmet"]-base["unmet"]
                    if adverse>worst:
                        worst=adverse
                        examples["adverse"]={**key,"kind":"largest_regional_unmet_increase","year":year,
                                             "region":i,"owner":owner,"reference_arm":REFERENCE[arm],
                                             "reference":base,"actual":current}
            for node in record["domestic"]["nodes"]:
                countries[node["owner"]]["civil_freight_food"]+=node["cost_food"]
            for owner in accounts:
                countries[owner].setdefault("border_freight_food",0)
            for s in record["border_market"]["trades"]:
                countries[rations[s["seller"]][0]]["border_freight_food"]+=s["cost_food"]
            for cab in competition["countries"]:
                owner=cab["id"]
                a=accounts[owner]
                agg=countries[owner]
                for k in ("elections","zero_participation_elections","installations","turnovers","turnover_choice_changes","negative_projects",
                          "paid_negative_projects","zero_score_projects","paid_zero_score_projects"):
                    agg.setdefault(k,0)
                tenures[owner].observe(year,cab["governing_faction"])
                _election(year,key,cab,a,agg,party[owner],data["elections"])
                t=a["totals"]
                paid=t["action_executed"]
                plan=a["decision"]
                selected=choice_key(plan)
                original=choice_key(recommendations[owner]["economic_choice"])
                prior=last_policy.get(owner)
                agg.update(economic_choice_changes=int(original!=selected),
                           economic_action_changes=int(original[0]!=selected[0]),
                           economic_target_changes=int(original[0]==selected[0] and original!=selected),
                           year_pairs=int(prior is not None),year_to_year_choice_changes=int(prior is not None and prior!=selected),
                           year_to_year_action_changes=int(prior is not None and prior[0]!=selected[0]))
                last_policy[owner]=selected
                score=plan["selected_score"]
                negative=plan["action"]!="defer" and score<0
                zero=plan["action"]!="defer" and score==0
                agg.update(negative_projects=int(negative),paid_negative_projects=int(negative)*paid,
                           zero_score_projects=int(zero),paid_zero_score_projects=int(zero)*paid,
                           public_freight_food=t["public_freight_food"],public_spoil_food=t["public_spoil_food"],
                           collection_cost_food=t["collection_cost_food"],all_works_ore=t["works_ore"],
                           all_works_tools=t["works_tools"])
                for f in (*FACTIONS,"caretaker"):
                    agg["tariff_years_"+f]+=int(cab["tariff"]==f)
                faction=cab["governing_faction"]
                if faction in FACTIONS:
                    pf=party[owner][faction]
                    pf["plans_"+plan["action"]]+=1
                    pf["executed_"+plan["action"]]+=paid
                    pf["paid_negative_projects"]+=int(negative and paid)
                costs=spending[owner]
                for k,v in costs.items():
                    agg["negative_"+k]+= v if negative else 0
                if negative or zero:
                    data["negative"].append({**key,"year":year,"owner":owner,"party":cab["governing_faction"],
                        "economic_score":score,**_descriptor(plan),"executed":paid,**costs})
                if negative and paid and "negative" not in examples:
                    examples["negative"]={**key,"kind":"first_paid_negative","year":year,"owner":owner,
                        "party":cab["governing_faction"],"economic_score":score,"choice":_descriptor(plan),
                        "budget":plan["budget"],"actual":dict(costs)}
            if year not in horizons: continue
            tag={**key,"year":year}
            group=prefs.summary(tag)
            data["preferences"].extend(group)
            local=defaultdict(Counter)
            for r in record["regions"]:
                i,owner,close=r["id"],r["owner"],r["closing"]
                c={**regions[i],"final_population":close["population"],"cash":close["cash"],"farmland":close["farmland"],
                   "soil_x_farmland":close["farmland"]*close["soil"]}
                local[owner].update(c)
                data["regions"].append({**tag,"region":i,"owner":owner,**c,**_rates(c)})
            total=Counter()
            for owner,a in accounts.items():
                c={**local[owner],**countries[owner],**physical[owner],**tenures[owner].snapshot(),
                   **{"private_stock_"+g:a["private_close"][g] for g in GOODS},
                   **{"public_stock_"+g:a["public_close"][g] for g in GOODS},
                   **{"combined_stock_"+g:a["combined_close"][g] for g in GOODS}}
                c["total_freight_food"]=sum(c[k] for k in ("civil_freight_food","border_freight_food","public_freight_food"))
                data["countries"].append({**tag,"owner":owner,**c,**_rates(c),
                    "current_leader":tenures[owner].party,"final_soil":_ratio(c["soil_x_farmland"],c["farmland"])})
                total.update({k:v for k,v in c.items() if k!="longest_observed_tenure"})
                total["longest_observed_tenure"]=max(total["longest_observed_tenure"],c["longest_observed_tenure"])
                total["installed_no_turnover_countries"]+=int(c["installations"]>0 and c["turnovers"]==0)
                for f in FACTIONS:
                    pf=party[owner][f]
                    data["parties"].append({**tag,"owner":owner,"faction":f,
                        **{k:pf[k] for k in ("incumbent_years","support_vote_points","participation_points",
                                             "ballot_vote_points","ballot_participation","seats_awarded","elections_won",
                                             "paid_negative_projects",*("plans_"+act for act in ACTIONS[:-1]),
                                             *("executed_"+act for act in ACTIONS[:-1]))}})
            for g in GOODS:
                converted=(total["food_output"] if g=="food" else total[g+"_output"])-total["sector_used_"+g]
                private=initial_stock[g]+converted-total["meal_used_"+g]-total["levied_"+g]
                public=total["levied_"+g]
                if g=="food":
                    private+=total["relief_food"]-total["civil_freight_food"]-total["border_freight_food"]
                    public-=sum(total[k] for k in ("relief_food","public_freight_food","public_spoil_food","collection_cost_food"))
                else:
                    public-=total["all_works_"+g]
                if (private!=total["private_stock_"+g] or public!=total["public_stock_"+g]
                        or private+public!=total["combined_stock_"+g]):
                    raise ValueError(f"private/public stock identity failed, seed {seed}, arm {arm}, year {year}, {g}")
            if (sum(x["member_years"] for x in group)!=total["food_need"] or total["cash"]!=initial_cash
                    or initial_pop+total["births"]-total["deaths"]!=total["final_population"]):
                raise ValueError("group, cash or population mismatch")
            total.update(prefs.pairs)
            data["runs"].append({**tag,"engine_arm":mode,"tax_policy":tax,"initial_sha256":initial_sha,
                "initial_political_sha256":political_sha,"years_sha256":digest.hexdigest(),
                "political_sha256":projection.hexdigest() if arm=="A" else "",
                "initial_population":initial_pop,"initial_cash":initial_cash,**{"initial_stock_"+g:v for g,v in initial_stock.items()},
                **total,**_rates(total),**_occupancy(total),"final_soil":_ratio(total["soil_x_farmland"],total["farmland"])})
        data["cases"].extend(examples.values())
    return data


def run_study(output,*,sample,seeds=20,horizons=(50,100,200),workers=8,verify=None):
    output=Path(output)
    if os.path.lexists(output): raise FileExistsError(output)
    horizons=tuple(horizons)
    if (sample not in ("dev","holdout") or type(seeds) is not int or not 1<=seeds<=20
            or not horizons or any(type(y) is not int or y<=0 for y in horizons)
            or len(horizons)!=len(set(horizons)) or type(workers) is not int or workers<1):
        raise ValueError("expected dev/holdout, positive unique horizons and workers, 1..20 seeds")
    first=0 if sample=="dev" else 20
    jobs=[(s,horizons) for s in range(first,first+seeds)]
    start=time.perf_counter()
    output.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=output.parent,prefix=".competition-") as temp:
        stage=Path(temp,"result")
        stage.mkdir()
        if workers==1: results=list(map(_seed,jobs))
        else:
            with ProcessPoolExecutor(max_workers=min(seeds,workers)) as pool:
                results=list(pool.map(_seed,jobs))
        tables={k:[row for r in results for row in r[k]] for k in results[0]}
        runs=tables["runs"]
        lookup={(r["seed"],r["arm"],r["year"]):r for r in runs}
        archive={(int(r["seed"]),int(r["year"])):r for r in _read(ARCHIVE/sample/"runs.csv") if r["arm"]=="on"}
        matched=0
        paired=[]
        for r in runs:
            seed,arm,year=r["seed"],r["arm"],r["year"]
            a=lookup[seed,"A",year]
            if a["initial_sha256"]!=r["initial_sha256"] or a["initial_political_sha256"]!=r["initial_political_sha256"]:
                raise ValueError("unmatched political or economic starting state")
            if arm=="A" and year in (50,100,200):
                old=archive[seed,year]
                if (old["years_sha256"]!=r["political_sha256"]
                        or old["initial_political_sha256"]!=r["initial_political_sha256"]):
                    raise ValueError(f"5B on archive mismatch seed {seed}, year {year}")
                matched+=1
            if arm in REFERENCE:
                b=lookup[seed,REFERENCE[arm],year]
                paired.append({"seed":seed,"arm":arm,"reference":REFERENCE[arm],"year":year,
                               **{"delta_"+k:r[k]-b[k] for k in DELTAS}})
        means=[]
        for arm in ARMS:
            for y in horizons:
                group=[r for r in runs if r["arm"]==arm and r["year"]==y]
                totals=Counter()
                for r in group: totals.update({k:v for k,v in r.items() if isinstance(v,(int,float))})
                means.append({"arm":arm,"year":y,"seeds":len(group),
                    **{k:fmean(r[k] for r in group) for k in totals if k not in ("seed","year")},
                    **{"pooled_"+k:v for k,v in {**_rates(totals),**_occupancy(totals)}.items()}})
        for name in ("runs","countries","regions","preferences","parties"):
            _write(stage/(name+".csv"),tables[name])
        for name,fields in (("elections",ELECTION_FIELDS),("negative",NEGATIVE_FIELDS)):
            with (stage/(name+".csv")).open("x",encoding="utf8",newline="") as stream:
                writer=csv.DictWriter(stream,fieldnames=fields)
                writer.writeheader()
                writer.writerows(tables[name])
        _write(stage/"paired.csv",paired)
        _write(stage/"means.csv",means)
        _json(stage/"cases.json",tables["cases"])
        manifest={}
        for path in sorted(stage.iterdir()):
            blob=path.read_bytes()
            manifest[path.name]=hashlib.sha256(blob).hexdigest()
            if verify is not None and (Path(verify)/path.name).read_bytes()!=blob:
                raise ValueError("independent replay mismatch in "+path.name)
        meta={"sample":sample,"first_seed":first,"seeds":seeds,"workers":min(seeds,workers),"horizons":horizons,
              "python":platform.python_version(),"paths":seeds*len(ARMS),"annual_transitions":seeds*len(ARMS)*max(horizons),
              "archived_5b_checkpoints":matched,"replayed_checkpoints":len(runs) if verify is not None else 0,
              "table_sha256":manifest,"wall_seconds":time.perf_counter()-start}
        _json(stage/"execution.json",meta)
        if os.path.lexists(output): raise FileExistsError(output)
        stage.rename(output)
    return meta


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out",required=True,type=Path)
    p.add_argument("--sample",required=True,choices=("dev","holdout"))
    p.add_argument("--seeds",type=int,default=20)
    p.add_argument("--horizons",default="50,100,200")
    p.add_argument("--workers",type=int,default=8)
    p.add_argument("--verify-against",type=Path)
    args=p.parse_args()
    try:
        meta=run_study(args.out,sample=args.sample,seeds=args.seeds,horizons=tuple(int(y) for y in args.horizons.split(",")),
                       workers=args.workers,verify=args.verify_against)
    except (ValueError,OSError) as error:
        p.exit(1,f"{p.prog}: {error}\n")
    print(json.dumps(meta))


if __name__=="__main__":
    main()
