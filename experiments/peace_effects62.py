"""Independent civilian, labor and public-service incidence audit on the B1/B2 matched panels."""
import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
import csv
from fractions import Fraction
import gzip
import hashlib
import json
from math import isclose
from pathlib import Path


BASE_END=("closing_population","closing_cash","closing_service_roster",
          *("closing_"+holder+"_"+g for holder in ("public","private") for g in ("food","ore","tools")))
RATIOS={"deficit_share":("food_deficit","food_need"),"mean_support":("support_x_members","member_years"),
        "mean_discontent":("discontent_x_members","member_years"),"within_country_disparity":("within_ration_gap","food_need"),
        "mean_opening_tension":("border_tension_sum","observed_pairs"),"mean_closing_tension":("closing_tension_sum","observed_pairs"),
        "aid_fulfillment":("aid_sent","aid_approved")}
TARGETS=("C-B","D-B","D-C")
SELECT=("closing_population","food_need","food_eaten","food_deficit","deficit_share",
        "service_enrolled","service_serving","service_available","service_ration_food","service_tools_used",
        "service_travel_food","service_reassignment_out","service_reassignment_in","service_road_load",
        "service_rationed_at_station","produced_food","produced_ore","produced_tools","civil_min","civil_max","nonserving")


def check(ok,msg):
    if not ok:
        raise ValueError(msg)


def ratio(n,d):
    if not d:
        return Fraction()
    return n/d if isinstance(n,float) else Fraction(n,d)


def exact_columns(row,source,context):
    for k,n in source.items():
        if k in RATIOS or k=="within_ration_gap":
            check(isclose(float(row[k]),float(n),abs_tol=1e-7 if k=="within_ration_gap" else 3e-13,
                          rel_tol=1e-12),f"{context}: {k} ratio")
        else:
            check(int(row[k])==n,f"{context}: {k} {row[k]} != {n}")


@contextmanager
def open_csv(path):
    op=gzip.open if path.suffix==".gz" else open
    with op(path,"rt",encoding="utf-8-sig",newline="") as f:
        yield f


def meal_bounds(population,serving,eaten,rations):
    """Non-enrolled residents' consumption; public personal rations go to enrolled residents."""
    check(0<=rations<=serving<=population and rations<=eaten<=population,"resident meals outside population")
    return max(0,eaten-serving),min(population-serving,eaten-rations)


def check_small_meal_accounts():
    for p in range(9):
        for s in range(p+1):
            for r in range(s+1):
                for e in range(r,p+1):
                    possible=[civil for civil in range(p-s+1) if r<=e-civil<=s]
                    check(meal_bounds(p,s,e,r)==(min(possible),max(possible)),"civilian meal bounds")


def annual_key(r):
    return int(r["seed"]),r["arm"],int(r["year"])


def _with_ratios(v):
    return {k:ratio(v[n],v[d]) for k,(n,d) in RATIOS.items() if n in v and d in v}


def _check_files(folder,meta,names):
    for name in names:
        with (folder/name).open("rb") as f:
            check(hashlib.file_digest(f,"sha256").hexdigest()==meta["table_sha256"][name],"hash mismatch "+name)


def annual_accounts(folder,level,meta):
    id_col="region" if level=="region" else "owner"
    n=32 if level=="region" else 8
    with open_csv(folder/(level+"s.csv" if level=="region" else "countries.csv")) as stream:
        snap={(*annual_key(r),int(r[id_col])):r for r in csv.DictReader(stream)}
    horizons=set(meta["horizons"])
    arms=set(meta["arms"])
    expect=meta["seeds"]*len(arms)*len(horizons)*n
    check(len(snap)==expect,"checkpoint coverage differs")
    cols=set(next(iter(snap.values())))-{"owner","region","seed","arm","year","opening_population",*RATIOS}
    acc=sorted(cols-set(BASE_END))
    ends=sorted(cols & set(BASE_END))
    states,notes,last,first={},defaultdict(Counter),{},{}
    output,groups={},defaultdict(Counter)
    with open_csv(folder/(level+"-years.csv.gz")) as f:
        reader=csv.reader(f)
        header=next(reader)
        idx={k:i for i,k in enumerate(header)}
        ai=[(j,idx[k]) for j,k in enumerate(acc) if k!="within_ration_gap"]
        gap=acc.index("within_ration_gap"),idx["within_ration_gap"]
        ei=[idx[k] for k in ends]
        for row in reader:
            s,a,y,i=int(row[idx["seed"]]),row[idx["arm"]],int(row[idx["year"]]),int(row[idx[id_col]])
            k=s,a,i
            def val(name):
                j=idx.get(name)
                return int(row[j]) if j is not None else 0
            p=val("food_need")
            close=val("closing_population")
            crew=val("service_serving")
            enrolled=val("service_enrolled")
            end_roster=val("closing_service_roster")
            register=val("service_roster_open_years")
            if k in last:
                check(last[k]==(y-1,p,register),"broken population or registration continuity")
            else:
                check(y==1 and register==0,"missing initial annual account")
                states[k]=[0]*len(acc)
                first[k]=p
            last[k]=(y,close,end_roster)
            check(close==p+val("births")-val("deaths")+val("immigrants")-val("emigrants"),"population conservation")
            check(register+enrolled-val("service_released")==crew and
                  crew-val("service_deaths")-val("service_emigrants")==end_roster,"recruitment conservation")
            check(val("working_age")==crew+sum(val(x) for x in ("production_workers","construction_workers","soil_workers",
                                                               "project_workers","withheld_workers")),"labor conservation")
            if "service_eligible_workers" in idx:
                check(val("service_eligible_workers")==val("working_age")-val("withheld_workers") and
                      crew<=val("service_eligible_workers"),"eligible labor mismatch")
            check(p==val("food_eaten")+val("food_deficit"),"meal balance")
            if level=="region":
                lo,hi=meal_bounds(p,crew,val("food_eaten"),val("service_ration_food"))
                seated,fed,available=val("service_stationed"),val("service_rationed_at_station"),val("service_available")
                incoming=val("service_reassignment_in")-val("service_reassignment_out")
                check(seated==crew+incoming and fed==val("service_ration_food")+incoming and
                      0<=available<=fed<=seated and seated-available==val("service_unavailable")
                      and val("service_tools_used")==((available+11)//12),"station post despite unavailable supplies")
                notes[k].update(civil_min=lo,civil_max=hi,nonserving=p-crew,missing_ration=seated-fed,
                                missing_tools=fed-available,region_zero_ready=int(seated>0 and not available))
            else:
                notes[k].update(country_years=1,zero_enrollment=int(not enrolled),
                                no_new_with_roster=int(crew>0 and not enrolled),zero_roster=int(not crew),
                                zero_target=int(not val("service_target")))
            sums=states[k]
            for j,pos in ai:
                sums[j]+=int(row[pos])
            sums[gap[0]]+=float(row[gap[1]])
            if y not in horizons:
                continue
            dst=(*k[:2],y,i)
            record=snap[dst]
            rebuilt={**dict(zip(acc,sums,strict=True)),**{col:int(row[pos]) for col,pos in zip(ends,ei,strict=True)},
                     "opening_population":first[k]}
            exact_columns(record,{**rebuilt,**_with_ratios(rebuilt)},dst)
            rebuilt.update(notes[k])
            totals=groups[s,a,y,int(record["owner"]) if level=="region" else -1]
            totals.update(rebuilt)
            rebuilt.update(_with_ratios(rebuilt))
            output[dst]={metric:rebuilt.get(metric,0) for metric in SELECT}
            if level=="region":
                output[dst]["owner"]=int(record["owner"])
    check(len(output)==expect and all(v[0]==max(horizons) for v in last.values()),"incomplete annual series")
    return output,groups,cols


def _policy_check(folder,meta,country):
    counts=defaultdict(Counter)
    previous_year={}
    with open_csv(folder/"service-policy.csv.gz") as f:
        for r in csv.DictReader(f):
            s,a,y=annual_key(r)
            own=int(r["owner"])
            check(previous_year.get((s,a,own),0)+1==y,"missing or repeated country policy year")
            previous_year[s,a,own]=y
            changes=json.loads(r["adjustments_json"])
            rate=int(r["target_rate_permille"])
            q=int(r["serving"])
            available=int(r["available"])
            reference=int(r["reference_roster"])
            need,crop=int(r["prior_food_need"]),int(r["prior_crop"])
            forecast=crop*reference//(need//2) if need>=2 else 0
            real=crop*q//(need//2) if need>=2 else 0
            def value(name):
                return int(r[name])
            def signed(x,step,cap):
                return (1 if x>=0 else -1)*min(abs(x)//step,cap)
            buffer=value("population")//64
            gap=1000*max(0,buffer-value("public_food"))//buffer if buffer else 0
            base=value("food_cost_denominator")
            share=min(1000,1000*forecast//base) if base else 0
            inputs={"tension":value("max_opening_tension")//20,
                    "recent_breaches":6*min(4,value("prior_breached_directions")),
                    "trade_exposure":value("tension_weighted_import_dependence")//40,
                    "industry":value("industry_road_signal")//80,"shortage":-(value("shortage_permille")//12),
                    "farm":-(value("farm_relief_signal")//100),"consumer":-(value("consumer_relief_signal")//100),
                    "public_food_gap":-(gap//100),"opportunity":-min(12,share//4),
                    "incumbent":max(-6,min(6,value("platform_road")-value("platform_relief"))),
                    "support":signed(value("weighted_support")-500,125,4),
                    "relation":-signed(value("mean_opening_relation"),50,8)}
            adaptive=max(0,min(80,24+sum(inputs.values())))
            check(inputs==changes and gap==value("public_gap_permille") and buffer==value("public_food_buffer")
                  and share==value("foregone_share_permille") and adaptive==value("adaptive_rate_permille")
                  and rate==(24 if a=="C" else adaptive) and
                  reference==int(r["population"])//2*24//1000 and forecast==int(r["reference_foregone_food"])
                  and real==int(r["opportunity_food_estimate"]) and q-available==int(r["unavailable"]) and
                  int(r["readiness_permille"])==(1000*available//q if q else 0),"country decision differs from observations")
            for h in meta["horizons"]:
                if y<=h:
                    counts[s,a,h,own].update(policy_years=1,rate_less_24=int(rate<24),rate_equal_24=int(rate==24),
                            rate_more_24=int(rate>24),zero_rate=int(rate==0),observed_reference_cost=forecast,
                            checked_estimate=real,checked_serving=q,checked_available=available)
    check(set(counts)==set(country),"policy-country keys differ")
    by_world=defaultdict(Counter)
    for key,c in counts.items():
        check(c["policy_years"]==key[2] and c["checked_serving"]==country[key]["service_serving"]
              and c["checked_available"]==country[key]["service_available"],"country policy totals differ")
        by_world[key[:3]].update(c)
    return by_world


def _move_check(folder,meta,areas):
    road_load=Counter()
    by_region=defaultdict(Counter)
    horizons=meta["horizons"]
    with open_csv(folder/"service-moves.csv.gz") as f:
        for r in csv.DictReader(f):
            s,a,y=annual_key(r)
            home,station,owner=int(r["home"]),int(r["station"]),int(r["owner"])
            count,d,load,fee=(int(r[m]) for m in ("people","distance","road_load","travel_food"))
            path=tuple(map(int,r["tile_path"].split()))
            check(d>0 and count>0 and home!=station and len(set(path))==len(path)==d+1 and
                  all((abs(x-z)==48 or (x//48==z//48 and abs(x-z)==1)) for x,z in zip(path,path[1:])) and
                  load==2*count and fee==(load*d+99)//100,"invalid physical commute")
            lo,hi=sorted((home,station))
            road_load[s,a,y,owner,lo,hi]+=load
            for h in horizons:
                if y<=h:
                    left,right=areas[s,a,h,home],areas[s,a,h,station]
                    check(left["owner"]==right["owner"]==owner,"commute crosses border")
                    by_region[s,a,h,home].update(service_reassignment_out=count,service_road_load=load,service_travel_food=fee)
                    by_region[s,a,h,station].update(service_reassignment_in=count)
    for key,v in areas.items():
        for m in ("service_reassignment_out","service_reassignment_in","service_road_load","service_travel_food"):
            check(v[m]==by_region[key][m],"commute/region mismatch")
    with open_csv(folder/"road-years.csv.gz") as f:
        rd=csv.reader(f)
        pos={m:j for j,m in enumerate(next(rd))}
        fields=[pos[m] for m in ("works_use","supply_use","duty_use","relief_use","private_use","unused")]
        for r in rd:
            key=(int(r[pos["seed"]]),r[pos["arm"]],int(r[pos["year"]]),int(r[pos["owner"]]),int(r[pos["a"]]),int(r[pos["b"]]))
            check(int(r[pos["duty_use"]])==road_load.pop(key,0) and int(r[pos["capacity"]])==sum(int(r[j]) for j in fields),
                  "shared road capacity or public duty mismatch")
    check(not road_load,"unregistered commuter road")


def audit_stage(folder):
    meta=json.loads((folder/"execution.json").read_text(encoding="utf8"))
    detailed=meta["arms"]==["C","D"]
    paths=["countries.csv","regions.csv","country-years.csv.gz","region-years.csv.gz","runs.csv","means.csv","paired.csv"]
    _check_files(folder,meta,paths+(["service-policy.csv.gz","service-moves.csv.gz","road-years.csv.gz"] if detailed else []))
    areas,by_owner,shared=annual_accounts(folder,"region",meta)
    country,groups,_=annual_accounts(folder,"country",meta)
    with open_csv(folder/"countries.csv") as f:
        for row in csv.DictReader(f):
            key=(*annual_key(row),int(row["owner"]))
            exact_columns(row,{k:by_owner[key][k] for k in (*shared,"opening_population")},key)
            for metric in ("civil_min","civil_max","nonserving"):
                country[key][metric]=by_owner[key][metric]
    if detailed:
        _move_check(folder,meta,areas)
    pol=_policy_check(folder,meta,country) if detailed else {}
    worlds={}
    with open_csv(folder/"runs.csv") as f:
        for row in csv.DictReader(f):
            k=annual_key(row)
            raw=groups[*k,-1].copy()
            native={m:v for m,v in raw.items() if m in row}
            exact_columns(row,{**native,**_with_ratios(native)},k)
            check(set(row)-{"seed","arm","year","initial_sha256","years_sha256"}==set(native)|set(_with_ratios(native)),
                  "unverified world column")
            if detailed:
                check(pol[k]["checked_estimate"]==raw["service_opportunity_food_estimate"],"opportunity estimate mismatched")
                raw.update(pol[k])
            for own in range(8):
                raw.update({m:by_owner[*k,own][m] for m in ("civil_min","civil_max","nonserving","missing_ration",
                                                            "missing_tools","region_zero_ready")})
            raw.update(_with_ratios(raw))
            check(raw["missing_ration"]+raw["missing_tools"]==raw["service_unavailable"]
                  and raw["service_road_load"]==raw["road_duty_use"],"unavailability or round-trip incidence differs")
            worlds[k]=raw
    with open_csv(folder/"means.csv") as f:
        for row in csv.DictReader(f):
            a,y=row["arm"],int(row["year"])
            selected=[v for (s,arm,h),v in worlds.items() if (arm,h)==(a,y)]
            check(len(selected)==meta["seeds"],"incomplete means")
            for m,value in row.items():
                if m in ("arm","year","seeds"):
                    continue
                v=ratio(sum(d["food_deficit"] for d in selected),sum(d["food_need"] for d in selected)) if m=="pooled_deficit_share" else sum(d[m] for d in selected)/len(selected)
                check(isclose(float(v),float(value),abs_tol=3e-12,rel_tol=1e-12),"mean mismatch "+m)
    return meta,worlds,country,areas


def audit_matched(b1,b2):
    ma,wa,ca,ra=audit_stage(b1)
    mb,wb,cb,rb=audit_stage(b2)
    check(all(ma[k]==mb[k] for k in ("sample","first_seed","seeds","horizons")) and ma["arms"]==["A","B"]
          and mb["arms"]==["C","D"] and mb["b1_reference_runs_sha256"]==ma["table_sha256"]["runs.csv"],
          "unmatched stages")
    worlds={**wa,**wb}
    for directory in (b1,b2):
        with open_csv(directory/"paired.csv") as f:
            for row in csv.DictReader(f):
                s,y=int(row["seed"]),int(row["year"])
                a,b=row["contrast"].split("-")
                out={}
                for m in row.keys()-{"seed","year","contrast"}:
                    # Only the published additional service fields are structurally zero for A and B.
                    for arm in (a,b):
                        check(m in worlds[s,arm,y] or (arm in ("A","B") and (m.startswith("service_") or
                              m=="closing_service_roster")),"absent non-service raw metric "+m)
                    out[m]=worlds[s,a,y].get(m,0)-worlds[s,b,y].get(m,0)
                exact_columns(row,out,(s,y,a,b))
    return {"meta":mb,"worlds":worlds,"countries":{**ca,**cb},"regions":{**ra,**rb}}


def fork_examples(archive=None):
    from civsim.model import generate_world
    from civsim.peace62 import start62, step62, fork_recruit62, snapshot62
    from civsim.regions import regionalize
    from civsim.storage import canonical_line
    sim=start62(regionalize(generate_world(0)))
    archived={} if archive is None else {r["year"]:r for r in json.loads((archive/"summary.json").read_text(encoding="utf8"))}
    cases=[]
    for year in (1,2,3):
        if year==2:
            step62(sim,year,"D")
            continue
        pre=canonical_line(snapshot62(sim))
        normal,hold=fork_recruit62(sim,year,"D")
        check(pre==canonical_line(snapshot62(sim)) and normal==step62(sim,year,"D"),"recruitment fork changed baseline")
        check(normal["diplomacy"]["countries"]==hold["diplomacy"]["countries"],"fork did not share political observations")
        if archive:
            row=archived[year]
            for key,blob in (("opening_sha256",pre),("ordinary_sha256",canonical_line(normal)),
                             ("held_sha256",canonical_line(hold))):
                check(hashlib.sha256(blob).hexdigest()==row[key],"fork archive digest mismatch")
            with (archive/row["file"]).open("rb") as f:
                check(hashlib.file_digest(f,"sha256").hexdigest()==row["file_sha256"],"fork file digest mismatch")
        amounts=[]
        for r in (normal,hold):
            areas=r["regions"]
            staff=r["service"]["regions"]
            values={k:sum(i[k] for i in staff) for k in ("enrolled","serving","available","ration_food","tools_used")}
            values.update({g:sum(i["production"]["produced"][g] for i in areas) for g in ("food","ore","tools")})
            values["meals"]=[i["consumption"]["food_eaten"] for i in areas]
            values["food_eaten"]=sum(values["meals"])
            values["population"]=sum(i["closing"]["population"] for i in areas)
            amounts.append(values)
        cases.append((year,*amounts))
    return cases


def fmt(x,digits=1):
    return format(float(x),f",.{digits}f")


def table(headers,rows):
    return "\n".join("| "+" | ".join(map(str,v))+" |" for v in [headers,["---"]*len(headers),*rows])


def arms(data,arm,year):
    return [row for (seed,a,h),row in sorted(data["worlds"].items()) if (a,h)==(arm,year)]


def average(rows,metric):
    return sum(r.get(metric,0) for r in rows)/len(rows)


def avg_ratio(rows,n,d):
    return sum(ratio(r.get(n,0),r.get(d,0)) for r in rows)/len(rows)


def trends(values):
    return "/".join(str(sum(fn(x) for x in values)) for fn in (lambda x:x>0,lambda x:x==0,lambda x:x<0))


def paired(data,level,high,low,y,field):
    return [(v[field]-data[level][(s,low,h,*idx)][field],s,*idx) for (s,a,h,*idx),v in data[level].items()
            if h==y and a==high]


def render(samples,cases):
    roster,service,comparisons,real,politics,labor,signals,coverage,bounds,local=[],[],[],[],[],[],[],[],[],[]
    findings=[]
    for label,data in samples:
        for y in data["meta"]["horizons"]:
            for arm in ("B","C","D"):
                rr=arms(data,arm,y)
                mean=lambda metric:average(rr,metric)
                roster.append([label,y,arm,fmt(mean("closing_population")),fmt(100*mean("deficit_share"),3),
                               fmt(mean("closing_service_roster")),fmt(mean("service_enrolled")),fmt(mean("service_released")),
                               fmt(mean("service_deaths")),fmt(mean("service_emigrants"))])
                if arm!="B":
                    service.append([label,y,arm,*(fmt(mean(k)) for k in ("service_serving","service_available")),
                        fmt(100*avg_ratio(rr,"service_available","service_serving"),1),
                        *(fmt(mean(k)) for k in ("missing_ration","missing_tools","service_ration_food","service_tools_used",
                                                 "service_reassignment_out","service_travel_food","service_road_load"))])
                for r in rr:
                    check(r["civil_min"]<=r["civil_max"]<=r["nonserving"] and
                          r["civil_min"]<=r["food_eaten"]-r["service_ration_food"],"private meal bounds")
                bounds.append([label,y,arm,fmt(mean("food_eaten")),fmt(mean("food_eaten")-mean("service_ration_food")),
                    fmt(mean("nonserving")),fmt(mean("civil_min")),fmt(mean("civil_max")),
                    fmt(100*avg_ratio(rr,"civil_min","nonserving"),3)+"–"+fmt(100*avg_ratio(rr,"civil_max","nonserving"),3)])
                if y==200 and arm!="B":
                    denom=int(sum(r["country_years"] for r in rr))
                    signals.append([label,arm,denom,*(fmt(sum(r[k] for r in rr),0) for k in
                        ("rate_less_24","rate_equal_24","rate_more_24","zero_rate","zero_target","zero_enrollment","no_new_with_roster",
                         "zero_roster","service_undersupplied_country_years","service_zero_available_country_years"))])
            for pair in TARGETS:
                a,b=pair.split("-")
                aa,bb=arms(data,a,y),arms(data,b,y)
                delta=lambda m:average(aa,m)-average(bb,m)
                population=[d for d,*_ in paired(data,"worlds",a,b,y,"closing_population")]
                scarcity=[-d for d,*_ in paired(data,"worlds",a,b,y,"deficit_share")]
                comparisons.append([label,y,pair,fmt(delta("closing_population")),trends(population),fmt(delta("food_eaten")),
                                    fmt(delta("food_deficit")),fmt(100*delta("deficit_share"),5),trends(scarcity)])
                real.append([label,y,pair,*(fmt(delta(k)) for k in
                         ("service_opportunity_food_estimate","produced_food","produced_ore","produced_tools",
                          "aid_sent","aid_received","foreign_in_food"))])
                labor.append([label,y,pair,*(fmt(delta(k)) for k in ("working_age","production_workers","construction_workers",
                    "soil_workers","project_workers","withheld_workers","service_serving"))])
                politics.append([label,y,pair,*(fmt(delta(k),5) for k in ("mean_support","mean_discontent",
                                "participants","active_group_years","mean_opening_tension","mean_closing_tension"))])
                if y==200:
                    for level in ("worlds","countries","regions"):
                        dp=paired(data,level,a,b,y,"closing_population")
                        ds=paired(data,level,a,b,y,"deficit_share")
                        coverage.append([label,pair,{"worlds":"세계","countries":"국가","regions":"지역"}[level],len(dp),
                                         trends([x[0] for x in dp]),trends([-x[0] for x in ds])])
                        for which,row in (("최소",min(ds)),("최대",max(ds))):
                            v,seed,*index=row
                            hi=data[level][seed,a,y,*index]
                            lo=data[level][seed,b,y,*index]
                            local.append([label,pair,{"worlds":"세계","countries":"국가","regions":"지역"}[level],which,
                                seed,index[0] if index else "—",hi["closing_population"]-lo["closing_population"],
                                hi["food_eaten"]-lo["food_eaten"],fmt(100*v,5)])
        if 200 in data["meta"]["horizons"]:
            base,fixed,adaptive=(arms(data,arm,200) for arm in ("B","C","D"))
            def diff(lhs,rhs,name,scale=1):
                digits=5 if scale==100 else 1
                n=(average(lhs,name)-average(rhs,name))*scale
                return ("+" if n>0 else "")+fmt(n,digits)
            findings.append(f"**{label} 20개 시드, 200년.** 고정 정원 C와 B의 기말 인구 차이는 "
                            f"{diff(fixed,base,'closing_population')}명, 누적 부족률 차이는 {diff(fixed,base,'deficit_share',100)}%p였다. "
                            f"적응형 D와 B의 차이는 각각 {diff(adaptive,base,'closing_population')}명과 "
                            f"{diff(adaptive,base,'deficit_share',100)}%p였다. D에서는 세계당 {fmt(average(adaptive,'service_serving'),0)} 복무 인년 중 "
                            f"{fmt(100*avg_ratio(adaptive,'service_available','service_serving'),1)}%가 급식·도구 요건을 충족했다. "
                            f"누적 근무 가능 인원은 C {fmt(average(fixed,'service_available'),0)}인년, D {fmt(average(adaptive,'service_available'),0)}인년이었다. "
                            f"C 대비 D의 실제 누적 식량 생산 차이는 {diff(adaptive,fixed,'produced_food')}단위였다.")
    fork_rows=[]
    for year,n,h in cases:
        differences=[i-j for i,j in zip(n["meals"],h["meals"],strict=True)]
        fork_rows.append([year,*(str(n[k])+" / "+str(h[k]) for k in ("enrolled","serving","available","ration_food","tools_used")),
                          *(n[k]-h[k] for k in ("food","ore","tools","food_eaten","population")),trends(differences)])
    return "\n\n".join([
        "# 평시 공공복무가 주민 식사와 생산에 미친 영향",
        "B는 공공창고 간 수송을 사용하는 기준 경로다. C는 여기에 고정 정원 복무를, D는 경제·정치·대외 관측에 따라 정원을 조절하는 복무를 더한다. 개발 0–19와 별도 검증 20–39에서 각 시드의 같은 출발점을 짝지었다. 기말 인구와 명부는 해당 연도 말 상태이고 나머지 수량은 1년부터 그 시점까지 누계다. 표의 수치는 별도 표시가 없으면 세계 하나당 시드 산술평균이다. 부족률은 각 세계의 누적 미충족 식량을 누적 필요로 나눈 뒤 평균한다.",
        *findings,
        "## 인구와 주민 식사",
        table(("표본","년","비교","기말 인구 Δ","인구 ↑/=/↓","섭취 Δ","부족량 Δ","부족률 Δ %p","부족률 개선/=/악화"),comparisons),
        "인구·필요량 자체가 변하므로 섭취 누계와 부족률은 따로 해석한다. 세계 전체의 상쇄는 개별 국가·지역의 개선을 보장하지 않는다. 아래 표는 같은 시드 안에서 모든 국가·지역 ID를 각각 짝지은 200년 비교다.",
        table(("표본","비교","단위","짝 수","인구 ↑/=/↓","부족률 개선/=/악화"),coverage),
        "## 복무 명부와 근무 요건",
        table(("표본","년","정책","인구","부족률 %","기말 명부","신규 등록","일반 해제","명부 사망","명부 전출"),roster),
        "명부는 주민의 부분집합이다. 사망·전출은 주민 통계에도 포함되며, 전출은 기존 명부에서 빠지는 인원이다. 아래 단위는 복무 및 근무 가능 인년이다. 식량 미확보는 근무지 인원에서 급식 확보 인원을 뺀 값이고, 도구 미확보는 그중 도구까지 지급할 수 없었던 인원이다. 두 값의 합이 근무 요건 미충족 인년이다. 지급 도구는 실제 소모량, 식사는 거주지에서 주민의 평상시 식사로 이전한 실물이다. 출퇴근자 한 명은 도로 한도 두 단위를 쓰며 통행 식량은 실제 소모된다.",
        table(("표본","년","정책","복무","근무 가능","가능 %","급식 미확보","도구 미확보","배식","도구","출퇴근 인원","통행 식량","도로 사용"),service),
        "200년 전국가·연도 빈도. 정원은 적격 주민 노동자 천 명당 비율이다. 신규 등록 0인 해에도 기존 명부가 남을 수 있다. 미충족 국년은 복무 인원이 근무 가능 인원보다 많은 국가·연도, 전원 미충족은 복무가 한 명 이상이면서 가능 인원이 0인 국가·연도다.",
        table(("표본","정책","국년","비율<24","=24",">24","비율0","목표인원0","신규0","기존만 복무","복무0","미충족","전원 미충족"),signals),
        "## 노동·기회비용과 실제 생산",
        "각 비교의 기회비용 Δ는 전년 식량 생산 × 올해 실제 복무 인원 ÷ 전년 추정 노동자에서 각 국가의 정수 몫을 합산한 관측 기반 추정치다. 경로 사이의 실현 생산은 토양·농지, 기술, 가계·창고 재고, 노동 구성, 가격과 거래 및 인구 변화를 함께 반영한다. Δ값을 식량 원장에서 추가 차감하지 않는다. 해외 수입 식량은 민간 수입이며 원조 수취와 구분했다.",
        table(("표본","년","비교","기회비용 추정 Δ","식량 생산 Δ","광석 생산 Δ","도구 생산 Δ","원조 발송 Δ","원조 수취 Δ","해외 식량 수입 Δ"),real),
        "각 시점까지의 노동 인년 차이. 민간 생산·설비건설·토양관리·공공사업·집단행동에 따른 노동 보류·복무를 합하면 전체 노동자 수다. 공공복무가 불완전 급식·도구 상태여도 해당 복무 인년은 민간 생산과 공공사업에 중복 배정되지 않는다.",
        table(("표본","년","비교","노동자 Δ","민간 생산 Δ","설비건설 Δ","토양관리 Δ","공공사업 Δ","노동 보류 Δ","복무 Δ"),labor),
        "## 비복무 주민이 먹은 양의 범위",
        "지역·연도별로 주민 P명, 복무 S명, 전체 실제 식사 E, 복무자 귀속 공공배식 R을 관측한다. 한 명은 한 단위까지 먹는다. 비복무자 식사는 최대(0, E−S) 이상, 최소(P−S, E−R) 이하다. 각 지역·연도의 하한과 상한을 따로 합했다. ‘공공배식 제외’ 열에는 민간 식량을 먹은 미배식 복무자도 포함될 수 있다. 비복무 인년의 식사율은 시드별로 나눈 뒤 평균했으며, 각 경로의 비복무 인원 수도 함께 달라진다.",
        table(("표본","년","정책","전체 섭취","복무 공공배식 제외","비복무 인년","섭취 하한","섭취 상한","비복무 식사율 범위 %"),bounds),
        "## 국내 정치와 이웃 국가 간 긴장",
        "대표 집단 지지와 불만은 구성원 인년으로 가중한 모형 점수다. 참가자는 실제 집단행동 참가 인년, 활동은 집단·연도다. 긴장은 관측된 모든 국가쌍의 연초·연말 점수를 기간 평균한 값이며 양쪽 국가의 관측을 같은 방식으로 분모에 넣었다. 복무와 함께 식사·세금·교역 등도 달라지므로 여기서는 경로 전체의 차이를 측정한다.",
        table(("표본","년","비교","지지 Δ","불만 Δ","참가 인년 Δ","활동 집단년 Δ","연초 긴장 Δ","연말 긴장 Δ"),politics),
        "## 반례와 같은 연초의 모집 보류",
        "아래는 각 표본·비교에서 200년 누적 부족률 차이의 최솟값과 최댓값을 보인 실제 세계·국가·지역이다. 동률에서는 (차이, 시드, ID) 튜플의 최솟값 또는 최댓값을 골랐다. 이 극단 사례에 전체 표본의 가중치를 부여하지 않았다.",
        table(("표본","비교","단위","부족률 Δ 순위","시드","ID","기말 인구 Δ","섭취 Δ","부족률 Δ %p"),local),
        "개발 시드 0의 같은 연초에서 D 신규 모집만 한 해 보류했다. 기존 인원의 유지·해제와 다른 결정은 원래 규칙대로 계산된다. 아래 슬래시는 정상 / 보류, Δ는 정상에서 보류를 뺀 값이다. 개발 경로를 열어본 뒤 선택한 비교이며 검증 표본에는 적용하지 않았다.",
        table(("년","등록","복무","근무 가능","배식","도구","식량 생산 Δ","광석 Δ","도구 Δ","섭취 Δ","기말 인구 Δ","지역 섭취 ↑/=/↓"),fork_rows),
        "1년에는 자원이 없어 새 복무자가 근무 요건을 충족하지 못하고 일부 지역의 식사가 줄었다. 3년에는 실제 근무 가능 인원이 늘고 작물 생산이 줄었지만 32개 지역 모두 당년 실제 식사가 같았다. 근무 가능은 모형 속 자원 충족 지표이며 별도 생산수입·외교 보상을 자동 지급하지 않는다.",
        "## 재현과 검산",
        "공식 두 단계의 dev·holdout 디렉터리에 대해 읽은 원자료의 SHA-256, 지역·국가의 모든 누계/기말 열, 지역→국가→세계 합계, 연간 인구·명부·노동·식사 보존, 정원 가감식, 개별 출퇴근과 공동 도로 한도, 전체 평균·짝차 표를 검산했다. 비율·가중 식량격차는 부동소수점 허용 오차 내에서, 사람·재화·노동은 정수로 대조했다. 개인별 식사 기록이 없어 미배식 복무자의 민간 식사를 특정할 수 없다. 복무자의 사망·전출은 주민 집단에서 비례 배정한 장부 수량이다.",
        "`python -m experiments.peace_effects62 --b1 examples/phase6b1/study --b2 examples/phase6b2/study`",
        "[B1 원자료](../examples/phase6b1/study/README.md) · [B2 원자료](../examples/phase6b2/study/README.md) · [같은 연초 모집 비교 원장](../examples/phase6b2/forks/summary.json) · [복무 규칙](service62.md) · [독립 검산 도구](../experiments/peace_effects62.py)"
    ])+"\n"


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--b1",type=Path,default=Path("examples/phase6b1/study"))
    parser.add_argument("--b2",type=Path,default=Path("examples/phase6b2/study"))
    parser.add_argument("--out",type=Path)
    opt=parser.parse_args()
    check_small_meal_accounts()
    samples=[]
    for name,label,first in (("dev","개발",0),("holdout","검증",20)):
        data=audit_matched(opt.b1/name,opt.b2/name)
        m=data["meta"]
        check((m["first_seed"],m["seeds"],m["horizons"])==(first,20,[50,100,200]),"unexpected sample")
        samples.append((label,data))
    archive=opt.b2.parent/"forks"
    report=render(samples,fork_examples(archive if archive.exists() else None))
    if opt.out:
        with opt.out.open("x",encoding="utf8",newline="\n") as f:
            f.write(report)
    else:
        print(report,end="")


if __name__=="__main__":
    main()
