"""Matched public-warehouse transport study with independently settled annual ledgers."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack
import csv
import filecmp
import hashlib
from importlib import import_module
import json
import os
from pathlib import Path
import platform
from statistics import fmean
from tempfile import TemporaryDirectory
import time

from civsim.model import GOODS, generate_world
from civsim.regions import regionalize
from civsim.storage import canonical_line
from experiments.phase5a import _ratio, _read, _sha, _write, disparity
from experiments.phase5d import _json
from experiments.phase6a import _assemble, compressed, digest_file, emit, physical


ARCHIVE=Path(__file__).resolve().parents[1]/"examples/phase6a1/study"
KEY=("seed","arm","year")
GROUPS=("farm","industry","consumer")
SHIP=(*KEY,"request_id","purpose","owner","source","target","recipient","good","quantity","distance","cost_food",
      "aid_freight_allowance_before","aid_freight_allowance_after","region_path","tile_path")
REQUEST=(*KEY,"request_id","owner","region","recipient","purpose","good","target","opening","closing","unfilled",
         "observed_limits","evidence_json")
ROAD=(*KEY,"owner","a","b","capacity","works_use","supply_use","duty_use","relief_use","private_use","unused")
DIRECTION=(*KEY,"source","target","active_pact","breach","opening_tension","closing_tension","closing_trust",
           "trade_value","trade_food","trade_ore","trade_tools","trade_denied","migrants","exit_denied","entry_denied",
           "request","offer","authorized","sent","received","unshipped","cost_food","handling_food","shortfall_reasons")
PANELS=("region-years","country-years","public-shipments","depot-requests","foreign-years","road-years")
REGULAR=("food_need","food_eaten","food_deficit","food_spoiled","births","deaths","immigrants","emigrants",
         "relief_food","public_spoil_food","levy_handling_food","aid_sent","aid_received","aid_freight_food",
         "aid_handling_food","public_works_freight_food","public_relief_freight_food","depot_freight_food",
         "internal_aid_freight_food","domestic_reserve_freight_food","depot_edge_cargo","private_edge_cargo",
         "private_freight_food","trade_freight_food","exports_value","imports_value","foreign_in","foreign_out",
         "trade_denied_out","exit_denied_out","entry_denied_in","member_years","support_x_members","discontent_x_members",
         "within_ration_gap","working_age","production_workers","construction_workers","soil_workers","project_workers",
         "withheld_workers","active_group_years","participants","depot_unfilled","depot_request_rows","depot_transfer_units",
         "emergency_aid_units","forward_aid_units","domestic_reserve_units",
         *(prefix+g for g in GOODS for prefix in ("produced_","production_used_","meal_used_","levied_","works_used_",
           "public_transfer_in_","public_transfer_out_","private_transfer_in_","private_transfer_out_","foreign_in_","foreign_out_")))
REG_END=("closing_population","closing_cash",*("closing_public_"+g for g in GOODS),*("closing_private_"+g for g in GOODS))
GOV=("aid_budget","aid_total_debit","aid_budget_left","aid_budget_overrun","aid_proposed","aid_approved","aid_unshipped",
     "aid_rejected_requests","aid_unshipped_stock","aid_unshipped_budget","aid_unshipped_road","aid_unshipped_storage",
     "pact_partners","terminated_pact_partners","border_tension_sum","closing_tension_sum","border_trust_sum","observed_pairs","trade_partner_years",
     "road_capacity","road_works_use","road_supply_use","road_duty_use","road_relief_use","road_private_use","road_unused","road_saturated_years")
BASE_FIELDS={"home_food":0,"travel_food":0,"public_tools":0,"work_loss":0}
NO_EXTENSION=(None,None)


def collect(record,world,key,writers,extra):
    """Post every private, public, person and cash movement before checking closing stocks."""
    gov=record["government"]
    diplomatic=record["diplomacy"]
    owners={r.id:r.owner for r in world.regions}
    members={r["id"]:r["closing"]["groups"] for r in record["politics"]["regions"]}
    resident={r["id"]:r for r in record["regions"]}
    regions={i:Counter(dict.fromkeys(REGULAR,0)) for i in resident}
    countries={n.id:Counter(dict.fromkeys(GOV,0)) for n in world.nations}
    depots={d["region"]:d for d in gov["depots"]}
    budgets={}
    border_flows,_,_=physical(record,world.borders,owners)
    for (a,b),t in border_flows.items():
        s,r=regions[a],regions[b]
        s.update(exports_value=t["trade_value"],trade_freight_food=t["trade_freight_food"],trade_denied_out=t["trade_denied"],
                 exit_denied_out=t["exit_denied"],foreign_out=t["migrants"],aid_sent=t["aid_dispatched"],
                 aid_freight_food=t["aid_freight_food"],aid_handling_food=t["aid_handling_food"])
        r.update(imports_value=t["trade_value"],entry_denied_in=t["entry_denied"],foreign_in=t["migrants"],
                 aid_received=t["aid_received"])
        for g in GOODS:
            s["foreign_out_"+g]+=t["trade_"+g]
            r["foreign_in_"+g]+=t["trade_"+g]
    ration={i:(r["owner"],r["consumption"]["food_need"],r["consumption"]["food_eaten"]) for i,r in resident.items()}
    _,within=disparity(ration)
    for i,r in resident.items():
        c,meal,prod,vital=regions[i],r["consumption"],r["production"],r["demography"]
        c.update(food_need=meal["food_need"],food_eaten=meal["food_eaten"],food_deficit=meal["food_unmet"],food_spoiled=meal["food_spoiled"],
                 public_spoil_food=depots[i]["spoil_food"],within_ration_gap=within[i],working_age=r["opening"]["population"]//2,
                 production_workers=prod["workers"],construction_workers=prod["investment"]["construction_labor"],
                 soil_workers=prod["soil_care"]["workers"],withheld_workers=prod["withheld_workers"])
        for k in ("births","deaths","immigrants","emigrants"): c[k]=vital[k]
        for g in GOODS:
            c["produced_"+g]=prod["produced"][g]
            c["production_used_"+g]=prod["used"][g]
            c["meal_used_"+g]=meal["used"][g]
        for group in members[i].values():
            n=group["members"]
            c.update(member_years=n,support_x_members=n*group["support"],discontent_x_members=n*group["discontent"])
    for r in record["collective"]["regions"]:
        for group in r["groups"].values():
            regions[r["id"]].update(active_group_years=int(group["participants"]>0),participants=group["participants"])
    for l in gov["levies"]:
        c=regions[l["region"]]
        c["levy_handling_food"]+=l["handling_used"]["food"]
        for g in GOODS: c["levied_"+g]+=l["levied"][g]
    for p in gov["works"]["projects"]:
        regions[p["target"]]["project_workers"]+=p["workers"]
        for g in GOODS: regions[p["source"]]["works_used_"+g]+=p["used"][g]
    for s in gov["works"]["shipments"]: regions[s["source"]]["public_works_freight_food"]+=s["cost_food"]
    relief_sent=Counter()
    for s in gov["relief"]["shipments"]:
        relief_sent[s["source"]]+=s["quantity"]
        regions[s["source"]]["public_relief_freight_food"]+=s["cost_food"]
        regions[s["target"]]["relief_food"]+=s["quantity"]
    for s in record["domestic"]["shipments"]:
        a,b,g,q=s["source"],s["target"],s["good"],s["quantity"]
        regions[a]["private_transfer_out_"+g]+=q
        regions[b]["private_transfer_in_"+g]+=q
        regions[a].update(private_freight_food=s["cost_food"],private_edge_cargo=q*len(s["legs"]))
    supply=record.get("supply",{})
    for s in supply.get("shipments",[]):
        a,b,g,q=s["source"],s["target"],s["good"],s["quantity"]
        owner=owners[a]
        if owner!=owners[b]: raise ValueError("foreign movement reported as domestic warehouse transport")
        regions[a]["public_transfer_out_"+g]+=q
        regions[b]["public_transfer_in_"+g]+=q
        purpose=s["purpose"]
        if purpose not in ("emergency_aid","forward_aid","domestic_reserve"): raise ValueError("unexpected public shipment purpose")
        which="domestic_reserve_freight_food" if purpose=="domestic_reserve" else "internal_aid_freight_food"
        regions[a].update(depot_freight_food=s["cost_food"],depot_edge_cargo=q*len(s["legs"]),depot_transfer_units=q)
        regions[a][which]+=s["cost_food"]
        regions[a][purpose+"_units"]+=q
        writers["public-shipments"].writerow({**key,**{k:s[k] for k in ("request_id","purpose","owner","source","target","recipient",
            "good","quantity","distance","cost_food","aid_freight_allowance_before","aid_freight_allowance_after")},
                            "region_path":" ".join(map(str,s["path"])),"tile_path":" ".join(map(str,s["tile_path"]))})
    for request in supply.get("requests",[]):
        writers["depot-requests"].writerow({**key,**{k:request[k] for k in REQUEST if k not in (*KEY,"observed_limits","evidence_json")},
            "observed_limits":"|".join(request["observed_limits"]),"evidence_json":json.dumps(request["evidence"],sort_keys=True,separators=(",",":"))})
        regions[request["region"]].update(depot_request_rows=1,depot_unfilled=request["unfilled"])
    loads=sum(r["depot_edge_cargo"] for r in regions.values())
    if loads!=sum(e["used"] for e in supply.get("roads",[])) or loads!=sum(e.get("supply_use",0) for e in gov["roads"]):
        raise ValueError("public warehouse hauls differ from road load")
    for edge in gov["roads"]:
        e={k:edge[k] if k in edge else 0 for k in ROAD if k not in KEY}
        used=sum(e[k] for k in ("works_use","supply_use","duty_use","relief_use","private_use"))
        if used+e["unused"]!=e["capacity"]: raise ValueError("shared domestic road does not close")
        writers["road-years"].writerow({**key,**e})
        c=countries[e["owner"]]
        c.update({"road_"+k:e[k] for k in ("capacity","works_use","supply_use","duty_use","relief_use","private_use","unused")})
        c["road_saturated_years"]+=int(e["capacity"]>0 and not e["unused"])
    directions={(e["source"],e["target"]):e for e in diplomatic["physical"]["aid"]["directions"]}
    closed_pacts={(e["a"],e["b"]) for e in diplomatic["events"] if e["kind"]=="pact_terminated"}
    partners=defaultdict(set)
    for p in diplomatic["pairs"]:
        for f,d in zip(p["flows"]["directions"],p["policy"]["directions"],strict=True):
            n,o=f["source"],f["target"]
            if (n,o)!=(d["source"],d["target"]): raise ValueError("unsorted diplomatic directions")
            t=countries[n]
            if budgets.setdefault(n,d["aid_budget"])!=d["aid_budget"]: raise ValueError("inconsistent donor budget")
            if f["trades"]:
                partners[n].add(o)
                partners[o].add(n)
            unfilled=d["aid_quantity"]-f["aid_sent"]
            reasons=directions.get((n,o),{}).get("shortfall_reasons",[])
            t.update(aid_proposed=d["aid_offer"],aid_approved=d["aid_quantity"],aid_unshipped=unfilled,
                     aid_rejected_requests=f["aid_request_rejected"],pact_partners=int(p["policy"]["agreement_active"]),
                     terminated_pact_partners=int((p["a"],p["b"]) in closed_pacts),border_tension_sum=p["opening"]["tension"],
                     closing_tension_sum=p["closing"]["tension"],border_trust_sum=p["closing"]["trust"],observed_pairs=1)
            for name in ("stock","road","budget","storage"):
                if name in reasons: t["aid_unshipped_"+name]+=unfilled
            if p["adjacent"] or d["aid_request"] or d["aid_offer"]:
                writers["foreign-years"].writerow({**key,"source":n,"target":o,"active_pact":int(p["policy"]["agreement_active"]),
                    "breach":f["agreement_breach"],"opening_tension":p["opening"]["tension"],"closing_tension":p["closing"]["tension"],
                    "closing_trust":p["closing"]["trust"],"trade_value":f["trade_value"],**{"trade_"+g:f["goods"][g] for g in GOODS},
                    "trade_denied":f["trade_denied"],"migrants":f["migrants"],"exit_denied":f["migration_denied_exit"],
                    "entry_denied":f["migration_denied_entry"],"request":d["aid_request"],"offer":d["aid_offer"],
                    "authorized":d["aid_quantity"],"sent":f["aid_sent"],"received":f["aid_received"],"unshipped":unfilled,
                    "cost_food":f["aid_freight"],"handling_food":f["aid_handling"],"shortfall_reasons":"|".join(reasons)})
    service,special,annual=extra(record,key,writers) if extra else ({},{},{})
    for i,r in resident.items():
        c=regions[i]
        cost=service.get(i,BASE_FIELDS)
        opening,closing=r["opening"],r["closing"]
        if opening["population"]+c["births"]-c["deaths"]+c["immigrants"]-c["emigrants"]!=closing["population"]:
            raise ValueError("resident population does not close")
        if opening["cash"]+c["exports_value"]-c["imports_value"]!=closing["cash"]:
            raise ValueError("resident cash does not close")
        if c["working_age"]!=sum(c[k] for k in ("production_workers","construction_workers","soil_workers","project_workers","withheld_workers"))+cost["work_loss"]:
            raise ValueError("home labor does not close")
        for g in GOODS:
            private=(opening["stock"][g]+c["produced_"+g]-c["production_used_"+g]-c["meal_used_"+g]-c["levied_"+g]
                     +c["foreign_in_"+g]-c["foreign_out_"+g]+c["private_transfer_in_"+g]-c["private_transfer_out_"+g])
            public=(depots[i]["opening"][g]+c["levied_"+g]-c["works_used_"+g]+c["public_transfer_in_"+g]-c["public_transfer_out_"+g])
            if g=="food":
                private+=c["relief_food"]+cost["home_food"]-c["trade_freight_food"]-c["private_freight_food"]
                public+=(c["aid_received"]-c["aid_sent"]-c["aid_freight_food"]-c["public_works_freight_food"]
                         -relief_sent[i]-c["public_relief_freight_food"]-c["public_spoil_food"]-c["levy_handling_food"]
                         -c["depot_freight_food"]-cost["home_food"]-cost["travel_food"])
            if g=="tools": public-=cost["public_tools"]
            if (private,public)!=(closing["stock"][g],depots[i]["closing"][g]):
                raise ValueError(f"public/private stock closure at {key}/{i}/{g}: projected {(private, public)} vs {(closing['stock'][g],depots[i]['closing'][g])}")
        c.update(annual.get(i,{}))
        end={"closing_population":closing["population"],"closing_cash":closing["cash"],
             **{"closing_public_"+g:depots[i]["closing"][g] for g in GOODS},**{"closing_private_"+g:closing["stock"][g] for g in GOODS}}
        countries[r["owner"]].update(c)
        c.update(end)
        countries[r["owner"]].update(end)
    receipts={d["donor"]:d for d in diplomatic["physical"]["aid"]["donors"]}
    for n,c in countries.items():
        c["aid_budget"]=budgets[n]
        debit=c["aid_sent"]+c["aid_freight_food"]+c["internal_aid_freight_food"]
        if debit!=receipts[n]["actual_debit"] or debit>budgets[n]: raise ValueError("donor gross food spending does not close")
        c.update(aid_total_debit=debit,aid_budget_left=budgets[n]-debit,aid_budget_overrun=max(0,debit-budgets[n]),
                 trade_partner_years=len(partners[n]))
        c.update(special.get(n,{}))
    return regions,countries


def ratios(row):
    result={"deficit_share":_ratio(row["food_deficit"],row["food_need"]),
            "mean_support":_ratio(row["support_x_members"],row["member_years"]),
            "mean_discontent":_ratio(row["discontent_x_members"],row["member_years"]),
            "within_country_disparity":_ratio(row["within_ration_gap"],row["food_need"])}
    if "observed_pairs" in row:
        result["mean_opening_tension"]=_ratio(row["border_tension_sum"],row["observed_pairs"])
        result["mean_closing_tension"]=_ratio(row["closing_tension_sum"],row["observed_pairs"])
        result["aid_fulfillment"]=_ratio(row["aid_sent"],row["aid_approved"])
    return result


def _seed(job):
    seed,horizons,temp,arms,engine_name,extension_name=job
    engine=import_module(engine_name)
    extension=import_module(extension_name) if extension_name else None
    more=extension.EXTRA_PANELS if extension else {}
    endpoints=set(REG_END)|set(extension.EXTRA_ENDPOINTS if extension else ())
    data={n:[] for n in ("runs","countries","regions")}
    with ExitStack() as stack:
        streams={p:stack.enter_context(compressed(Path(temp)/f"{seed}-{p}.gz")) for p in (*PANELS,*more)}
        headers={"public-shipments":SHIP,"depot-requests":REQUEST,"foreign-years":DIRECTION,"road-years":ROAD,**more}
        writers={p:emit(streams[p],names,True) for p,names in headers.items()}
        for arm in arms:
            world=regionalize(generate_world(seed))
            sim=engine.start62(world)
            initial=_sha(engine.snapshot62(sim))
            h=hashlib.sha256()
            initial_n={n.id:n.population for n in world.nations}
            initial_r={r.id:r.population for r in world.regions}
            owner={r.id:r.owner for r in world.regions}
            accum={level:defaultdict(Counter) for level in ("regions","countries")}
            for y in range(1,max(horizons)+1):
                row=engine.step62(sim,y,arm)
                h.update(canonical_line(row))
                key={"seed":seed,"arm":arm,"year":y}
                reg,nat=collect(row,world,key,writers,extension.observe_service if extension else None)
                for level,items,panel in (("regions",reg,"region-years"),("countries",nat,"country-years")):
                    for i,c in items.items():
                        area={"region":i,"owner":owner[i]} if level=="regions" else {"owner":i}
                        raw={**key,**area,**c,**ratios(c)}
                        if level=="regions":
                            old=row["government"]["depots"][i]
                            if old["region"]!=i: raise ValueError("depot order differs from region order")
                            raw.update({"opening_public_"+g:old["opening"][g] for g in GOODS})
                        if panel not in writers: writers[panel]=emit(streams[panel],tuple(raw),True)
                        writers[panel].writerow(raw)
                        accum[level][i].update({k:v for k,v in c.items() if k not in endpoints})
                if y not in horizons: continue
                total=Counter()
                for level,items,init in (("regions",reg,initial_r),("countries",nat,initial_n)):
                    for i,c in items.items():
                        area={"region":i,"owner":owner[i]} if level=="regions" else {"owner":i}
                        snap={**accum[level][i],**{k:v for k,v in c.items() if k in endpoints},"opening_population":init[i]}
                        if level=="countries": total.update(snap)
                        data[level].append({**key,**area,**snap,**ratios(snap)})
                if total["aid_sent"]!=total["aid_received"]+total["aid_handling_food"]:
                    raise ValueError("world aid cargo differs from received + lost")
                data["runs"].append({**key,"initial_sha256":initial,"years_sha256":h.hexdigest(),**total,**ratios(total)})
    return data


def _bound(output,sample,seeds,horizons,workers):
    if os.path.lexists(output): raise FileExistsError(output)
    if (sample not in ("dev","holdout") or type(seeds) is not int or not 1<=seeds<=20 or
            not horizons or any(type(y) is not int or y<=0 for y in horizons) or tuple(sorted(set(horizons)))!=horizons or
            type(workers) is not int or workers<1): raise ValueError("invalid experiment range")
    first=0 if sample=="dev" else 20
    return range(first,first+seeds)


def run_stage(output,*,sample,seeds,horizons,workers,verify,arms,engine_name,extension_name=None,reference=None):
    output=Path(output)
    horizons=tuple(horizons)
    seeds_range=_bound(output,sample,seeds,horizons,workers)
    first=seeds_range.start
    start=time.perf_counter()
    output.parent.mkdir(parents=True,exist_ok=True)
    extension=import_module(extension_name) if extension_name else None
    metrics_extra=extension.SERVICE_METRICS if extension else ()
    if reference is not None:
        reference=Path(reference)
        met=json.loads((reference/"execution.json").read_bytes())
        if (met["sample"]!=sample or met["seeds"]!=seeds or list(horizons)!=met["horizons"] or
                digest_file(reference/"runs.csv")!=met["table_sha256"]["runs.csv"]):
            raise ValueError("unmatched public-transport reference")
    with TemporaryDirectory(prefix=".public-study-",dir=output.parent) as temp:
        stage=Path(temp,"result")
        stage.mkdir()
        jobs=[(s,horizons,temp,arms,engine_name,extension_name) for s in seeds_range]
        if workers==1: parts=list(map(_seed,jobs))
        else:
            with ProcessPoolExecutor(max_workers=min(seeds,workers)) as pool: parts=list(pool.map(_seed,jobs))
        tables={k:[r for p in parts for r in p[k]] for k in parts[0]}
        runs=tables["runs"]
        seen={(r["seed"],r["arm"],r["year"]):r for r in runs}
        historical={(int(r["seed"]),int(r["year"])):r for r in _read(ARCHIVE/sample/"runs.csv") if r["arm"]=="F"}
        matches=0
        for r in runs:
            s,arm,y=r["seed"],r["arm"],r["year"]
            if r["initial_sha256"]!=seen[s,arms[0],y]["initial_sha256"]: raise ValueError("unmatched arm openings")
            if arm=="A" and y in (50,100,200):
                old=historical[s,y]
                if (r["initial_sha256"],r["years_sha256"])!=(old["initial_sha256"],old["years_sha256"]):
                    raise ValueError(f"historical F diverged at {s}/{y}")
                matches+=1
        metrics=[k for k in runs[0] if k not in (*KEY,"initial_sha256","years_sha256")]
        def numeric(v): return float(v) if "." in v or "e" in v.lower() else int(v)
        ref_count=0
        if reference:
            for old in _read(reference/"runs.csv"):
                s,y=int(old["seed"]),int(old["year"])
                if old["initial_sha256"]!=seen[s,arms[0],y]["initial_sha256"]: raise ValueError("different B1/B2 opening")
                seen[s,old["arm"],y]={k:numeric(old[k]) if k in old else 0 for k in metrics if k in old or k in metrics_extra}
                ref_count+=1
            if ref_count!=2*seeds*len(horizons): raise ValueError("incomplete A/B reference")
        comparisons=(("B","A"),) if not reference else (("B","A"),("C","B"),("D","C"),("D","B"),("C","A"),("D","A"))
        paired=[{"seed":s,"year":y,"contrast":a+"-"+b,**{k:seen[s,a,y][k]-seen[s,b,y][k] for k in metrics}}
                for s in seeds_range for y in horizons for a,b in comparisons]
        means=[]
        for arm in arms:
            for y in horizons:
                g=[seen[s,arm,y] for s in seeds_range]
                means.append({"arm":arm,"year":y,"seeds":seeds,**{k:fmean(r[k] for r in g) for k in metrics},
                              "pooled_deficit_share":_ratio(sum(r["food_deficit"] for r in g),sum(r["food_need"] for r in g))})
        for k in (*PANELS,*(extension.EXTRA_PANELS if extension else ())): _assemble(k,seeds_range,Path(temp),stage/(k+".csv.gz"))
        for k,data in {**tables,"paired":paired,"means":means}.items(): _write(stage/(k+".csv"),data)
        manifest={p.name:digest_file(p) for p in sorted(stage.iterdir())}
        if verify:
            for name in manifest:
                if not filecmp.cmp(stage/name,Path(verify)/name,shallow=False): raise ValueError("repeat differs in "+name)
        meta={"sample":sample,"first_seed":first,"seeds":seeds,"workers":min(seeds,workers),"horizons":horizons,
              "arms":arms,"paths":seeds*len(arms),"annual_transitions":seeds*len(arms)*max(horizons),
              "archived_6a1_F":matches,"b1_reference_checkpoints":ref_count,
              "b1_reference_runs_sha256":digest_file(reference/"runs.csv") if reference else None,
              "replayed_checkpoints":len(runs) if verify else 0,"table_sha256":manifest,
              "wall_seconds":time.perf_counter()-start,"python":platform.python_version()}
        _json(stage/"execution.json",meta)
        if os.path.lexists(output): raise FileExistsError(output)
        stage.rename(output)
    return meta


def run_study(output,*,sample,seeds=20,horizons=(50,100,200),workers=5,verify=None):
    return run_stage(output,sample=sample,seeds=seeds,horizons=horizons,workers=workers,verify=verify,
                     arms=("A","B"),engine_name="civsim.supply62")


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sample",required=True,choices=("dev","holdout"))
    p.add_argument("--seeds",type=int,default=20)
    p.add_argument("--workers",type=int,default=5)
    p.add_argument("--horizons",default="50,100,200")
    p.add_argument("--out",required=True,type=Path)
    p.add_argument("--verify-against",type=Path)
    return p


if __name__=="__main__":
    a=parser().parse_args()
    print(json.dumps(run_study(a.out,sample=a.sample,seeds=a.seeds,horizons=tuple(map(int,a.horizons.split(","))),
                               workers=a.workers,verify=a.verify_against)))
