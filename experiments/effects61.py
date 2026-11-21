"""Rebuild the 6.0A.1 economic contrasts from regional, national and directional observations."""
import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
import csv
from fractions import Fraction
import gzip
import hashlib
from itertools import groupby
import json
from math import isclose
from pathlib import Path
import sys


ARMS = "ABCDEF"
CHECKPOINTS = (50,100,200)
COMPARISONS = ("B-A","C-A","D-A","E-A","F-E","I")
QUANTITIES = ("closing_population","food_need","food_eaten","food_deficit","export_value",
              "export_food","export_ore","export_tools","trade_denied_out","exit_denied_out","entry_denied_in")
DIRECT_SUM = {"trade_food":"export_food","trade_ore":"export_ore","trade_tools":"export_tools",
              "trade_value":"export_value","migrants":"emigrants","trade_denied":"trade_denied_out",
              "exit_denied":"exit_denied_out","entry_denied":"entry_denied_in"}
PACTS = {"agreement_active":("agreement_years","active_pact_partners"),
         "agreement_started":("agreements_started","new_pact_partners"),
         "agreement_terminated":("agreements_terminated","terminated_pact_partners")}
DERIVED = ("trade_partners_per_country_year","distinct_trading_pairs")


def require(ok,message):
    if not ok:
        raise ValueError(message)


def fraction(n,d):
    require(d>=0 and (d>0 or n==0),"nonzero measure has no denominator")
    return Fraction(n,d) if d else Fraction()


def compare(values,name):
    if name=="I":
        return values["E"]-values["B"]-values["C"]-values["D"]+2*values["A"]
    arm,reference = name.split("-")
    return values[arm]-values[reference]


def signs(values):
    counted = Counter((x>0)-(x<0) for x in values)
    return counted[1],counted[0],counted[-1]


def direction_year(rows):
    """Count observed partner and treaty pairs once, even when both directions are populated."""
    totals = Counter(dict.fromkeys((*DIRECT_SUM.values(),"trade_partner_years",*(k for k,_ in PACTS.values())),0))
    traded,seen = set(),set()
    signed = {flag:Counter() for flag in PACTS}
    for r in rows:
        s,t = int(r["source"]),int(r["target"])
        require(s!=t and (s,t) not in seen,"duplicate or internal foreign direction")
        seen.add((s,t))
        pair = min(s,t),max(s,t)
        for raw,k in DIRECT_SUM.items():
            totals[k]+=int(r[raw])
        if any(int(r[g])>0 for g in ("trade_food","trade_ore","trade_tools")):
            traded.add(pair)
        for flag in PACTS:
            value = int(r[flag])
            require(value in (0,1),"invalid bilateral event")
            if value:
                signed[flag][pair]+=1
    for flag,(key,_) in PACTS.items():
        require(all(v==2 for v in signed[flag].values()),"bilateral event lacks a matching second account")
        totals[key] = len(signed[flag])
    totals["trade_partner_years"] = 2*len(traded)
    return totals,traded


@contextmanager
def rows(path):
    opener = gzip.open if path.suffix==".gz" else open
    with opener(path,"rt",encoding="utf-8-sig",newline="") as stream:
        yield csv.DictReader(stream)


def key(r):
    return int(r["seed"]),r["arm"],int(r["year"])


def verify_numbers(record,expected,where):
    for k,v in expected.items():
        actual = Fraction(record[k])
        valid = actual==v if isinstance(v,int) else isclose(float(v),float(actual),rel_tol=1e-12,abs_tol=2e-15)
        require(valid,f"{where}: {k}, {v} != {record[k]}")


def audit_sample(folder,sample):
    receipt = json.loads((folder/"execution.json").read_text(encoding="utf8"))
    first = {"dev":0,"holdout":20}[sample]
    seeds = range(first,first+20)
    require(receipt["sample"]==sample and receipt["first_seed"]==first and receipt["seeds"]==20
            and receipt["horizons"]==list(CHECKPOINTS),"expected the published complete sample")
    for name in ("regions.csv","countries.csv","direction-years.csv.gz","runs.csv","means.csv","paired.csv"):
        with (folder/name).open("rb") as stream:
            require(hashlib.file_digest(stream,"sha256").hexdigest()==receipt["table_sha256"][name],
                    "stored table differs from receipt: "+name)
    region_totals,country_totals = defaultdict(Counter),defaultdict(Counter)
    regions,countries,owners = {},{},{}
    with rows(folder/"regions.csv") as table:
        for r in table:
            k = key(r)
            i,n = int(r["region"]),int(r["owner"])
            require((*k,i) not in regions and owners.setdefault((k[0],i),n)==n,"duplicate or reassigned region")
            v = {metric:int(r[metric]) for metric in QUANTITIES}
            require(v["food_need"]-v["food_eaten"]==v["food_deficit"],"meal postings differ")
            region_totals[*k,n].update(v)
            rate = fraction(v["food_deficit"],v["food_need"])
            verify_numbers(r,{"deficit_share":rate},(*k,i))
            regions[*k,i] = {"closing_population":v["closing_population"],"deficit_share":rate}
    with rows(folder/"countries.csv") as table:
        for r in table:
            k,n = key(r),int(r["owner"])
            require((*k,n) not in countries and (*k,n) in region_totals,"duplicate or unobserved country")
            v = region_totals[*k,n]
            verify_numbers(r,v,(*k,n))
            rate = fraction(v["food_deficit"],v["food_need"])
            verify_numbers(r,{"deficit_share":rate},(*k,n))
            countries[*k,n] = {"closing_population":v["closing_population"],"deficit_share":rate}
            ordinary = ("trade_partner_years","emigrants",*(col for _,col in PACTS.values()))
            country_totals[k].update({**v,**{col:int(r[col]) for col in ordinary}})
    expected_keys = {(s,a,y) for s in seeds for a in ARMS for y in CHECKPOINTS}
    require(set(country_totals)==expected_keys and len(regions)==len(expected_keys)*32
            and len(countries)==len(expected_keys)*8,"sample coverage differs")
    require(all((*k,i) in regions for k in expected_keys for i in range(32))
            and all((*k,n) in countries for k in expected_keys for n in range(8)),"region or country missing")
    direct,contacts,seen = defaultdict(Counter),defaultdict(set),set()
    with rows(folder/"direction-years.csv.gz") as table:
        for (s,a,y),annual in groupby(table,key):
            require((s,a,y) not in seen and s in seeds and a in ARMS and 1<=y<=200,"invalid direction-year group")
            seen.add((s,a,y))
            counters,traded = direction_year(annual)
            for h in CHECKPOINTS:
                if h>=y:
                    direct[s,a,h].update(counters)
                    contacts[s,a,h].update(traded)
    worlds = {}
    for k,values in country_totals.items():
        base = dict(values)
        for count,by_member in PACTS.values():
            twice = base.pop(by_member)
            require(twice%2==0,"incomplete bilateral country-year total")
            base[count] = twice//2
        actual = direct[k]
        for metric in (*DIRECT_SUM.values(),"trade_partner_years",*(v[0] for v in PACTS.values())):
            require(base[metric]==actual[metric],f"direction and country postings differ {k} {metric}")
        base.update(deficit_share=fraction(base["food_deficit"],base["food_need"]),
                    trade_partners_per_country_year=fraction(actual["trade_partner_years"],8*k[2]),
                    distinct_trading_pairs=len(contacts[k]))
        worlds[k] = base
    metrics = [m for m in next(iter(worlds.values())) if m not in DERIVED]
    checked = set()
    with rows(folder/"runs.csv") as table:
        for r in table:
            k = key(r)
            require(k not in checked,"duplicate run")
            verify_numbers(r,{m:worlds[k][m] for m in metrics},k)
            checked.add(k)
    require(checked==expected_keys,"missing run")
    checked = set()
    with rows(folder/"means.csv") as table:
        for r in table:
            y,arm=int(r["year"]),r["arm"]
            require((y,arm) not in checked and int(r["seeds"])==20,"duplicate/incomplete mean")
            group=[worlds[s,arm,y] for s in seeds]
            means={m:sum((w[m] for w in group),Fraction())/20 for m in metrics}
            means["pooled_deficit_share"] = fraction(sum(w["food_deficit"] for w in group),sum(w["food_need"] for w in group))
            verify_numbers(r,means,(y,arm))
            checked.add((y,arm))
    require(checked=={(y,a) for y in CHECKPOINTS for a in ARMS},"missing mean")
    checked=set()
    with rows(folder/"paired.csv") as table:
        for r in table:
            s,y,c=int(r["seed"]),int(r["year"]),r["contrast"]
            require((s,y,c) not in checked and c in COMPARISONS,"duplicate/invalid contrast")
            values = {m:compare({a:worlds[s,a,y][m] for a in ARMS},c) for m in metrics}
            verify_numbers(r,values,(s,y,c))
            checked.add((s,y,c))
    require(checked=={(s,y,c) for s in seeds for y in CHECKPOINTS for c in COMPARISONS},"missing paired row")
    return {"seeds":seeds,"world":worlds,"country":countries,"region":regions,"owners":owners,
            "verified_metrics":len(metrics)}


def mean(values):
    values = list(values)
    return sum(values,Fraction())/len(values)


def number(value,digits=2,signed=False):
    if value==0:
        return "0"
    spec = ("+" if signed else "")+",."+str(digits)+"f"
    return format(float(value),spec).replace("-","−")


def table(lines,head,records):
    lines.extend(["","| "+" | ".join(head)+" |","|"+"|".join("---" for _ in head)+"|"])
    for row in records:
        lines.append("| "+" | ".join(map(str,row))+" |")


def delta_set(level,seeds,y,c,metric,ids=None):
    if ids is None:
        return {s:compare({a:level[s,a,y][metric] for a in ARMS},c) for s in seeds}
    return {(s,i):compare({a:level[s,a,y,i][metric] for a in ARMS},c) for s in seeds for i in ids}


def count_text(values,*,lower=False):
    up,eq,down=signs(values)
    return "/".join(map(str,(down,eq,up) if lower else (up,eq,down)))


def render_sample(data,sample):
    names={"dev":"개발 시드 0~19","holdout":"홀드아웃 시드 20~39"}
    seeds,world = data["seeds"],data["world"]
    lines=["","## "+names[sample],"","### 군별 세계 결과","",
           "각 행은 같은 20개 세계의 평균이다. 인구는 해당 연도 말, 식량·광석·도구 교역량과 교역액은 첫해부터 누적이다. 상대국 평균의 분모는 거래가 없던 나라까지 포함한 8개국×관측 연수다. 누적 교역 쌍은 해당 시점까지 한 번 이상 민간 거래한 서로 다른 쌍의 수다."]
    economy,policy,ranks,external=[],[],[],[]
    for y in CHECKPOINTS:
        for arm in ARMS:
            avg={k:mean(world[s,arm,y][k] for s in seeds) for k in world[seeds[0],arm,y]}
            economy.append([y,arm,number(avg["closing_population"]),number(100*avg["deficit_share"],6),
                            *(number(avg["export_"+g],2) for g in ("food","ore","tools")),number(avg["export_value"]),
                            number(avg["trade_partners_per_country_year"],4),number(avg["distinct_trading_pairs"])])
            policy.append([y,arm,number(avg["agreements_started"]),number(avg["agreements_terminated"]),
                           number(avg["agreement_years"]),number(avg["trade_denied_out"]),
                           number(avg["exit_denied_out"]),number(avg["entry_denied_in"]),number(avg["emigrants"])])
        for c in COMPARISONS:
            p=delta_set(world,seeds,y,c,"closing_population")
            r=delta_set(world,seeds,y,c,"deficit_share")
            ranks.append([y,c,number(mean(p.values()),2,True),count_text(p.values()),
                          number(100*mean(r.values()),7,True),count_text(r.values(),lower=True)])
            metrics=("export_value","trade_partners_per_country_year","agreements_started","agreements_terminated",
                     "trade_denied_out","exit_denied_out","entry_denied_in","emigrants")
            v=[mean(delta_set(world,seeds,y,c,m).values()) for m in metrics]
            external.append([y,c,number(v[0],2,True),number(v[1],5,True),*(number(x,2,True) for x in v[2:])])
    table(lines,["년","군","기말 인구","부족률 %","식량 교역","광석 교역","도구 교역","교역액","상대국/국·년","누적 교역 쌍"],economy)
    lines.extend(["","### 협정과 이동","",
                  "합의·조기 종료·유효기간은 국가 쌍당 한 번씩 합산했다. 수출 거부는 재화 물량, 출국·입국 거부는 각 국경 심사에서 거부된 인원이다. 실이주는 국경을 건넌 인원이다."])
    table(lines,["년","군","협정 체결","조기 종료","유효 쌍·년","수출 거부","출국 거부","입국 거부","실이주"],policy)
    lines.extend(["","### 같은 시드의 차이","",
                  "인구 분포 열은 증가/동일/감소, 부족률 분포 열은 개선(하락)/동일/악화(상승) 시드 수다. 비율·인구를 먼저 세계별로 짝지은 뒤 20개 차이의 산술평균을 구했다. I의 부호는 비가산적 기여의 방향이다."])
    table(lines,["년","비교","Δ 인구","인구 ↑/=/↓","Δ 부족률 %p","부족 개선/=/악화"],ranks)
    lines.extend(["","### 교역·협정·국경의 처리별 차이","",
                  "각 값은 같은 시드의 차이를 20개 세계에서 평균했다. 단위는 군별 세계 결과와 같다. I 행의 수출·이주 거부는 결합 처리의 결과가 세 단독 처리의 선형 예측에서 벗어난 정도다."])
    table(lines,["년","비교","Δ 교역액","Δ 상대국/국·년","Δ 협정 체결","Δ 조기 종료","Δ 수출 거부","Δ 출국 거부","Δ 입국 거부","Δ 실이주"],external)
    extremal=[]
    for metric,unit,scale in (("closing_population","명",1),("deficit_share","%p",100)):
        diffs=delta_set(world,seeds,200,"I",metric)
        lo,hi=min(seeds,key=lambda s:(diffs[s],s)),min(seeds,key=lambda s:(-diffs[s],s))
        digits=0 if scale==1 else 6
        extremal.append(f"시드 {lo}의 {number(diffs[lo]*scale,digits,True)}{unit}에서 시드 {hi}의 {number(diffs[hi]*scale,digits,True)}{unit}")
    lines.extend(["","200년 잔차의 시드 범위는 인구가 "+extremal[0]+", 부족률이 "+extremal[1]+"였다."])
    lines.extend(["","### 200년의 국가·지역 분포","",
                  "각 비교는 고정 국가 160곳과 지역 640곳에서 같은 ID끼리 계산했다. 부족률 분모는 각 나라 또는 지역의 200년 누적 식량 수요다."])
    geographic=[]
    for c in COMPARISONS:
        row=[c]
        for label,count in (("country",8),("region",32)):
            for m in ("closing_population","deficit_share"):
                d=delta_set(data[label],seeds,200,c,m,range(count))
                row.append(count_text(d.values(),lower=m=="deficit_share"))
        geographic.append(row)
    table(lines,["비교","국가 인구 ↑/=/↓","국가 부족 개선/=/악화","지역 인구 ↑/=/↓","지역 부족 개선/=/악화"],geographic)
    lines.extend(["","### 상반된 경로를 직접 확인한 사례","",
                  "200년의 각 정책 비교에서 세계 인구 차이가 최솟값·최댓값인 시드를 골랐다. 같은 시드 안에 세계 인구 차이와 반대 방향으로 움직인 국가·지역이 있으면 그중 절댓값이 가장 큰 곳을 표시했다. 없으면 절댓값이 가장 큰 곳을 표시했다. 동률은 작은 ID 순이다. 각 수치는 원자료의 기준군→처리군 순서다."])
    records=[]
    for c in ("B-A","C-A","D-A","E-A","F-E"):
        after,before=c.split("-")
        ds=delta_set(world,seeds,200,c,"closing_population")
        for label,s in (("최소",min(seeds,key=lambda i:(ds[i],i))),("최대",min(seeds,key=lambda i:(-ds[i],i)))):
            w0,w1=world[s,before,200],world[s,after,200]
            def display(a,b):
                return f'{a["closing_population"]:,}→{b["closing_population"]:,} / {number(100*a["deficit_share"],5)}→{number(100*b["deficit_share"],5)}%'
            entries=[c+" "+label,s,display(w0,w1)]
            for level,count in (("country",8),("region",32)):
                d=delta_set(data[level],[s],200,c,"closing_population",range(count))
                opposite=[i for i in range(count) if d[s,i]*ds[s]<0]
                i=min(opposite or range(count),key=lambda i:(-abs(d[s,i]),i))
                values=data[level]
                entity = f"국가 {i}" if level=="country" else f"국가 {data['owners'][s,i]} 지역 {i}"
                entries.append(entity+" · "+display(values[s,before,200,i],values[s,after,200,i]))
            records.append(entries)
    table(lines,["비교·선정","시드","세계 인구 / 부족률","국가 인구 / 부족률","지역 인구 / 부족률"],records)
    return lines


def report(study):
    samples={s:audit_sample(study/s,s) for s in ("dev","holdout")}
    lines=["# 6.0A.1 인구·부족·교역·이동의 독립 검산","",
           "같은 시드에서 협정만 유지한 A, 원조만 더한 B, 수출 제한만 더한 C, 이주 통제만 더한 D, 세 수단을 결합한 E, 여기에 실제 원조 지출 상한을 둔 F를 비교했다. 개발과 홀드아웃은 각각 세계 20개이며 50·100·200년은 같은 세계에서 이어지는 관측이다.",
           "","## 200년 요약",""]
    for sample,title in (("dev","개발"),("holdout","홀드아웃")):
        d=samples[sample]
        parts=[]
        for c in ("E-A","F-E","I"):
            dp=mean(delta_set(d["world"],d["seeds"],200,c,"closing_population").values())
            dr=100*mean(delta_set(d["world"],d["seeds"],200,c,"deficit_share").values())
            parts.append(f"{c} 인구 {number(dp,2,True)}명·부족률 {number(dr,7,True)}%p")
        lines.append("- "+title+"에서 "+", ".join(parts)+"였다.")
    lines.extend(["","## 재집계 방법","",
                  "지역 체크포인트의 기말 인구·식량 필요·섭취·미충족·국제 교역을 같은 국가의 원장과 맞췄다. 식량 부족률은 각 단위에서 누적 미충족량/누적 필요량이다. 인구와 교역은 합산하고 국가별 비율을 세계 평균에 직접 더하지 않는다. 시드 안에서 분수로 계산한 뒤 정확한 부호를 판별했다. 표의 0 부근 숫자는 표시 자릿수에서 반올림한 값이다.",
                  "","방향별 연표에서는 재화가 한 단위라도 이동한 (연도, 국가 쌍)을 사용해 실제 교역 상대를 복원했다. 같은 해 양방향 거래가 있어도 한 쌍이며, 양국의 상대국 수에는 각각 1을 더한다. 누적 교역액은 실거래 수출액 한쪽, 협정 체결·조기 종료는 양국 기표가 맞는 쌍 한쪽만 센다. 같은 쌍의 만기 후 재체결은 새로운 사건이다. 유효 협정은 거래가 없는 해도 유효기간에 포함한다.",
                  "","수출·이주 거부는 해당 거래·이주 후보가 실제 심사에서 막힌 수량이다. 한 화물·사람이 대체 경로를 재시도할 수 있어 연도·국경별 시도 수량의 합으로 해석해야 한다. 입국 거부는 출국 심사를 통과하고 남은 후보 인원에서 계산한다.",
                  "","각 시드·시점·지표 Y에서 잔차는 I = (E−A) − [(B−A)+(C−A)+(D−A)]다. 정책이 함께 바꾸는 재고·인구·관계와 추후 결정을 포함한다. 2개 수단만 켠 군이 없으므로 특정 두 수단의 상호작용 비율은 식별할 수 없다. 세수·원조 비용·수혜 귀착은 별도 자료에 기록한다."])
    for sample,data in samples.items():
        lines.extend(render_sample(data,sample))
    n=samples["dev"]["verified_metrics"]
    lines.extend(["","## 재현","",
                  f"각 표본에서 지역 11,520행, 국가 2,880행, 세계 360행을 대조했다. 같은 독립 산식으로 시드별 {n}개 지표의 세계값, 18개 군·시점 평균과 별도 인구수요 가중 부족률, 360개 짝지은 대비 행을 검산했다. 상대국/국·년과 누적 실거래 쌍 수는 방향표에서 추가 계산했다. 입력 6개 파일의 SHA-256도 실행 영수증과 대조했다.",
                  "","프로젝트 루트에서 `python -m experiments.effects61 --study examples/phase6a1/study`를 실행하면 이 문서를 표준 출력으로 재생한다. `python -m unittest tests.test_effects61`은 양방향 기표·거래 상대 중복, 잔차, 0분모와 정확한 부호 처리를 검증한다. [개발 표본](../examples/phase6a1/study/dev) · [홀드아웃](../examples/phase6a1/study/holdout) · [검산 코드](../experiments/effects61.py)"])
    return "\n".join(lines)+"\n"


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--study",type=Path,required=True)
    p.add_argument("--out",type=Path)
    args=p.parse_args()
    content=report(args.study)
    if args.out:
        with args.out.open("x",encoding="utf8",newline="\n") as target:
            target.write(content)
    else:
        sys.stdout.reconfigure(encoding="utf8")
        sys.stdout.write(content)
