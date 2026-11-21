"""Six matched policy paths with regional consumption, shipment and budget accounting."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack
import filecmp
import hashlib
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
from experiments.phase5a import _ratio, _read, _sha, _write
from experiments.phase5d import _json
from experiments.phase6a import ENDPOINT, NATIONAL, _assemble, compressed, country_years, digest_file, emit, physical, rates

ARMS = tuple("ABCDEF")
ARCHIVE = Path(__file__).resolve().parents[1]/"examples/phase6a/study"
KEY = ("seed","arm","year")
GROUPS = ("farm","industry","consumer")
PANELS = ("country-years","region-years","direction-years","aid-attempts")
ATTEMPT = (*KEY,"donor","recipient","source","target","distance","authorized_remaining","capacity_remaining",
           "available_stock","storage_space","uncapped_quantity","quantity","budget_displaced",
           "budget_before","budget_after","limit_authorized","limit_road","limit_stock","limit_storage","limit_budget","binding")
DIRECT = (*KEY,"source","target","agreement_active","agreement_started","agreement_terminated","access_kept","breach","no_opportunity",
          "pact_score","export_permille","exit_permille","entry_permille","trade_denied","exit_denied","entry_denied",
          "import_dependence","export_exposure","trade_food","trade_ore","trade_tools","trade_value","migrants",
          "request","offer","authorized","unshipped","dispatched","received","freight","handling","actual_debit","shortfall_reasons")
CONSUMPTION = ("direct_eaten_delta","recipient_depot_eaten_delta","control_eaten_delta","control_deficit_delta",
               "recipient_control_eaten_delta","donor_control_deficit_delta")
POLICY = ("planned_budget","available_aid_budget","approved_donor_budget","unspent_budget","approved_donor_unspent_budget",
          "aid_policy_country_years","actual_debit","budget_overrun","overrun_donor_years","budget_displaced",
          "aid_offered","aid_authorized","aid_unshipped","requested_food","unapproved_requests","rejected_offers",
          "offer_years","approved_donor_years","recipient_years","donor_years",
          "active_pact_partners","new_pact_partners","terminated_pact_partners","pact_kept_out","pact_breached_out","pact_no_opportunity_out",
          "trade_denied_out","exit_denied_out","entry_denied_in","export_limited_directions","exit_limited_directions",
          "entry_limited_directions","donor_control_reserve_delta","donor_control_support_delta_x_members",
          "donor_control_population_years","open_public_food_years","closing_public_food_years",*CONSUMPTION)
COUNTRY_SUM = (*NATIONAL,*POLICY)
REG_SUM = ("food_need","food_eaten","food_deficit","food_spoiled","aid_sent","aid_received","aid_freight_food",
           "aid_handling_food","actual_debit","relief_food","public_spoil_food","member_years",
           "support_x_members","discontent_x_members","closing_public_food_years","births","deaths",*CONSUMPTION,
           *("produced_"+g for g in GOODS), *("import_"+g for g in GOODS), *("export_"+g for g in GOODS),
           "import_value","export_value","trade_denied_out","exit_denied_out","entry_denied_in",
           *(g+"_direct_x_members" for g in GROUPS))
REG_END = ("closing_population","closing_cash",*("closing_public_"+g for g in GOODS),*("closing_private_"+g for g in GOODS))


def contrasts(values):
    a,b,c,d,e,f = (values[k] for k in ARMS)
    return {"B-A":b-a,"C-A":c-a,"D-A":d-a,"E-A":e-a,"F-E":f-e,"I":(e-a)-((b-a)+(c-a)+(d-a))}


def attempt_limits(t,distance):
    return {"authorized":t["request_remaining"],"road":t["capacity_before"],
            "stock":100*t["available_food"]//(100+distance),"storage":(32*t["storage_space"]+31)//31,"budget":None}


def terminal_reasons(remaining,visits):
    if not remaining: return []
    if remaining<2: return ["minimum_lot"]
    if not visits: return ["no_border_route"]
    reasons={k for bound,_ in visits for k in bound if k!="authorized"}
    if any(raw==1 for _,raw in visits): reasons.add("minimum_lot")
    return sorted(reasons)


def policies(record, owners, routes, arm, key, writers):
    """Cross-post international contracts, shipments, donor spending and shortfalls."""
    ctx = record["diplomacy"]
    aid = ctx["physical"]["aid"]
    nations = {n["id"]:Counter(dict.fromkeys(POLICY,0)) for n in ctx["countries"]}
    budgets = {}
    tickets = defaultdict(Counter)
    for t in aid["shipments"]:
        tickets[t["donor"],t["recipient"]].update(dispatched=t["quantity"],received=t["received"],
                                                  freight=t["cost_food"],handling=t["handling_food"])
    plans = {(d["source"],d["target"]):d for p in ctx["pairs"] for d in p["policy"]["directions"]}
    for d in plans.values():
        donor = d["source"]
        if budgets.setdefault(donor,d["aid_budget"])!=d["aid_budget"]:
            raise ValueError("national aid budget duplicated inconsistently across destinations")
    summary = {(r["source"],r["target"]):r for r in aid["directions"]}
    visits=defaultdict(list)
    for t in aid["attempts"]:
        a,b=t["source"],t["target"]
        caps=t.get("limits") or attempt_limits(t,routes[tuple(sorted((a,b)))].distance)
        raw=min(q for q in caps.values() if q is not None)
        visits[owners[a],owners[b]].append(([k for k,v in caps.items() if v==raw],raw))
    terminated={(e["a"],e["b"]) for e in ctx["events"] if e["kind"]=="pact_terminated"}
    actual_by_donor = Counter()
    for pair in ctx["pairs"]:
        active = int(pair["policy"]["agreement_active"])
        started = int(pair["policy"]["agreement_started"])
        ended = int((pair["a"],pair["b"]) in terminated)
        if ended!=int(active and pair["closing"]["agreement_start"]==0):
            raise ValueError("pact termination event differs from active agreement closing state")
        for direction in pair["flows"]["directions"]:
            a,b = direction["source"], direction["target"]
            d,t = plans[a,b],tickets[a,b]
            source,target = nations[a],nations[b]
            auth = d["aid_quantity"]
            if sum((t["received"],t["handling"]))!=t["dispatched"] or t["dispatched"]>auth:
                raise ValueError("directional aid voucher does not close")
            if auth:
                expected = summary[a,b]
                if [auth,t["dispatched"],t["received"],t["freight"],t["handling"],auth-t["dispatched"]] != [
                    expected[k] for k in ("authorized","dispatched","received","cost_food","handling_food","unshipped")]:
                    raise ValueError("directional aid receipt differs from shipments")
            debit = t["dispatched"]+t["freight"]
            actual_by_donor[a]+=debit
            source.update(actual_debit=debit,aid_offered=d["aid_offer"],aid_authorized=auth,
                          aid_unshipped=auth-t["dispatched"],rejected_offers=direction["aid_offer_rejected"],
                          active_pact_partners=active,new_pact_partners=started,terminated_pact_partners=ended,pact_kept_out=direction["access_kept"],
                          pact_breached_out=direction["agreement_breach"],
                          pact_no_opportunity_out=int(active and not direction["trade_opportunity"]),
                          trade_denied_out=direction["trade_denied"],exit_denied_out=direction["migration_denied_exit"],
                          export_limited_directions=int(d["trade_limit_permille"]<1000),
                          exit_limited_directions=int(d["migration_limit_permille"]<1000))
            target.update(requested_food=d["aid_request"],unapproved_requests=direction["aid_request_rejected"],
                          entry_denied_in=direction["migration_denied_entry"],entry_limited_directions=int(d["migration_accept_permille"]<1000))
            if t["received"]: target["recipient_years"]=1
            if (active or d["aid_request"] or d["aid_offer"] or direction["trades"] or direction["migrants"]
                    or min(d["trade_limit_permille"],d["migration_limit_permille"],d["migration_accept_permille"])<1000):
                reasons=terminal_reasons(auth-t["dispatched"],visits[a,b])
                official=summary.get((a,b),{}).get("shortfall_reasons")
                if official is not None and official!=reasons: raise ValueError("shortfall explanation differs from physical attempts")
                row = {**key,"source":a,"target":b,"agreement_active":active,"agreement_started":started,"agreement_terminated":ended,
                       "access_kept":direction["access_kept"],"breach":direction["agreement_breach"],
                       "no_opportunity":int(active and not direction["trade_opportunity"]),"pact_score":d["pact_score"],
                       "export_permille":d["trade_limit_permille"],"exit_permille":d["migration_limit_permille"],
                       "entry_permille":d["migration_accept_permille"],"trade_denied":direction["trade_denied"],
                       "exit_denied":direction["migration_denied_exit"],"entry_denied":direction["migration_denied_entry"],
                       "import_dependence":d["import_dependence"],"export_exposure":d["export_exposure"],
                       **{"trade_"+g:direction["goods"][g] for g in GOODS},"trade_value":direction["trade_value"],
                       "migrants":direction["migrants"],"request":d["aid_request"],"offer":d["aid_offer"],"authorized":auth,
                       "unshipped":auth-t["dispatched"],**{k:t[k] for k in ("dispatched","received","freight","handling")},
                       "actual_debit":debit,"shortfall_reasons":"|".join(reasons) if reasons else ""}
                writers["direction-years"].writerow(row)
    enhanced = arm in "BCDF"
    for t in aid["attempts"]:
        x,y = t["source"],t["target"]
        a,b = owners[x],owners[y]
        distance = routes[tuple(sorted((x,y)))].distance
        limits = attempt_limits(t,distance)
        if enhanced: limits = t["limits"]
        unbounded = min(limits[k] for k in ("authorized","road","stock","storage"))
        uncapped = unbounded if unbounded>=2 else 0
        q = t["quantity"]
        if enhanced and t["uncapped_quantity"]!=uncapped: raise ValueError("uncapped route quantity does not match physical limits")
        displaced = uncapped-q
        if displaced<0 or (arm!="F" and displaced): raise ValueError("unexplained suppression of physical aid")
        nations[a]["budget_displaced"]+=displaced
        binding = t.get("binding")
        if binding is None: binding = [k for k,v in limits.items() if v==unbounded]
        writers["aid-attempts"].writerow({**key,"donor":a,"recipient":b,"source":x,"target":y,"distance":distance,
            "authorized_remaining":t["request_remaining"],"capacity_remaining":t["capacity_before"],"available_stock":t["available_food"],
            "storage_space":t["storage_space"],"uncapped_quantity":uncapped,"quantity":q,"budget_displaced":displaced,
            "budget_before":t.get("before_budget"),"budget_after":t.get("after_budget"),
            **{"limit_"+k:v for k,v in limits.items()},"binding":"|".join(binding)})
    donor_rows = {d["donor"]:d for d in aid.get("donors",[])}
    if enhanced and donor_rows.keys()!=nations.keys(): raise ValueError("public donor ledger incomplete")
    for i,c in nations.items():
        q = budgets[i]
        debit = actual_by_donor[i]
        over = max(0,debit-q)
        available=q if arm in "BEF" else 0
        approved=bool(c["aid_authorized"])
        c.update(planned_budget=q,available_aid_budget=available,approved_donor_budget=q if approved else 0,
                 aid_policy_country_years=int(arm in "BEF"),unspent_budget=max(0,available-debit),
                 approved_donor_unspent_budget=max(0,q-debit) if approved else 0,
                 budget_overrun=over,overrun_donor_years=int(over>0),
                 offer_years=int(c["aid_offered"]>0),approved_donor_years=int(c["aid_authorized"]>0),donor_years=int(debit>0))
        if arm=="F" and over: raise ValueError("realized food and freight exceed capped national budget")
        if i in donor_rows:
            d = donor_rows[i]
            if (q,debit,max(0,q-debit),over)!=(d["planned_budget"],d["actual_debit"],d["remaining_budget"],d["overrun"]):
                raise ValueError("donor charge differs from independently posted receipts")
    return nations


def regional_rows(record, edges, incidence, arm, base):
    depots = {d["region"]:d for d in record["government"]["depots"]}
    states = {r["id"]:r["closing"]["groups"] for r in record["politics"]["regions"]}
    relief = Counter()
    for s in record["government"]["relief"]["shipments"]:
        relief[s["target"]]+=s["quantity"]
    transit = defaultdict(Counter)
    for (a,b),e in edges.items():
        outgoing,incoming=transit[a],transit[b]
        outgoing.update(aid_sent=e["aid_dispatched"],aid_freight_food=e["aid_freight_food"],aid_handling_food=e["aid_handling_food"],
                        export_value=e["trade_value"],trade_denied_out=e["trade_denied"],exit_denied_out=e["exit_denied"])
        incoming.update(aid_received=e["aid_received"],import_value=e["trade_value"],entry_denied_in=e["entry_denied"])
        for g in GOODS:
            outgoing["export_"+g]+=e["trade_"+g]
            incoming["import_"+g]+=e["trade_"+g]
    result={}
    for r in record["regions"]:
        i=r["id"]
        c=Counter(dict.fromkeys(REG_SUM,0))
        c.update(transit[i])
        depot,meal,d=depots[i],r["consumption"],r["demography"]
        c.update(food_need=meal["food_need"],food_eaten=meal["food_eaten"],food_deficit=meal["food_unmet"],
                 food_spoiled=meal["food_spoiled"],relief_food=relief[i],public_spoil_food=depot["spoil_food"],
                 actual_debit=c["aid_sent"]+c["aid_freight_food"],direct_eaten_delta=incidence[i],
                 recipient_depot_eaten_delta=incidence[i] if c["aid_received"] else 0,
                 closing_public_food_years=depot["closing"]["food"],births=d["births"],deaths=d["deaths"])
        membership={}
        for name,g in states[i].items():
            n=g["members"]
            delta=g.get("foreign_aid_support_delta",0)
            membership.update({name+"_members":n,name+"_support":g["support"],name+"_discontent":g["discontent"],
                               name+"_direct":delta})
            c.update(member_years=n,support_x_members=n*g["support"],discontent_x_members=n*g["discontent"])
            c[name+"_direct_x_members"]=n*delta
        for g in GOODS: c["produced_"+g]=r["production"]["produced"][g]
        ky=record["year"],i
        if arm=="A": base[ky]=(c["food_eaten"],c["food_deficit"])
        ae,af=base[ky]
        c["control_eaten_delta"]=c["food_eaten"]-ae
        c["control_deficit_delta"]=c["food_deficit"]-af
        c["recipient_control_eaten_delta"]=c["control_eaten_delta"] if c["aid_received"] else 0
        c["donor_control_deficit_delta"]=c["control_deficit_delta"] if c["aid_sent"] else 0
        result[i]={"owner":r["owner"],**c,**membership,"opening_public_food":depot["opening"]["food"],
                   "opening_population":r["opening"]["population"],"closing_population":r["closing"]["population"],
                   "closing_cash":r["closing"]["cash"],**{"closing_public_"+g:depot["closing"][g] for g in GOODS},
                   **{"closing_private_"+g:r["closing"]["stock"][g] for g in GOODS}}
    return result


def _seed(job):
    from civsim.diplomacy61 import snapshot61, start61, step61
    from experiments.aid_incidence61 import meal_incidence
    seed,horizons,temp=job
    data={k:[] for k in ("runs","countries","regions")}
    region_ref,nation_ref={},{}
    with ExitStack() as stack:
        streams={p:stack.enter_context(compressed(Path(temp)/f"{seed}-{p}.gz")) for p in PANELS}
        writers={"aid-attempts":emit(streams["aid-attempts"],ATTEMPT,True),
                 "direction-years":emit(streams["direction-years"],DIRECT,True)}
        for arm in ARMS:
            world=regionalize(generate_world(seed))
            sim=start61(world)
            initial=_sha(snapshot61(sim))
            initial_n={n.id:(n.population,n.cash) for n in world.nations}
            initial_r={r.id:r.population for r in world.regions}
            owners={r.id:r.owner for r in world.regions}
            routes={(road.a,road.b):road for road in world.borders}
            digest=hashlib.sha256()
            running_c,running_r=defaultdict(Counter),defaultdict(Counter)
            for year in range(1,max(horizons)+1):
                row=step61(sim,year,arm)
                digest.update(canonical_line(row))
                key={"seed":seed,"arm":arm,"year":year}
                edges,flows,_=physical(row,world.borders,owners)
                regions=regional_rows(row,edges,meal_incidence(row,world),arm,region_ref)
                countries=country_years(row,flows)
                extra=policies(row,owners,routes,arm,key,writers)
                for i,r in regions.items():
                    running_r[i].update({k:r[k] for k in REG_SUM})
                    for k in CONSUMPTION[:-1]: extra[r["owner"]][k]+=r[k]
                    raw={**key,"region":i,**r}
                    if "region-years" not in writers: writers["region-years"]=emit(streams["region-years"],tuple(raw),True)
                    writers["region-years"].writerow(raw)
                opening={a["id"]:a["public_open"]["food"] for a in row["government"]["accounts"]}
                for i,c in countries.items():
                    p=extra[i]
                    within=[r for r in regions.values() if r["owner"]==i]
                    if any(c[k]!=sum(r[k] for r in within) for k in ("aid_sent","aid_received","aid_freight_food","food_eaten","food_deficit")):
                        raise ValueError("national and regional meal or aid accounts differ")
                    if p["actual_debit"]!=c["aid_sent"]+c["aid_freight_food"]: raise ValueError("inconsistent national gross aid")
                    ky=year,i
                    support=_ratio(c["support_x_members"],c["member_years"])
                    if arm=="A": nation_ref[ky]=(c["food_deficit"],c["closing_public_food"],support)
                    gap,reserve,reference_support=nation_ref[ky]
                    if p["donor_years"]:
                        p["donor_control_deficit_delta"]=c["food_deficit"]-gap
                        p["donor_control_reserve_delta"]=c["closing_public_food"]-reserve
                        p["donor_control_support_delta_x_members"]=(support-reference_support)*c["member_years"]
                        p["donor_control_population_years"]=c["member_years"]
                    p["open_public_food_years"]=opening[i]
                    p["closing_public_food_years"]=c["closing_public_food"]
                    c.update(p)
                    running_c[i].update({k:c[k] for k in COUNTRY_SUM})
                    raw={**key,"owner":i,**c,**rates(c)}
                    if "country-years" not in writers: writers["country-years"]=emit(streams["country-years"],tuple(raw),True)
                    writers["country-years"].writerow(raw)
                if year not in horizons: continue
                total=Counter()
                for i,c in countries.items():
                    snapshot={**running_c[i],**{k:c[k] for k in ENDPOINT},"opening_population":initial_n[i][0],
                              "opening_cash":initial_n[i][1]}
                    total.update(snapshot)
                    data["countries"].append({**key,"owner":i,**snapshot,**rates(snapshot)})
                for i,r in regions.items():
                    c=running_r[i]
                    data["regions"].append({**key,"region":i,"owner":r["owner"],**c,"opening_population":initial_r[i],
                         **{k:r[k] for k in REG_END},"deficit_share":_ratio(c["food_deficit"],c["food_need"])})
                if any(total[k]%2 for k in ("active_pact_partners","new_pact_partners","terminated_pact_partners")):
                    raise ValueError("bilateral treaty not recorded for both countries")
                data["runs"].append({**key,"initial_sha256":initial,"years_sha256":digest.hexdigest(),
                    **total,**rates(total),"agreement_years":total["active_pact_partners"]//2,
                    "agreements_started":total["new_pact_partners"]//2,"agreements_terminated":total["terminated_pact_partners"]//2})
    return data


def run_study(output,*,sample,seeds=20,horizons=(50,100,200),workers=5,verify=None):
    output=Path(output)
    if os.path.lexists(output): raise FileExistsError(output)
    horizons=tuple(horizons)
    if (sample not in ("dev","holdout") or type(seeds) is not int or not 1<=seeds<=20 or not horizons or
            any(type(y) is not int or y<=0 for y in horizons) or tuple(sorted(set(horizons)))!=horizons or
            type(workers) is not int or workers<1): raise ValueError("invalid cohort, horizons or worker count")
    first=0 if sample=="dev" else 20
    seeds_range=range(first,first+seeds)
    t0=time.perf_counter()
    output.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix=".aid-study-",dir=output.parent) as temp:
        stage=Path(temp,"result")
        stage.mkdir()
        jobs=[(s,horizons,temp) for s in seeds_range]
        if workers==1: parts=list(map(_seed,jobs))
        else:
            with ProcessPoolExecutor(max_workers=min(seeds,workers)) as pool: parts=list(pool.map(_seed,jobs))
        tables={k:[r for p in parts for r in p[k]] for k in parts[0]}
        runs=tables["runs"]
        lookup={(r["seed"],r["arm"],r["year"]):r for r in runs}
        archived={(int(r["seed"]),r["arm"],int(r["year"])):r for r in _read(ARCHIVE/sample/"runs.csv") if r["arm"] in ("C","D")}
        matches=Counter()
        for r in runs:
            s,arm,y=r["seed"],r["arm"],r["year"]
            if r["initial_sha256"]!=lookup[s,"A",y]["initial_sha256"]: raise ValueError("unmatched opening")
            if arm in ("A","E") and y in (50,100,200):
                old=archived[s,{"A":"C","E":"D"}[arm],y]
                if (old["initial_sha256"],old["years_sha256"])!=(r["initial_sha256"],r["years_sha256"]):
                    raise ValueError(f"6.0A control path diverged at {s} {arm} {y}")
                matches[arm]+=1
        metrics=[k for k,v in runs[0].items() if k not in KEY and isinstance(v,(int,float))]
        paired=[]
        for s in seeds_range:
            for y in horizons:
                values={k:contrasts({arm:lookup[s,arm,y][k] for arm in ARMS}) for k in metrics}
                for name in next(iter(values.values())):
                    paired.append({"seed":s,"year":y,"contrast":name,**{k:v[name] for k,v in values.items()}})
        means=[]
        for arm in ARMS:
            for y in horizons:
                group=[lookup[s,arm,y] for s in seeds_range]
                means.append({"arm":arm,"year":y,"seeds":seeds,**{k:fmean(r[k] for r in group) for k in metrics},
                    "pooled_deficit_share":_ratio(sum(r["food_deficit"] for r in group),sum(r["food_need"] for r in group))})
        for k in PANELS: _assemble(k,seeds_range,Path(temp),stage/(k+".csv.gz"))
        for k,records in {**tables,"means":means,"paired":paired}.items(): _write(stage/(k+".csv"),records)
        manifest={p.name:digest_file(p) for p in sorted(stage.iterdir())}
        if verify:
            for name in manifest:
                if not filecmp.cmp(stage/name,Path(verify)/name,shallow=False): raise ValueError("replay differs in "+name)
        meta={"sample":sample,"first_seed":first,"seeds":seeds,"workers":min(workers,seeds),"horizons":horizons,
              "paths":len(ARMS)*seeds,"annual_transitions":len(ARMS)*seeds*max(horizons),"archive_6a_A":matches["A"],
              "archive_6a_E":matches["E"],"replayed_checkpoints":len(runs) if verify else 0,"table_sha256":manifest,
              "python":platform.python_version(),"wall_seconds":time.perf_counter()-t0}
        _json(stage/"execution.json",meta)
        if os.path.lexists(output): raise FileExistsError(output)
        stage.rename(output)
    return meta


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sample",choices=("dev","holdout"),required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--seeds",type=int,default=20)
    p.add_argument("--workers",type=int,default=5)
    p.add_argument("--horizons",default="50,100,200")
    p.add_argument("--verify-against",type=Path)
    a=p.parse_args()
    print(json.dumps(run_study(a.out,sample=a.sample,seeds=a.seeds,horizons=tuple(map(int,a.horizons.split(","))),
                               workers=a.workers,verify=a.verify_against)))
