"""Compare resident public-work rosters with day trips and persistent administrative workplaces."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack
import csv
import hashlib
import json
from pathlib import Path
import platform
from tempfile import TemporaryDirectory
import time

from civsim.model import GOODS, generate_world
from civsim.regions import regionalize
from civsim.storage import canonical_line
from experiments.civic_disputes63 import HORIZONS, verify_tables, write_json, write_table
from experiments.phase6a import compressed, digest_file, emit


EXAMPLES = Path(__file__).resolve().parents[1]/"examples"
ARMS = ("A","A_fixed","B")
BASELINE = "phase6c1/baseline/checkpoints.csv"


def csv_rows(filename):
    with filename.open(encoding="utf8",newline="") as f:
        return list(csv.DictReader(f))


def historical_controls():
    proof=json.loads((EXAMPLES/"phase6c1-followup/compatibility.json").read_bytes())
    names=(BASELINE,*(f"phase6b2/study/{sample}/runs.csv" for sample in ("dev","holdout")))
    pins={name:proof["source_sha256"][name] for name in names}
    if any(digest_file(EXAMPLES/name)!=value for name,value in pins.items()):
        raise ValueError("economic control source differs from the PR 18 receipt")
    d={(int(r["seed"]),int(r["year"])):r for r in csv_rows(EXAMPLES/BASELINE)}
    controls={}
    for name in names[1:]:
        for r in csv_rows(EXAMPLES/name):
            arm={"C":"A_fixed","D":"A"}[r["arm"]]
            key=int(r["seed"]),arm,int(r["year"])
            if key in controls:
                raise ValueError("repeated control checkpoint")
            if arm=="A" and any(r[k]!=d[key[0],key[2]][k] for k in ("initial_sha256","years_sha256")):
                raise ValueError("PR 18 economic reference and original D disagree")
            controls[key]=r
    if set(controls)!={(s,arm,y) for s in range(40) for arm in ARMS[:2] for y in HORIZONS}:
        raise ValueError("incomplete historical controls")
    return controls,pins


CIVIL=("food_need","food_eaten","food_unmet","births","deaths","immigrants","emigrants",
       "exports_value","imports_value",*("produced_"+g for g in GOODS),*("production_used_"+g for g in GOODS))
END=("closing_population","closing_cash",*("private_"+g for g in GOODS),*("public_"+g for g in GOODS))


def regional_accounts(record):
    """Independently count home residents, prices paid across borders and actual stocks."""
    depots={r["region"]:r for r in record["government"]["depots"]}
    accounts={r["id"]:r for r in record["government"]["accounts"]}
    ids=[r["id"] for r in record["regions"]]
    if len(set(ids))!=len(ids) or set(depots)!=set(ids):
        raise ValueError("residential, public depot and private registers disagree")
    imports,exports=Counter(),Counter()
    for trade in record["border_market"]["trades"]:
        imports[trade["buyer"]]+=trade["value"]
        exports[trade["seller"]]+=trade["value"]
    totals={owner:Counter() for owner in accounts}
    values={}
    for row in record["regions"]:
        i,owner=row["id"],row["owner"]
        opening,closing=row["opening"],row["closing"]
        meal,vital=row["consumption"],row["demography"]
        out={k:int(vital[k]) for k in ("births","deaths","immigrants","emigrants")}
        out.update({k:int(meal[k]) for k in ("food_need","food_eaten","food_unmet")})
        if (opening["population"]!=out["food_need"] or out["food_need"]!=out["food_eaten"]+out["food_unmet"] or
            opening["population"]+out["births"]-out["deaths"]+out["immigrants"]-out["emigrants"]!=closing["population"]):
            raise ValueError("meal or resident population double counted")
        if opening["cash"]+exports[i]-imports[i]!=closing["cash"] or closing["cash"]<0:
            raise ValueError("cash transfer does not reconcile")
        out.update(closing_population=closing["population"],closing_cash=closing["cash"],
                   imports_value=imports[i],exports_value=exports[i])
        if depots[i]["owner"]!=owner:
            raise ValueError("public depot credited to a different owner")
        for g in GOODS:
            out["produced_"+g]=row["production"]["produced"][g]
            out["production_used_"+g]=row["production"]["used"][g]
            out["private_"+g]=closing["stock"][g]
            out["public_"+g]=depots[i]["closing"][g]
        if any(type(n) is not int or n<0 for n in out.values()):
            raise ValueError("negative or noninteger economic posting")
        totals[owner].update(out)
        values[i]=out
    for n,items in totals.items():
        for g in GOODS:
            if (items["private_"+g]!=accounts[n]["private_close"][g] or
                items["public_"+g]!=accounts[n]["public_close"][g]):
                raise ValueError("regional inventory totals disagree with national accounts")
    return values


DUTY = ("eligible_workers","serving","ration_food","tools_used","travel_food","enrolled","released","service_deaths","service_emigrants")
NOMINAL = ("ledger_assignments","invoice_people","unentered_invoice_people","carried_other_affiliation",
           "released_other_affiliation","enrolled_ledger","deaths_other_affiliation","emigrants_other_affiliation",
           "during_other_affiliation")
NOMINAL_END = ("closing_other_affiliation_home","closing_other_affiliation_office","closing_ledger")


def count_cells(rows):
    cells=Counter()
    for r in rows:
        key=r["home"],r["post"]
        if key in cells or type(r["count"]) is not int or r["count"]<=0:
            raise ValueError("invalid or duplicate affiliation balance")
        cells[key]=r["count"]
    return cells


def affiliation_accounts(register,service,previous):
    booked={k:count_cells(register[k]) for k in ("opening","released","enrolled","during","deaths","emigrants","closing")}
    if booked["opening"]!=previous:
        raise ValueError("previous nominal closing differs from opening")
    residence={r["id"]:r for r in service["regions"]}
    values={i:Counter(dict.fromkeys((*NOMINAL,*NOMINAL_END),0)) for i in residence}
    incoming,outgoing=Counter(),Counter()
    for r in register["assignments"]:
        h,origin,dest=r["home"],r["source"],r["destination"]
        n=r["assigned"]
        if origin!=h or residence[h]["owner"]!=residence[dest]["owner"] or not 0<=n<=r["invoice_people"]:
            raise ValueError("unattributed nominal entry")
        incoming[h,dest]+=n
        outgoing[h,origin]+=n
        values[h].update(ledger_assignments=n,invoice_people=r["invoice_people"],
                         unentered_invoice_people=r["invoice_people"]-n)
    cells=set(incoming)|set(outgoing)|set().union(*(set(c) for c in booked.values()))
    for h,p in cells:
        before,released,enrolled,during,deaths,emigrants,closing=(booked[k][h,p] for k in booked)
        if before-released+enrolled+incoming[h,p]-outgoing[h,p]!=during or during-deaths-emigrants!=closing:
            raise ValueError("affiliation row does not reconcile")
        v=values[h]
        v.update(enrolled_ledger=enrolled,closing_ledger=closing)
        if h!=p:
            v.update(carried_other_affiliation=before-released,released_other_affiliation=released,
                     during_other_affiliation=during,deaths_other_affiliation=deaths,
                     emigrants_other_affiliation=emigrants,closing_other_affiliation_home=closing)
            values[p]["closing_other_affiliation_office"]+=closing
    for i,v in values.items():
        if v["closing_ledger"]!=residence[i]["closing_roster"]:
            raise ValueError("nominal affiliation duplicated or omitted home residents")
    return values,booked["closing"]


def annual_duty(record):
    rows={}
    for r in record["service"]["regions"]:
        if (r["opening_roster"]+r["enrolled"]-r["released"]!=r["serving"]
                or r["serving"]-r["service_deaths"]-r["service_emigrants"]!=r["closing_roster"]
                or r["used"]!={"food":r["ration_food"]+r["travel_food"],"tools":r["tools_used"],"ore":0}):
            raise ValueError("annual resident roster and public payments do not close")
        rows[r["id"]]={"duty_"+k:r[k] for k in DUTY}
        rows[r["id"]]["closing_home_roster"]=r["closing_roster"]
    return rows


def accrued(previous, values, endpoints):
    for k,n in values.items():
        if k in endpoints:
            previous[k]=n
        else:
            previous[k]+=n


def policy_metrics(data,region,arm):
    if arm=="B":
        return {**data["A_fixed"][region],**data["register"][region]}
    return dict(data[arm][region])


def checkpoint(seed,year,arm,data,owners,econ_hash,register_hash,initial,controls,worlds,regions):
    common={"seed":seed,"year":year,"arm":arm}
    country=Counter()
    for i,owner in owners.items():
        values=policy_metrics(data,i,arm)
        country.update(values)
        regions.append({**common,"region":i,"owner":owner,**values})
    e="A_fixed" if arm=="B" else arm
    archive=controls[seed,e,year]
    if (initial,econ_hash[e].hexdigest())!=(archive["initial_sha256"],archive["years_sha256"]):
        raise ValueError(f"economic checkpoint differs from archived {e} for {seed}/{year}")
    if any(country[k]!=int(archive[v]) for k,v in
           (("food_eaten","food_eaten"),("food_unmet","food_deficit"),("food_need","food_need"),("closing_population","closing_population"),
            ("closing_cash","closing_cash"),("duty_tools_used","service_tools_used"),("duty_ration_food","service_ration_food"))):
        raise ValueError("aggregate economic outcomes disagree with archived source data")
    worlds.append({**common,"initial_sha256":initial,"economy_sha256":econ_hash[e].hexdigest(),
                   "affiliation_sha256":register_hash.hexdigest() if arm=="B" else "",**country})


def write_mixed(path,rows):
    # Blank cells identify metrics outside the data model of the historical controls.
    fields=dict.fromkeys(k for r in rows for k in r)
    with path.open("x",encoding="utf8",newline="") as f:
        emit(f,fields,True).writerows(rows)


def observe_cases(cases,seed,register,opening,record,values):
    from civsim.posting_engine65 import fork_affiliation
    year=record["year"]
    for r in register["assignments"]:
        h,p,n=r["home"],r["destination"],r["assigned"]
        invoice=record["service"]["moves"][r["invoice"]]
        if n and "held_entry" not in cases:
            before=hashlib.sha256(canonical_line(record)).hexdigest()
            ordinary,held=fork_affiliation(opening,record,hold=(h,h,p))
            if ordinary!=register or before!=hashlib.sha256(canonical_line(record)).hexdigest():
                raise ValueError("same-close filing intervention changed its economic source")
            variant,_=affiliation_accounts(held,record["service"],opening)
            if any(variant[i]["closing_ledger"]!=v["closing_ledger"] for i,v in values.items()):
                raise ValueError("record hold changed residence or total registered population")
            held_entries=[x for x in held["assignments"] if x["held"]]
            cases["held_entry"]={"seed":seed,"year":year,"home":h,"office":p,"source_invoice":invoice,
                                 "economic_year_sha256":before,"ordinary":ordinary,"held":held,
                                 "held_entries":held_entries,"home_closing_roster":values[h]["closing_ledger"]}
        if n<r["invoice_people"] and "not_entered" not in cases:
            cases["not_entered"]={"seed":seed,"year":year,"assignment":r,"source_invoice":invoice}
    if "carried" not in cases:
        for i,data in values.items():
            if data["carried_other_affiliation"]:
                cases["carried"]={"seed":seed,"year":year,"home":i,"values":dict(data),
                                  "opening":[r for r in register["opening"] if r["home"]==i],
                                  "closing":[r for r in register["closing"] if r["home"]==i]}
                break


def one_seed(job):
    from civsim import peace62
    from civsim.posting_engine65 import audit_households, run
    from civsim.postings65 import audit_postings
    seed,years,stage,controls=job
    out=Path(stage)/f"seed-{seed:02}"
    out.mkdir()
    world=regionalize(generate_world(seed))
    initial=hashlib.sha256(canonical_line(peace62.snapshot62(peace62.start62(world)))).hexdigest()
    owners={r.id:r.owner for r in world.regions}
    data={k:{i:Counter() for i in owners} for k in ("A","A_fixed","register")}
    econ_hash={k:hashlib.sha256() for k in ARMS[:2]}
    book_hash=hashlib.sha256()
    worlds,regions,cases=[],[],{}
    fields=("seed","year","arm","region","owner","opening_population","opening_cash",*CIVIL,*END,
            *("duty_"+k for k in DUTY),"closing_home_roster")
    with ExitStack() as stack:
        file=stack.enter_context(compressed(out/"economic-regions.csv.gz"))
        economic=emit(file,fields,True)
        raw=stack.enter_context(compressed(out/"affiliations.jsonl.gz"))
        for stream_arm in ("A","B"):
            # B publicly runs the original fixed economy once and returns an independent office register.
            e="A" if stream_arm=="A" else "A_fixed"
            previous=previous_register=None
            opening=Counter()
            for y,(record,_,register) in enumerate(run(seed,years,stream_arm),1):
                if record["year"]!=y:
                    raise ValueError("nonconsecutive economic year")
                econ_hash[e].update(canonical_line(record))
                audit_households(record,previous)
                economy=regional_accounts(record)
                duty=annual_duty(record)
                openings={r["id"]:r["opening"] for r in record["regions"]}
                for i in owners:
                    all_values={**economy[i],**duty[i]}
                    accrued(data[e][i],all_values,(*END,"closing_home_roster"))
                    economic.writerow({"seed":seed,"year":y,"arm":e,"region":i,"owner":owners[i],
                                       "opening_population":openings[i]["population"],"opening_cash":openings[i]["cash"],**all_values})
                if stream_arm=="B":
                    audit_postings(register,record["service"],previous=previous_register)
                    values,closing=affiliation_accounts(register,record["service"],opening)
                    observe_cases(cases,seed,register,opening,record,values)
                    for i,v in values.items():
                        accrued(data["register"][i],v,NOMINAL_END)
                    written=canonical_line(register)
                    raw.write(written.decode("utf8"))
                    book_hash.update(written)
                    opening=closing
                    previous_register=register
                if y in HORIZONS:
                    for result_arm in (("A",) if stream_arm=="A" else ("A_fixed","B")):
                        checkpoint(seed,y,result_arm,data,owners,econ_hash,book_hash,initial,controls,worlds,regions)
                previous=record
    write_json(out/"cases.json",cases)
    return worlds,regions


def subset_equal(original,repeat,seed):
    for name in ("runs.csv","regions.csv"):
        rows=[r for r in csv_rows(original/name) if int(r["seed"])==seed]
        if rows!=csv_rows(repeat/name):
            raise ValueError("independent sampled checkpoints differ in "+name)
    raw=f"seed-{seed:02}"
    names=("economic-regions.csv.gz","affiliations.jsonl.gz","cases.json")
    verify_tables(original/raw,repeat/raw,names)
    return [raw+"/"+n for n in names]


def run_study(out,sample,*,workers=4,verify=None):
    out=Path(out)
    if out.exists():
        raise FileExistsError(out)
    if workers<1:
        raise ValueError("workers must be positive")
    start=time.perf_counter()
    controls,pins=historical_controls()
    start_seed={"dev":0,"holdout":20}[sample]
    seeds=list(range(start_seed,start_seed+(1 if verify else 20)))
    out.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=out.parent,prefix=".office-study-") as work:
        stage=Path(work)/"result"
        stage.mkdir()
        jobs=[(s,200,stage,{k:r for k,r in controls.items() if k[0]==s}) for s in seeds]
        if len(seeds)>1 and workers>1:
            with ProcessPoolExecutor(max_workers=min(len(seeds),workers)) as pool:
                results=list(pool.map(one_seed,jobs))
        else:
            results=list(map(one_seed,jobs))
        for i,name in enumerate(("runs","regions")):
            write_mixed(stage/(name+".csv"),[r for result in results for r in result[i]])
        all_files={str(p.relative_to(stage).as_posix()):digest_file(p) for p in sorted(stage.rglob("*")) if p.is_file()}
        checked=subset_equal(Path(verify),stage,seeds[0]) if verify else []
        meta={"sample":sample,"seeds":seeds,"workers":min(workers,len(seeds)),"horizons":HORIZONS,
              "historical_controls":pins,"economic_world_years":len(seeds)*400,"nominal_register_years":len(seeds)*200,
              "archived_economic_checkpoints":len(seeds)*6,"register_checkpoints":len(seeds)*3,
              "replayed_economic_checkpoints":6 if verify else 0,"replayed_register_checkpoints":3 if verify else 0,
              "identical_seed_files":checked,"table_sha256":all_files,"python":platform.python_version(),
              "wall_seconds":time.perf_counter()-start}
        write_json(stage/"execution.json",meta)
        if out.exists():
            raise FileExistsError(out)
        stage.rename(out)
    return meta


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--sample",choices=("dev","holdout"),required=True)
    parser.add_argument("--workers",type=int,default=4)
    parser.add_argument("--verify-sample-against",type=Path)
    opt=parser.parse_args()
    print(json.dumps(run_study(opt.out,opt.sample,workers=opt.workers,verify=opt.verify_sample_against)))
