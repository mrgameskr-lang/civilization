"""Retrospective reconciliation of civilian household and public accounts from the 6.0B2 archive."""
import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from fractions import Fraction
from itertools import groupby
from pathlib import Path
from tempfile import TemporaryDirectory


YEARS=(50,100,200)
INPUTS=("region-years.csv.gz","country-years.csv.gz","road-years.csv.gz","service-moves.csv.gz","runs.csv")
ROAD=("works_use","supply_use","duty_use","relief_use","private_use","unused","capacity")
END=("closing_population","closing_service_roster")
PEOPLE=("food_need","food_eaten","food_deficit","food_spoiled","births","deaths","emigrants","immigrants",
        "working_age","project_workers","production_workers","construction_workers","soil_workers","withheld_workers")
DUTY=("service_serving","service_ration_food","service_available","service_unavailable","service_tools_used",
      "service_travel_food","service_reassignment_in","service_reassignment_out","service_road_load",
      "service_stationed","service_rationed_at_station","service_roster_open_years","service_enrolled","service_released",
      "service_deaths","service_emigrants","service_eligible_workers")
FISCAL=("aid_sent","aid_received","aid_freight_food","aid_handling_food","internal_aid_freight_food","relief_food",
        "levy_handling_food","public_relief_freight_food","public_works_freight_food","public_spoil_food",
        "depot_freight_food","trade_freight_food","private_freight_food")
GOODS=("food","ore","tools")
STOCK=tuple(k+"_"+g for g in GOODS for k in ("public_transfer_in","public_transfer_out","works_used","levied",
      "produced","production_used","meal_used","foreign_in","foreign_out","private_transfer_in","private_transfer_out"))
SHARED=PEOPLE+DUTY+FISCAL+STOCK
BALANCES=tuple(k+"_"+g for k in ("opening_public","closing_public","closing_private") for g in GOODS)
PUBLISH=("food_need","food_eaten","food_deficit","food_spoiled","service_serving","service_ration_food","service_available",
         "service_tools_used","service_enrolled","service_released","service_deaths","service_emigrants",
         "service_reassignment_out","service_travel_food","service_road_load","working_age","project_workers",
         "production_workers","construction_workers","soil_workers","withheld_workers","produced_food","produced_tools",
         "aid_sent","aid_received","aid_freight_food","aid_handling_food","internal_aid_freight_food","relief_food",
         "public_transfer_in_food","public_transfer_out_food","works_used_tools","public_works_freight_food")
DERIVED=("unprovided_food","unprovided_tools","roster_gap_with_resident_shortfall","roster_gap_with_full_meals",
         "regions_with_both","regions_with_roster_gap_only","regions_with_resident_shortfall_only","regions_with_neither",
         "nonparticipant_person_years","nonparticipant_eaten_min","nonparticipant_eaten_max","resident_meals_without_public_ration")
RATES={"public_rations_per_registered":("service_ration_food","service_serving"),
       "both_receipts_per_registered":("service_available","service_serving"),
       "resident_meals_per_need":("food_eaten","food_need"),
       "nonparticipant_meals_lower":("nonparticipant_eaten_min","nonparticipant_person_years"),
       "nonparticipant_meals_upper":("nonparticipant_eaten_max","nonparticipant_person_years")}


def require(condition,message):
    if not condition:
        raise ValueError(message)


def regional_account(r):
    """Rebuild physical receipts, then distinguish household meals from public transfers."""
    p,e,s=r["food_need"],r["food_eaten"],r["service_serving"]
    moved=r["service_reassignment_in"]-r["service_reassignment_out"]
    ration,got=r["service_ration_food"],r["service_available"]
    stock={g:r["opening_public_"+g]-r["works_used_"+g]+r["public_transfer_in_"+g]
           -r["public_transfer_out_"+g] for g in GOODS}
    stock["food"]-=r["public_works_freight_food"]+r["depot_freight_food"]
    require(min(stock.values())>=0,"public stock before personal meals")
    require(ration==min(s,stock["food"]) and 0<=ration<=e<=p and e+r["food_deficit"]==p,"food transfer or resident meals")
    require(r["working_age"]==p//2 and r["service_eligible_workers"]==p//2-r["withheld_workers"]
            and r["working_age"]==s+sum(r[k] for k in ("production_workers","construction_workers","soil_workers",
                                                       "withheld_workers","project_workers")),"worker balance")
    require(r["service_roster_open_years"]+r["service_enrolled"]-r["service_released"]==s and
            s-r["service_deaths"]-r["service_emigrants"]==r["closing_service_roster"] and
            p+r["births"]-r["deaths"]-r["emigrants"]+r["immigrants"]==r["closing_population"],"resident register")
    require(r["service_stationed"]==s+moved and r["service_rationed_at_station"]==ration+moved and
            got==min(ration+moved,12*stock["tools"]) and r["service_tools_used"]==(got+11)//12 and
            r["service_unavailable"]==s+moved-got and got>=0,"tool receipt or commuter not reconciled")
    gap=s-ration
    short=r["food_deficit"]>0
    return dict(unprovided_food=gap,unprovided_tools=ration+moved-got,
                roster_gap_with_resident_shortfall=gap if short else 0,roster_gap_with_full_meals=0 if short else gap,
                regions_with_both=int(gap>0 and short),regions_with_roster_gap_only=int(gap>0 and not short),
                regions_with_resident_shortfall_only=int(not gap and short),regions_with_neither=int(not gap and not short),
                nonparticipant_person_years=p-s,nonparticipant_eaten_min=max(0,e-s),
                nonparticipant_eaten_max=min(p-s,e-ration),resident_meals_without_public_ration=e-ration)


def year_end(r,prior):
    """Return inferred relief issued by the depot; recipients are posted separately in the archive."""
    public={g:r["opening_public_"+g]+r["levied_"+g]-r["works_used_"+g]+r["public_transfer_in_"+g]
            -r["public_transfer_out_"+g] for g in GOODS}
    public["food"]+=r["aid_received"]-sum(r[k] for k in ("aid_sent","aid_freight_food","public_works_freight_food",
        "depot_freight_food","service_ration_food","service_travel_food","levy_handling_food","public_relief_freight_food","public_spoil_food"))
    public["tools"]-=r["service_tools_used"]
    issued=public["food"]-r["closing_public_food"]
    require(issued>=0 and all(public[g]==r["closing_public_"+g] for g in ("ore","tools")),"public goods balance")
    require(r["meal_used_food"]==r["food_eaten"]+r["food_spoiled"],"resident meals or spoilage")
    if prior is None:
        require(r["year"]==1 and r["service_roster_open_years"]==0 and all(r["opening_public_"+g]==0 for g in GOODS),
                "opening archive balance")
    else:
        require(r["year"]==prior["year"]+1 and r["food_need"]==prior["closing_population"] and
                r["service_roster_open_years"]==prior["closing_service_roster"] and
                all(r["opening_public_"+g]==prior["closing_public_"+g] for g in GOODS),"broken annual continuity")
        for g in GOODS:
            net=r["produced_"+g]-r["production_used_"+g]-r["meal_used_"+g]-r["levied_"+g]
            net+=r["private_transfer_in_"+g]-r["private_transfer_out_"+g]+r["foreign_in_"+g]-r["foreign_out_"+g]
            if g=="food":
                net+=r["relief_food"]+r["service_ration_food"]-r["trade_freight_food"]-r["private_freight_food"]
            require(prior["closing_private_"+g]+net==r["closing_private_"+g],"private stock "+g)
    return issued


def check_road(row,commute):
    require(min(row[m] for m in ROAD)>=0 and row["capacity"]==sum(row[m] for m in ROAD[:-1])
            and row["duty_use"]==commute,"shared road receipts")


def summarize_rates(rows,n,d):
    valid=[(r[n],r[d]) for r in rows if r[d]]
    if not valid:
        return None,None,0
    return (sum(Fraction(x,y) for x,y in valid)/len(valid),Fraction(sum(x for x,y in valid),sum(y for x,y in valid)),len(valid))


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f,"sha256").hexdigest()


def rows(path,fields):
    op=gzip.open if path.suffix==".gz" else open
    with op(path,"rt",encoding="utf-8-sig",newline="") as f:
        reader=csv.reader(f)
        header=next(reader)
        labels=("seed","arm","year",*fields)
        ix=[header.index(k) for k in labels]
        for raw in reader:
            vals=[raw[j] for j in ix]
            numbers=list(map(int,vals[2:]))
            require(min(numbers)>=0,"negative physical entry in "+path.name)
            yield dict(zip(labels,(int(vals[0]),vals[1],*numbers),strict=True))


def key(r):
    return r["seed"],r["arm"],r["year"]


def groups(path,fields):
    return groupby(rows(path,fields),key=key)


def sample(source,name,first):
    folder=source/name
    meta=json.loads((folder/"execution.json").read_text(encoding="utf8"))
    require((meta["first_seed"],meta["seeds"],meta["arms"],meta["horizons"])==(first,20,["C","D"],list(YEARS)),"unexpected sample")
    hashes={f:digest(folder/f) for f in INPUTS}
    require(all(meta["table_sha256"][f]==h for f,h in hashes.items()),"archived file digest differs")
    road_load=Counter()
    commuters=defaultdict(Counter)
    for r in rows(folder/INPUTS[3],("home","station","owner","distance","people","road_load","travel_food")):
        k=key(r)
        home,station=sorted((r["home"],r["station"]))
        q=r["people"]
        require(q>0 and home!=station and r["distance"]>0 and r["road_load"]==2*q and
                r["travel_food"]==(2*q*r["distance"]+99)//100,"commuter receipt")
        road_load[*k,r["owner"],home,station]+=2*q
        commuters[*k,r["owner"],r["home"]].update(service_reassignment_out=q,service_road_load=2*q,service_travel_food=r["travel_food"])
        commuters[*k,r["owner"],r["station"]].update(service_reassignment_in=q)
    archive={key(r):r for r in rows(folder/INPUTS[4],(*PUBLISH,*END,*("road_"+k for k in ROAD)))}
    regional=groups(folder/INPUTS[0],("owner","region",*SHARED,*END,*BALANCES))
    national=groups(folder/INPUTS[1],("owner",*SHARED,*END,*("road_"+k for k in ROAD)))
    roads=groups(folder/INPUTS[2],("owner","a","b",*ROAD))
    past={}
    accumulated=defaultdict(Counter)
    checkpoints=[]
    count=Counter()
    history={}
    for (ky,local),(kn,countries),(ke,edges) in zip(regional,national,roads,strict=True):
        require(ky==kn==ke,"archive group alignment")
        seed,arm,y=ky
        require(first<=seed<first+20 and arm in ("C","D") and y==history.get((seed,arm),0)+1,"unexpected year or identity")
        history[seed,arm]=y
        subtotal=defaultdict(Counter)
        derived=Counter()
        unique=set()
        for r in local:
            i,n=r["region"],r["owner"]
            require(i not in unique and 0<=i<32 and 0<=n<8,"duplicate region")
            unique.add(i)
            derived.update(regional_account(r))
            posted=commuters.pop((*ky,n,i),Counter())
            require(all(r[m]==posted[m] for m in ("service_reassignment_in","service_reassignment_out","service_road_load",
                                                  "service_travel_food")),"home commuter debit or receipt")
            regkey=(seed,arm,i)
            subtotal[n]["relief_issued_inferred"]+=year_end(r,past.get(regkey))
            past[regkey]=r
            for m in (*SHARED,*END):
                subtotal[n][m]+=r[m]
            count["region_years"]+=1
        require(len(unique)==32,"region coverage")
        edge_seen=set()
        for e in edges:
            road=(e["owner"],e["a"],e["b"])
            require(road not in edge_seen and e["a"]<e["b"],"duplicate road")
            edge_seen.add(road)
            check_road(e,road_load.pop((*ky,*road),0))
            for m in ROAD:
                subtotal[e["owner"]]["road_"+m]+=e[m]
            count["road_years"]+=1
        issued=0
        seen=set()
        world=Counter()
        for r in countries:
            n=r["owner"]
            require(n not in seen and 0<=n<8,"duplicate country")
            seen.add(n)
            v=subtotal[n]
            require(all(v[m]==r[m] for m in (*SHARED,*END,*("road_"+k for k in ROAD))),"country disagrees with regions/roads")
            require(v["relief_issued_inferred"]==r["relief_food"] and r["service_reassignment_out"]==r["service_reassignment_in"],
                    "domestic relief or commuting crosses accounts")
            issued+=v["relief_issued_inferred"]
            for m in (*PUBLISH,*END,*("road_"+k for k in ROAD)):
                world[m]+=r[m]
            count["country_years"]+=1
        require(seen==set(range(8)) and world["aid_sent"]==world["aid_received"]+world["aid_handling_food"] and
                world["public_transfer_in_food"]==world["public_transfer_out_food"] and world["service_road_load"]==world["road_duty_use"] and
                world["service_serving"]==world["service_available"]+derived["unprovided_food"]+derived["unprovided_tools"],"world closure")
        count["world_years"]+=1
        total=accumulated[seed,arm]
        total.update(world)
        total.update(derived)
        total["relief_issued_inferred"]+=issued
        if y in YEARS:
            values=dict(total)
            values.update({m:world[m] for m in END})
            check=archive.pop(ky)
            require(all(values[m]==v for m,v in check.items() if m not in ("arm","seed","year")),"checkpoint mismatch")
            checkpoints.append(dict(sample=name,seed=seed,arm=arm,year=y,**values))
    require(not commuters and not road_load and not archive and count["world_years"]==8000 and
            len(history)==40 and set(history.values())=={200},"incomplete archive")
    return checkpoints,dict(count),hashes


def summaries(seeds):
    result=[]
    for name in ("dev","holdout","all"):
        for arm in ("C","D"):
            for year in YEARS:
                rr=[r for r in seeds if (name=="all" or r["sample"]==name) and (r["arm"],r["year"])==(arm,year)]
                out={"sample":name,"arm":arm,"year":year,"seeds":len(rr)}
                for m in (*PUBLISH,*END,*DERIVED,"relief_issued_inferred",*("road_"+k for k in ROAD)):
                    out[m]=sum(r[m] for r in rr)
                for rate,(n,d) in RATES.items():
                    mean,pool,nseed=summarize_rates(rr,n,d)
                    out[rate+"_mean"]="" if mean is None else f"{float(mean):.12f}"
                    out[rate+"_pooled"]="" if pool is None else f"{float(pool):.12f}"
                    out[rate+"_seeds"]=nseed
                result.append(out)
    return result


def archived_examples(folder):
    index=json.loads((folder/"summary.json").read_text(encoding="utf8"))
    cases=[]
    for entry in index:
        year=entry["year"]
        require(entry["seed"]==0 and year in (1,3) and entry["arm"]=="D","unexpected archived example")
        path=folder/entry["file"]
        require(digest(path)==entry["file_sha256"],"fork archive")
        with gzip.open(path,"rb") as stream:
            for label,blob in zip(("ordinary","held"),stream,strict=True):
                require(hashlib.sha256(blob).hexdigest()==entry[label+"_sha256"],"archived year digest")
                log=json.loads(blob)
                require(log["year"]==year and log["service"]["recruit"]==(label=="ordinary"),"archived condition")
                residents=log["regions"]
                staff=log["service"]["regions"]
                meals={r["id"]:r["consumption"]["food_eaten"] for r in residents}
                rec=dict(year=year,branch=label,enrolled=sum(r["enrolled"] for r in staff),registered=sum(r["serving"] for r in staff),
                         rations=sum(r["ration_food"] for r in staff),tools_used=sum(r["tools_used"] for r in staff),
                         travel_food=sum(r["travel_food"] for r in staff),food_produced=sum(r["production"]["produced"]["food"] for r in residents),
                         actual_meals=sum(meals.values()),closing_population=sum(r["closing"]["population"] for r in residents),
                         household_meals_by_region=list(dict(sorted(meals.items())).values()))
                require(rec["actual_meals"]==entry[label]["eaten"] and rec["rations"]==entry[label]["service"]["ration_food"],"example summary")
                cases.append(rec)
    require({(r["year"],r["branch"]) for r in cases}=={(y,b) for y in (1,3) for b in ("ordinary","held")} and len(cases)==4,"example coverage")
    return cases


def write_csv(path,data):
    with path.open("x",encoding="utf8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(data[0]),lineterminator="\n")
        w.writeheader()
        w.writerows(data)


def write_json(path,obj):
    path.write_text(json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf8",newline="\n")


def build(source,forks,out):
    if out.exists():
        raise FileExistsError(out)
    data=[]
    receipt={"method":"6.0C1-civilian-archive-1","samples":{}}
    for name,first in (("dev",0),("holdout",20)):
        points,count,hashes=sample(source,name,first)
        data.extend(points)
        receipt["samples"][name]={"rows_checked":count,"input_sha256":hashes}
    rr=sorted(data,key=lambda r:(r["seed"],r["arm"],r["year"]))
    result=summaries(rr)
    cases=archived_examples(forks)
    out.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=out.parent) as tmp:
        stage=Path(tmp)/"accounts"
        stage.mkdir()
        write_csv(stage/"seed-accounts.csv",rr)
        write_csv(stage/"cohort-accounts.csv",result)
        write_json(stage/"archived-cases.json",cases)
        receipt["case_source_sha256"]=digest(forks/"summary.json")
        receipt["output_sha256"]={p.name:digest(p) for p in sorted(stage.iterdir())}
        write_json(stage/"receipt.json",receipt)
        if out.exists():
            raise FileExistsError(out)
        stage.rename(out)


def markdown_table(columns,rows):
    return "\n".join("| "+" | ".join(map(str,line))+" |" for line in (columns,["---"]*len(columns),*rows))


def report(folder):
    receipt=json.loads((folder/"receipt.json").read_text(encoding="utf8"))
    require(all(digest(folder/n)==v for n,v in receipt["output_sha256"].items()),"result differs from receipt")
    cases=json.loads((folder/"archived-cases.json").read_text(encoding="utf8"))
    with (folder/"cohort-accounts.csv").open(encoding="utf8",newline="") as f:
        data=list(csv.DictReader(f))
    with (folder/"seed-accounts.csv").open(encoding="utf8",newline="") as f:
        seeds=list(csv.DictReader(f))
    names={"dev":"개발","holdout":"검증","all":"전체"}
    def qty(r,m):
        return f'{int(r[m]):,}'
    def p(r,k):
        return f'{float(r[k])*100:.3f}'
    def percentages(r,m):
        return p(r,m+"_mean")+" / "+p(r,m+"_pooled")
    rates,house,flows,work=[],[],[],[]
    for r in data:
        key=(names[r["sample"]],r["arm"],r["year"])
        rates.append([*key,qty(r,"service_serving"),qty(r,"service_ration_food"),
                      percentages(r,"public_rations_per_registered"),percentages(r,"both_receipts_per_registered"),
                      percentages(r,"resident_meals_per_need")])
        if r["sample"]!="all":
            continue
        house.append([r["arm"],r["year"],*(qty(r,m) for m in ("unprovided_food","unprovided_tools","roster_gap_with_resident_shortfall",
                      "roster_gap_with_full_meals","food_need","food_eaten","food_deficit")),
                      p(r,"nonparticipant_meals_lower_pooled")+"–"+p(r,"nonparticipant_meals_upper_pooled")])
        flows.append([r["arm"],r["year"],*(qty(r,m) for m in ("service_reassignment_out","service_road_load","service_travel_food",
                      "road_works_use","road_supply_use","road_relief_use","road_private_use","road_unused","road_capacity"))])
        work.append([r["arm"],r["year"],*(qty(r,m) for m in ("production_workers","project_workers","works_used_tools","service_tools_used",
                     "produced_food","public_transfer_in_food","relief_food","aid_sent","aid_received"))])
    pairs={(r["year"],r["branch"]):r for r in cases}
    examples=[]
    for y in (1,3):
        for label in ("ordinary","held"):
            r=pairs[y,label]
            examples.append([y,"정상" if label=="ordinary" else "그해 신규 등록 보류",
                             *(qty(r,k) for k in ("enrolled","registered","rations","tools_used","travel_food",
                                                  "food_produced","actual_meals","closing_population"))])
    examples2=[]
    for label in ("dev","holdout"):
        chosen={(int(r["seed"]),r["arm"]):r for r in seeds if r["year"]=="200" and r["sample"]==label}
        contrasts=[]
        for seed,arm in chosen:
            if arm=="C":
                continue
            d,c=chosen[seed,"D"],chosen[seed,"C"]
            diff=lambda k:int(d[k])-int(c[k])
            contrasts.append((diff("food_eaten"),seed,diff("service_ration_food"),diff("production_workers"),
                              diff("aid_received"),diff("closing_population")))
        for mark,obs in (("섭취 차 최소",min(contrasts)),("섭취 차 최대",max(contrasts))):
            e,s,r,l,a,n=obs
            examples2.append([names[label],mark,s,f"{r:+,}",f"{l:+,}",f"{a:+,}",f"{e:+,}",f"{n:+,}"])
    all200={r["arm"]:r for r in data if r["sample"]=="all" and r["year"]=="200"}
    c,d=all200["C"],all200["D"]
    amount_delta=int(d["food_eaten"])-int(c["food_eaten"])
    pub_delta=int(d["service_ration_food"])-int(c["service_ration_food"])
    return "\n\n".join([
        "# 평시 주민 명부·공공 배식·실제 식사의 회고 결산",
        f'기존 시드 40개의 200년 기록을 합치면 고정 정원 C에서는 등록 {qty(c,"service_serving")}인년에 공공 식사 {qty(c,"service_ration_food")}단위, 적응형 D에서는 {qty(d,"service_serving")}인년에 {qty(d,"service_ration_food")}단위를 지급했다. D−C의 공공 배식 차이는 {pub_delta:+,}단위였고 주민 전체가 실제 먹은 식량 차이는 {amount_delta:+,}단위였다. 공공 배식과 총섭취는 같은 식사를 다른 계정에서 볼 수 있으므로 두 값을 합산하면 지급한 식사를 중복 계산한다.',
        "## 시드별 평균과 인년 가중 비율",
        "개발 시드 0–19, 검증 시드 20–39다. 수량은 각 표본의 합계다. 셀의 두 비율(%)은 시드별 비율의 산술평균 / 전체 분자·분모를 각각 합쳐 나눈 값이다. 앞의 평균은 분모가 양수인 시드만 포함하며 원자료에 포함 시드 수도 기록했다. 배식과 두 물품 수령의 분모는 등록 인년, 실제 식사의 분모는 주민 필요 식수다. 한 도구가 여러 사람의 공동 작업에 사용되므로 두 물품을 받은 인원과 소모한 도구 수는 서로 다르다. 50·100·200년은 같은 경로의 중첩된 누계다.",
        markdown_table(("표본","정책","년","등록 인년","공공 배식","배식/명부 %","배식·도구 수령/명부 %","주민 실제 식사/필요 %"),rates),
        "## 공공 물품 차액과 가구 식사",
        "지역·연도별 등록 인원을 S, 거주지 공공 배식을 R, 주민 전체 필요 P, 섭취 E라고 두었다. 급식 계정의 차액은 S−R이다. 자택에서 식사를 받은 출퇴근자의 지역 간 순유입 M을 반영해 근무지 식사 기록은 R+M이다. 해당 지역에서 두 물품 수령이 확인된 인원을 A로 두면 도구 측 차액은 R+M−A다. 국내 이동은 쌍방에 한 번씩 기록되어 세계 합에서 M=0이다. 두 차액과 A를 더하면 S가 된다.",
        "아래 표는 지역·연도별 S−R을 그 지역 주민의 E<P 또는 E=P에 따라 배분했다. 같은 지역에 있었던 두 관측으로 개인의 굶주림 원인을 특정할 수 없다. 비등록 주민 식사는 max(0,E−S) 이상, min(P−S,E−R) 이하이다. 이 범위를 지역·연도별로 산출한 다음 합산하고 비등록 인년 Σ(P−S)으로 나눴다. 개인별 민간 식사 분배는 관측되지 않는다.",
        markdown_table(("정책","년","미배식 인년","배식 후 도구 미수령 인년","주민 식사 부족 지역의 미배식 인년","주민 전원 식사 지역의 미배식 인년",
                        "주민 필요량","주민 실제 섭취","주민 부족량","비등록 섭취율 범위 %"),house),
        "## 장부의 처리 순서와 보존",
        "1. 기초 공공창고에서 공공사업 사용분을 빼고 국내 창고 수령을 더하며 발송을 뺐다. 식량에는 공사 운임과 국내 창고 운임도 차감했다. 그 결과가 해당 연도의 배식 전 재고다. R은 이 식량과 S의 최솟값이다. 실제 도구 지급 건수는 지역별 A를 12로 나눈 올림이며 배식된 인원과 당시 공공 도구로 대조했다. 공공 식량이 나중에 들어왔더라도 앞선 시점의 식사로 기록하지 않았다.",
        "2. 공공 배식은 지역 공공창고에서 한 번 차감하고 일반 식사 직전 개인 식량 계정에 같은 양을 더했다. 개인 식량 기말은 기초 + 생산 − 생산투입 − 주민섭취 − 부패 − 현물세 + 민간 국내외 순유입 + 국내 구호 + 공공 배식 − 민간 국내외 운임이다. 연간표에서 독립적으로 확인되는 민간 기초는 전년 기말이므로 이 식은 2–200년에 적용했다. 1년에도 실제 필요·섭취·부패와 공공 재고를 대조했다.",
        "3. 공공창고의 나머지 변화에는 현물세, 세금 처리비, 국내 구호와 그 운임, 외국 원조 발송·수령 및 운임, 출퇴근 운임, 부패가 있다. 지역별 구호 발송량 열은 없어 이 결산의 식량 잔차로 추산하고, 모든 국가·연도에서 발송 추산합이 별도로 기록된 실제 구호 수령합과 같은지 확인했다. 도구와 광석은 지역별로 직접 닫았다. 세계의 외국 원조 발송은 수령 + 취급 손실과 일치했다.",
        "4. 등록 인년은 기초 명부 + 신규 등록 − 해제, 기말 명부는 등록 인년 − 그 집단의 사망·전출이다. 주소지 노동은 민간 생산·건설·토양관리·공공사업·집단행동 노동 보류·등록 인년의 합이다. 출퇴근은 일반 이주에 더하지 않았다. 아래 왕복 도로 사용은 같은 해의 전체 실측 사용 중 하나이며 운임은 실제 공공 식량 지출이다.",
        markdown_table(("정책","년","타지역 출퇴근 인년","왕복 도로","통행 식량","공공사업 도로","창고 이동 도로","국내 구호 도로",
                        "민간 도로","미사용 도로","전체 한도"),flows),
        markdown_table(("정책","년","민간 생산 인년","공공사업 인년","공사 도구 소모","복무 도구 소모","식량 생산","국내 창고 식량 수령",
                        "국내 가구 구호","해외 원조 발송","해외 원조 순수령"),work),
        "국내 창고 수령은 창고 사이 이동이다. 식사, 구호, 원조 지급의 처리 시점과 수령 계정은 서로 다르다. 도로를 같이 쓰거나 공공사업·민간 노동 및 원조 수치가 함께 변한 기록만으로 개별 식사의 공급원이나 각 항목이 일으킨 인과효과를 분리할 수 없다.",
        "## 보관된 실제 사례",
        "시드 0 적응형의 기존 단년 원장 네 개에서 직접 읽었다. 1년에는 두 경로 모두 공공 배식·도구 수령이 0이었지만 실제 주민 식사는 47 차이였다. 3년에는 공공 배식이 16 차이였지만 32개 지역 모두 실제 식사가 같았다. 이 비교의 개입은 한 해의 신규 등록이며 배식·도로·농업 각 항목의 독립 효과는 식별되지 않는다.",
        markdown_table(("년","기존 기록","신규 등록","등록 인년","공공 배식","도구 소모","통행 식량","식량 생산","실제 주민 식사","기말 인구"),examples),
        "각 표본에서 200년 주민 섭취 D−C가 가장 작고 큰 시드를 기계적으로 골랐다. 아래는 한 세계의 짝차다. 표본 평균으로 일반화할 때는 위의 40개 시드를 모두 사용한다.",
        markdown_table(("표본","선정 기준","시드","공공 배식 Δ","민간 생산 인년 Δ","해외 원조 수령 Δ","주민 식사 Δ","기말 인구 Δ"),examples2),
        "## 검증과 재현",
        "기존 개발·검증 원자료에서 지역 512,000년, 국가 128,000년, 세계 16,000년을 검사했다. 연간 지역합, 국가합, 세계 240개 체크포인트를 교차 대조했다. 비용과 수량은 정수로 대조했고 비율은 분자·분모 정수로 계산한 뒤 CSV 출력을 위해 반올림했다. 새 역사 경로를 실행하거나 모형 계수를 변경하지 않았다.",
        "`python -m experiments.civic_accounts63 --out 새결산폴더`로 새 폴더에 결과를 만들고, `python -m experiments.civic_accounts63 --verify examples/phase6c1/accounts --report docs/phase6c1-accounts.md`로 과거 원자료부터 다시 계산해 비교할 수 있다. 집중 테스트는 `python -m unittest tests.test_civic_accounts63 -v`이다.",
        "[시드별 수량](../examples/phase6c1/accounts/seed-accounts.csv) · [표본별 분자·분모 및 비율](../examples/phase6c1/accounts/cohort-accounts.csv) · [역사 사례](../examples/phase6c1/accounts/archived-cases.json) · [검산 영수증](../examples/phase6c1/accounts/receipt.json) · [기존 원장](../examples/phase6b2/study/README.md)"
    ])+"\n"


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,default=Path("examples/phase6b2/study"))
    parser.add_argument("--forks",type=Path,default=Path("examples/phase6b2/forks"))
    target=parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--out",type=Path)
    target.add_argument("--verify",type=Path)
    parser.add_argument("--report",type=Path)
    options=parser.parse_args()
    if options.verify:
        with TemporaryDirectory() as tmp:
            new=Path(tmp)/"accounts"
            build(options.source,options.forks,new)
            names={p.name for p in new.iterdir()}
            require(names=={p.name for p in options.verify.iterdir()} and
                    all(digest(new/n)==digest(options.verify/n) for n in names),"independent publication mismatch")
            if options.report:
                require(report(new).encode("utf8")==options.report.read_bytes(),"independent narrative differs")
        print("Verified the published civilian accounts.")
    else:
        if options.report and options.report.exists():
            raise FileExistsError(options.report)
        build(options.source,options.forks,options.out)
        if options.report:
            with options.report.open("x",encoding="utf8",newline="\n") as f:
                f.write(report(options.out))
        print(f"Published civilian accounts in {options.out}.")


if __name__=="__main__":
    main()
