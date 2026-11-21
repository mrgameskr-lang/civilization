"""Matched 5.0B political feedback paths and archived 5.0A integrated-policy controls."""
import argparse
import csv
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import platform
from statistics import fmean
from tempfile import TemporaryDirectory
import time

from civsim.government import fiscal_snapshot, start_government
from civsim.model import GOODS, generate_world
from civsim.regions import regionalize
from civsim.storage import canonical_line
from experiments.capacity5 import RoadCapacityAudit
from experiments.phase5a import _rates, _ratio, _read, _sha, _write, disparity


ARMS = ("off", "on")
GROUPS = ("farm", "industry", "consumer")
ACTIONS = ("relief", "road", "soil", "reserve", "defer", "none")
INDICES = ("support", "discontent")
ARCHIVE = Path(__file__).resolve().parents[1] / "examples/phase5/study"
DELTAS = ("final_population", "food_need", "food_deficit", "deficit_share", "regional_ration_disparity",
          "within_country_ration_disparity", "food_output", "mean_support", "mean_discontent", "demand_share",
          "persistent_demand_share", "relief_food", "road_built", "soil_projects", "public_labor",
          "levied_food", "actual_switches", "final_cash_hhi", "final_soil", "year_effective_capacity",
          "next_year_effective_capacity", "civil_freight_food", "public_freight_food", "border_freight_food")
FILES = ("runs", "countries", "regions", "groups", "regional_groups", "distributions", "demands")
SWITCH_FIELDS = ("seed", "arm", "year", "owner", "economic_action", "economic_region", "economic_edge",
                 "recommended_action", "recommended_region", "recommended_edge", "old_economic_score",
                 "new_economic_score", "old_political_score", "new_political_score", "adopted", "action_executed")


def choice_key(choice):
    return choice["action"], choice["target_region"], tuple(choice["target_edge"] or ())


def band(value):
    if type(value) is not int or not 0 <= value <= 1000:
        raise ValueError("political index outside 0..1000")
    return min(9, value // 100) * 100


def _weighted(c):
    people = c["member_years"]
    return {"mean_support": _ratio(c["support_x_members"], people),
            "mean_discontent": _ratio(c["discontent_x_members"], people),
            "mean_pressure": _ratio(c["pressure_x_members"], people),
            "mean_benefit": _ratio(c["benefit_x_members"], people),
            "mean_burden": _ratio(c["burden_x_members"], people),
            "demand_share": _ratio(c["demand_member_years"], people),
            "persistent_demand_share": _ratio(c["persistent_demand_member_years"], people)}


class PoliticalMeasures:
    def __init__(self):
        self.groups = defaultdict(Counter)
        self.hist = defaultdict(Counter)
        self.demands = defaultdict(Counter)

    def observe(self, groups, need):
        counts = Counter()
        if set(groups) != set(GROUPS) or sum(g["members"] for g in groups.values()) != need:
            raise ValueError("class membership differs from paid annual rations exposure")
        for name, g in groups.items():
            n, age, request = g["members"], g["age"], g["demand"]
            if request not in ACTIONS or (request == "none") != (age == 0):
                raise ValueError("invalid demand age or action")
            change = {"member_years": n, "support_x_members": n*g["support"],
                      "discontent_x_members": n*g["discontent"],
                      "pressure_x_members": n*g["pressure"], "benefit_x_members": n*g["benefit"],
                      "burden_x_members": n*g["burden"],
                      "demand_member_years": n * int(request != "none"),
                      "persistent_demand_member_years": n * int(age >= 2)}
            self.groups[name].update(change)
            counts.update(change)
            for index in INDICES:
                self.hist[name, index, band(g[index])].update(
                    {"member_years": n, "nonempty_group_years": int(n > 0)})
            d = self.demands[name, request]
            d.update({"member_years": n, "nonempty_group_years": int(n > 0),
                      "persistent_member_years": n * int(age >= 2), "age_x_members": n*age})
            d["max_age"] = max(d["max_age"], age if n else 0)
        return counts

    def snapshot(self, key):
        groups = [{**key, "group":g, **self.groups[g], **_weighted(self.groups[g])} for g in GROUPS]
        hist, demands = [], []
        for g in GROUPS:
            for index in INDICES:
                for lower in range(0,1000,100):
                    h = self.hist[g,index,lower]
                    hist.append({**key, "group":g, "index":index, "lower":lower,
                                 "upper":lower+99 if lower<900 else 1000, "member_years":h["member_years"],
                                 "nonempty_group_years":h["nonempty_group_years"]})
            for request in ACTIONS:
                d = self.demands[g,request]
                demands.append({**key, "group":g, "demand":request,
                                **{k:d[k] for k in ("member_years","nonempty_group_years","persistent_member_years",
                                                   "age_x_members","max_age")}})
        return groups, hist, demands


def _allocations(record):
    out = {r["id"]: Counter({"road_built":0, "road_endpoint_units":0, "road_service":0, "soil_projects":0,
                             "public_labor":0, "works_ore":0, "works_tools":0, "relief_food":0})
           for r in record["regions"]}
    gov = record["government"]
    for l in gov["levies"]:
        out[l["region"]].update({"levied_" + g: l["levied"][g] for g in GOODS})
    for s in gov["relief"]["shipments"]:
        out[s["target"]]["relief_food"] += s["quantity"]
    for p in gov["works"]["projects"]:
        out[p["target"]].update({{"build":"road_built","service":"road_service","soil":"soil_projects"}[p["action"]]:1,
                                 "public_labor":p["workers"], "works_ore":p["used"]["ore"],
                                 "works_tools":p["used"]["tools"]})
        if p["action"] == "build":
            for i in p["edge"]:
                out[i]["road_endpoint_units"] += 1
    return out


def _select_case(seed, year, owner, rec, fiscal, opening, allocations):
    e, p = rec["economic_choice"], rec["political_choice"]
    selected = {choice_key(e),choice_key(p)}
    return {"seed":seed, "year":year, "owner":owner, "economic_choice":e, "political_choice":p,
            "candidate_scores":[c for c in rec["candidates"] if choice_key(c) in selected],
            "previous_groups":[{"region":i,"groups":o["groups"]} for i,o in opening.items() if o["owner"]==owner],
            "action_executed":fiscal["totals"]["action_executed"],
            "allocations":[{"region":i,**a} for i,a in allocations.items() if opening[i]["owner"]==owner]}


def _seed(job):
    from civsim.politics import political_snapshot, start_political, step_political
    seed, horizons = job
    baseline = {}
    rows = {k:[] for k in (*FILES, "cases", "switches")}
    for arm in ARMS:
        world = regionalize(generate_world(seed))
        regional_hash = _sha(asdict(world))
        fiscal_hash = _sha(fiscal_snapshot(start_government(world)))
        sim = start_political(world)
        road_audit = RoadCapacityAudit(world)
        initial = _sha(political_snapshot(sim))
        population = sum(n.population for n in world.nations)
        cash = sum(n.cash for n in world.nations)
        digest, fiscal_digest = hashlib.sha256(), hashlib.sha256()
        political = PoliticalMeasures()
        regions, countries = defaultdict(Counter), defaultdict(Counter)
        evidence, extremes = {}, {}
        for year in range(1,max(horizons)+1):
            record = step_political(sim, year, arm == "on")
            physical = road_audit.observe(record)
            digest.update(canonical_line(record))
            fiscal_digest.update(canonical_line({k:v for k,v in record.items() if k != "politics"}))
            pol = record["politics"]
            rations = {r["id"]:(r["owner"],r["consumption"]["food_need"],r["consumption"]["food_eaten"])
                       for r in record["regions"]}
            world_gap, within_gap = disparity(rations)
            allocations = _allocations(record)
            observations = {r["id"]:r for r in pol["regions"]}
            for r in record["regions"]:
                i = r["id"]
                owner, need, eaten = rations[i]
                gap = need - eaten
                counts = political.observe(observations[i]["closing"]["groups"], need)
                regions[i].update(counts)
                regions[i].update(allocations[i])
                regions[i].update({"food_need":need,"food_eaten":eaten,"food_deficit":gap,
                                   "absolute_world_ration_gap":world_gap[i],"absolute_national_ration_gap":within_gap[i],
                                   "shortage_region_years":int(gap>0),"births":r["demography"]["births"],
                                   "deaths":r["demography"]["deaths"],
                                   **{g+"_output":r["production"]["produced"][g] for g in GOODS}})
                if arm == "off":
                    baseline[year,i] = (need, gap, allocations[i]["relief_food"], allocations[i]["soil_projects"],
                                        allocations[i]["road_built"])
                else:
                    ref = baseline[year,i]
                    diff = gap-ref[1]
                    kind = "more_unmet" if diff>0 else "less_unmet"
                    if abs(diff)>extremes.get(kind,0):
                        extremes[kind] = abs(diff)
                        evidence[kind] = {"kind":kind,"seed":seed,"year":year,"owner":owner,"region":i,
                            "off":dict(zip(("food_need","food_deficit","relief_food","soil_projects","road_built"),ref)),
                            "on":{"food_need":need,"food_deficit":gap,**allocations[i]},
                            "on_opening_groups":observations[i]["opening"]["groups"]}
            accounts = {a["id"]:a for a in record["government"]["accounts"]}
            for owner in accounts:
                countries[owner].setdefault("border_freight_food", 0)
            for t in record["border_market"]["trades"]:
                countries[rations[t["seller"]][0]]["border_freight_food"] += t["cost_food"]
            for n in record["domestic"]["nodes"]:
                countries[n["owner"]]["civil_freight_food"] += n["cost_food"]
            for n in pol["countries"]:
                owner, rec = n["id"], n["recommendation"]
                acc = accounts[owner]
                econ, alternate, actual = (choice_key(x) for x in (
                    rec["economic_choice"],rec["political_choice"],acc["decision"]))
                changed = econ != alternate
                if bool(rec["changed"])!=changed or actual!=(alternate if arm=="on" else econ):
                    raise ValueError("posted fiscal decision differs from experiment arm")
                if changed:
                    before, after = rec["economic_choice"], rec["political_choice"]
                    rows["switches"].append(dict(zip(SWITCH_FIELDS, (
                        seed,arm,year,owner,econ[0],econ[1],"-".join(map(str,econ[2])),
                        alternate[0],alternate[1],"-".join(map(str,alternate[2])),
                        before["economic_score"],after["economic_score"],before["political_score"],
                        after["political_score"],int(arm=="on"),acc["totals"]["action_executed"]),strict=True)))
                c = countries[owner]
                constrained = [(row, raw) for row,raw in zip(rec["candidates"],acc["decision"]["candidates"],strict=True)
                               if row["political_score"]>0 and not row["eligible"] and raw["constraints"]]
                c["country_years_constrained_demand"] += int(bool(constrained))
                c["constrained_demand_candidates"] += len(constrained)
                if arm=="on" and constrained and "first_constrained_demand" not in evidence:
                    blocked, raw = max(constrained,key=lambda x:x[0]["political_score"])
                    evidence["first_constrained_demand"] = {"kind":"first_constrained_demand","seed":seed,
                        "year":year,"owner":owner,"chosen":rec["political_choice"],"blocked_candidate":blocked,
                        "constraints":raw["constraints"],"fiscal_inputs":raw["inputs"]}
                c.update({"decision_years":1,"recommended_switches":int(changed),
                          "actual_switches":int(actual!=econ),"action_switches":int(actual[0]!=econ[0]),
                          "target_only_switches":int(actual[0]==econ[0] and actual!=econ),
                          "executed_switches":int(actual!=econ)*acc["totals"]["action_executed"],
                          "public_freight_food":acc["totals"]["public_freight_food"],
                          "public_spoil_food":acc["totals"]["public_spoil_food"]})
                for action in ACTIONS[:-1]:
                    c["plans_"+action] += int(actual[0]==action)
                if arm=="on" and changed:
                    kind="first_action_switch" if actual[0]!=econ[0] else "first_target_switch"
                    if kind not in evidence:
                        previous = {i:r["opening"] for i,r in observations.items()}
                        evidence[kind] = {"kind":kind,**_select_case(seed,year,owner,rec,acc,previous,allocations)}
            if year not in horizons:
                continue
            key = {"seed":seed,"arm":arm,"year":year}
            local = defaultdict(Counter)
            for r in record["regions"]:
                i,owner,close = r["id"],r["owner"],r["closing"]
                summary = {**regions[i],"final_population":close["population"],"final_cash":close["cash"],
                           "farmland":close["farmland"],"soil_x_farmland":close["soil"]*close["farmland"]}
                local[owner].update(summary)
                rows["regions"].append({**key,"region":i,"owner":owner,**summary,**_rates(summary),**_weighted(summary)})
                for name, g in observations[i]["closing"]["groups"].items():
                    rows["regional_groups"].append({**key,"region":i,"owner":owner,"group":name,
                        **{k:g[k] for k in ("members","support","discontent","pressure","benefit","burden","demand","age")}})
            total = Counter()
            for owner,a in accounts.items():
                summary = {**local[owner],**countries[owner],**physical[owner],
                           **{"reserve_"+g:a["public_close"][g] for g in GOODS}}
                total.update(summary)
                rows["countries"].append({**key,"owner":owner,**summary,**_rates(summary),**_weighted(summary),
                                          "final_soil":_ratio(summary["soil_x_farmland"],summary["farmland"])})
            if (total["member_years"]!=total["food_need"] or cash!=total["final_cash"]
                    or population+total["births"]-total["deaths"]!=total["final_population"]
                    or total["action_switches"]+total["target_only_switches"]!=total["actual_switches"]
                    or total["road_endpoint_units"]!=2*total["road_built"]):
                raise ValueError("members, fiscal choices, roads, cash or population failed to reconcile")
            rows["runs"].append({**key,"initial_regional_sha256":regional_hash,"initial_fiscal_sha256":fiscal_hash,
                "initial_political_sha256":initial,"years_sha256":digest.hexdigest(),"fiscal_sha256":fiscal_digest.hexdigest(),
                "initial_population":population,"initial_cash":cash,**total,**_rates(total),**_weighted(total),
                "final_cash_hhi":_ratio(sum(c["closing"]["cash"]**2 for c in record["countries"]),cash**2),
                "final_soil":_ratio(total["soil_x_farmland"],total["farmland"])})
            for name,data in zip(("groups","distributions","demands"),political.snapshot(key),strict=True):
                rows[name].extend(data)
        rows["cases"].extend(evidence.values())
    return rows


def _json(path, data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n", encoding="utf-8", newline="\n")


def run_study(output, *, sample, seeds=20, horizons=(50,100,200), workers=8, verify=None):
    output = Path(output)
    if os.path.lexists(output):
        raise FileExistsError(output)
    horizons = tuple(horizons)
    if (sample not in ("dev","holdout") or type(seeds) is not int or not 1<=seeds<=20 or not horizons
            or any(type(y) is not int or y<=0 for y in horizons) or len(set(horizons))!=len(horizons)
            or type(workers) is not int or workers<1):
        raise ValueError("expected disjoint dev/holdout, 1..20 seeds, positive workers and unique positive horizons")
    start = time.perf_counter()
    first = 0 if sample=="dev" else 20
    jobs=[(seed,horizons) for seed in range(first,first+seeds)]
    output.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=output.parent,prefix=".political-study-") as temp:
        stage=Path(temp,"study")
        stage.mkdir()
        if workers==1:
            results=list(map(_seed,jobs))
        else:
            with ProcessPoolExecutor(max_workers=min(seeds,workers)) as pool:
                results=list(pool.map(_seed,jobs))
        tables={name:[r for data in results for r in data[name]] for name in (*FILES,"cases","switches")}
        runs=tables["runs"]
        index={(r["seed"],r["arm"],r["year"]):r for r in runs}
        archive={(int(r["seed"]),int(r["year"])):r for r in _read(ARCHIVE/sample/"runs.csv")
                 if r["mode"]=="integrated"}
        matches=0
        paired=[]
        for r in runs:
            ref=index[r["seed"],"off",r["year"]]
            if any(ref[k]!=r[k] for k in ("initial_regional_sha256","initial_fiscal_sha256","initial_political_sha256")):
                raise ValueError("paired political arms have different opening states")
            if r["arm"]=="off" and r["year"] in (50,100,200):
                old=archive[r["seed"],r["year"]]
                if (old["initial_fiscal_sha256"]!=r["initial_fiscal_sha256"] or old["years_sha256"]!=r["fiscal_sha256"]
                        or old["initial_regional_sha256"]!=r["initial_regional_sha256"]):
                    raise ValueError("economic control differs from archived 5.0A integrated path")
                matches+=1
            if r["arm"]=="on":
                paired.append({"seed":r["seed"],"year":r["year"],**{"delta_"+k:r[k]-ref[k] for k in DELTAS}})
        means=[]
        for arm in ARMS:
            for y in horizons:
                group=[r for r in runs if r["arm"]==arm and r["year"]==y]
                totals=Counter()
                for r in group:
                    totals.update({k:v for k,v in r.items() if isinstance(v,(int,float))})
                means.append({"arm":arm,"year":y,"seeds":len(group),
                              **{k:fmean(r[k] for r in group) for k in totals if k not in ("seed","year")},
                              **{"pooled_"+k:v for k,v in {**_rates(totals),**_weighted(totals)}.items()}})
        for name in FILES:
            _write(stage/(name+".csv"),tables[name])
        with (stage/"switches.csv").open("x", encoding="utf-8",newline="") as stream:
            w=csv.DictWriter(stream,fieldnames=SWITCH_FIELDS)
            w.writeheader()
            w.writerows(tables["switches"])
        _write(stage/"paired.csv",paired)
        _write(stage/"means.csv",means)
        _json(stage/"cases.json",tables["cases"])
        manifest={}
        for file in sorted(stage.iterdir()):
            scientific=file.read_bytes()
            manifest[file.name]=hashlib.sha256(scientific).hexdigest()
            if verify is not None and scientific!=(Path(verify)/file.name).read_bytes():
                raise ValueError("replay differs in "+file.name)
        meta={"sample":sample,"first_seed":first,"seeds":seeds,"workers":min(workers,seeds),"horizons":horizons,
              "python":platform.python_version(),"paths":seeds*len(ARMS),"annual_transitions":seeds*len(ARMS)*max(horizons),
              "archived_fiscal_checkpoints":matches,"replayed_checkpoints":len(runs) if verify is not None else 0,
              "table_sha256":manifest,"wall_seconds":time.perf_counter()-start}
        _json(stage/"execution.json",meta)
        if os.path.lexists(output):
            raise FileExistsError(output)
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
        result=run_study(args.out,sample=args.sample,seeds=args.seeds,
                         horizons=tuple(int(v) for v in args.horizons.split(",")),workers=args.workers,
                         verify=args.verify_against)
    except (OSError,ValueError) as error:
        p.exit(1,f"{p.prog}: {error}\n")
    print(json.dumps(result))


if __name__=="__main__":
    main()
