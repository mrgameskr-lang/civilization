"""Read the settled economic and nominal office files without running a simulation."""
import argparse
from collections import Counter
import csv
import gzip
import hashlib
from itertools import groupby
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from civsim.model import GOODS, generate_world
from civsim.regions import regionalize
from experiments.civic_disputes63 import HORIZONS, write_json
from experiments.phase6a import digest_file
from experiments.posting_study65 import EXAMPLES, csv_rows


def goods_account(r, start):
    """Private balances are locally closed. Public relief origins cancel within each country."""
    n=lambda k:int(r[k])
    private, public = {}, {}
    for g in GOODS:
        private[g]=(start[g]+n("produced_"+g)-n("production_used_"+g)-n("meal_used_"+g)-n("levied_"+g)
                    +n("foreign_in_"+g)-n("foreign_out_"+g)+n("private_transfer_in_"+g)-n("private_transfer_out_"+g))
        public[g]=(n("opening_public_"+g)+n("levied_"+g)-n("works_used_"+g)
                   +n("public_transfer_in_"+g)-n("public_transfer_out_"+g))
    private["food"]+=(n("relief_food")+n("service_ration_food")-n("trade_freight_food")-n("private_freight_food"))
    public["food"]+=(n("aid_received")-n("aid_sent")-n("aid_freight_food")-n("public_works_freight_food")
                     -n("relief_food")-n("public_relief_freight_food")-n("public_spoil_food")-n("levy_handling_food")
                     -n("depot_freight_food")-n("service_ration_food")-n("service_travel_food"))
    public["tools"]-=n("service_tools_used")
    return private,public


def audit_seed(source,seed,directory,counts):
    with gzip.open(directory/f"seed-{seed:02}"/"economic-regions.csv.gz","rt",encoding="utf8",newline="") as f:
        rows={(r["arm"],int(r["year"]),int(r["region"])):r for r in csv.DictReader(f)}
    if len(rows)!=2*200*32:
        raise ValueError("missing public economic rows")
    initial={r.id:r.stock for r in regionalize(generate_world(seed)).regions}
    for (old,y),records in groupby(source,key=lambda r:(r["arm"],int(r["year"]))):
        e={"C":"A_fixed","D":"A"}[old]
        if y==1:
            private={i:v.copy() for i,v in initial.items()}
            public={i:dict.fromkeys(GOODS,0) for i in initial}
        projected,actual={},{}
        coverage=set()
        for r in records:
            i,o=int(r["region"]),int(r["owner"])
            b=rows.pop((e,y,i))
            if i in coverage or int(b["owner"])!=o or int(b["seed"])!=seed:
                raise ValueError("duplicate or misattributed public row")
            coverage.add(i)
            for field, historic in (("food_need","food_need"),("food_eaten","food_eaten"),("food_unmet","food_deficit"),
                                    ("closing_population","closing_population"),("closing_cash","closing_cash"),
                                    ("imports_value","imports_value"),("exports_value","exports_value"),
                                    ("duty_serving","service_serving"),("duty_ration_food","service_ration_food"),
                                    ("duty_tools_used","service_tools_used"),("duty_travel_food","service_travel_food")):
                if b[field]!=r[historic]:
                    raise ValueError(f"published regional {field} differs from historical economy")
            p,government=goods_account(r,private[i])
            for g in GOODS:
                if (p[g]!=int(b["private_"+g]) or p[g]!=int(r["closing_private_"+g]) or
                        int(b["public_"+g])!=int(r["closing_public_"+g]) or public[i][g]!=int(r["opening_public_"+g])):
                    raise ValueError(f"private goods, public custody or regional carry mismatch at {seed}/{e}/{y}/{i}/{g}")
                public[i][g]=int(b["public_"+g])
            private[i]=p
            projected.setdefault(o,Counter()).update(government)
            actual.setdefault(o,Counter()).update(public[i])
        if coverage!=set(initial) or projected!=actual:
            raise ValueError(f"public warehouse goods do not close by country at {seed}/{e}/{y}")
        counts["economic_years"]+=1
        counts["regional_private_good_balances"]+=len(coverage)*len(GOODS)
        counts["national_public_good_balances"]+=len(projected)*len(GOODS)
    if rows:
        raise ValueError("unmatched public economic records")


def inspect(sample,directory):
    runs=csv_rows(directory/"runs.csv")
    grid={(int(r["seed"]),r["arm"],int(r["year"])):r for r in runs}
    seeds=sorted({k[0] for k in grid})
    old=EXAMPLES/"phase6b2/study"/sample
    fingerprint=digest_file(old/"region-years.csv.gz")
    if fingerprint!=json.loads((old/"execution.json").read_bytes())["table_sha256"]["region-years.csv.gz"]:
        raise ValueError("archived regional receipts changed")
    count=Counter()
    with gzip.open(old/"region-years.csv.gz","rt",encoding="utf8",newline="") as source:
        grouped=groupby(csv.DictReader(source),key=lambda r:int(r["seed"]))
        for s in seeds:
            key,part=next(grouped)
            if key!=s:
                raise ValueError("historical seeds out of order")
            audit_seed(part,s,directory,count)
        if next(grouped,None) is not None:
            raise ValueError("unexpected historical seed")
    reasons=Counter()
    for s in seeds:
        chain=hashlib.sha256()
        nominal=Counter()
        with gzip.open(directory/f"seed-{s:02}"/"affiliations.jsonl.gz","rb") as f:
            for y in range(1,201):
                line=f.readline()
                record=json.loads(line)
                if record["year"]!=y:
                    raise ValueError("wrong nominal register year")
                chain.update(line)
                for a in record["assignments"]:
                    reasons[a["reason"]]+=1
                    nominal["ledger_assignments"]+=a["assigned"]
                    nominal["invoice_people"]+=a["invoice_people"]
                closing=record["closing"]
                nominal["closing_other_affiliation_home"]=sum(r["count"] for r in closing if r["home"]!=r["post"])
                nominal["closing_ledger"]=sum(r["count"] for r in closing)
                if y in HORIZONS:
                    b=grid[s,"B",y]
                    fixed=grid[s,"A_fixed",y]
                    for k,v in fixed.items():
                        if k not in ("arm","affiliation_sha256") and v and b[k]!=v:
                            raise ValueError(f"B and source fixed economy disagree in {k}")
                    if (chain.hexdigest()!=b["affiliation_sha256"] or
                            any(v!=int(b[k]) for k,v in nominal.items())):
                        raise ValueError("nominal raw rows differ from published checkpoint")
                    count["raw_register_digests"]+=1
            if f.read(1):
                raise ValueError("unexpected extra raw register years")
    by_year={}
    for y in HORIZONS:
        selected=[grid[s,"B",y] for s in seeds]
        keys=("ledger_assignments","invoice_people","unentered_invoice_people","carried_other_affiliation",
              "released_other_affiliation","deaths_other_affiliation","emigrants_other_affiliation","closing_ledger",
              "closing_other_affiliation_home","closing_population","food_need","food_unmet","duty_ration_food",
              "duty_tools_used","duty_travel_food")
        stats={k:sum(int(r[k]) for r in selected) for k in keys}
        for k in ("ledger_assignments","closing_other_affiliation_home","unentered_invoice_people"):
            stats["worlds_without_"+k]=sum(int(r[k])==0 for r in selected)
        stats["fixed_relative_to_A"]={k:sum(int(grid[s,"A_fixed",y][k])-int(grid[s,"A",y][k]) for s in seeds)
                                      for k in ("closing_population","food_need","food_eaten","food_unmet","duty_serving")}
        by_year[y]=stats
    return {"years":by_year,"verification":count,"administrative_invoice_rows":reasons,
            "historical_region_sha256":fingerprint}


def summarize(study,out,verify_against=None):
    if out.exists():
        raise FileExistsError(out)
    values={s:inspect(s,study/s) for s in ("dev","holdout")}
    if verify_against is None:
        write_json(out,values)
        return
    with TemporaryDirectory(dir=out.parent) as temp:
        regenerated=Path(temp)/"outcomes.json"
        write_json(regenerated,values)
        if regenerated.read_bytes()!=verify_against.read_bytes():
            raise ValueError("economic and register outcome analysis differs")
        write_json(out,{"byte_identical":True,"summary_sha256":digest_file(regenerated),
                        "register_checkpoints":sum(s["verification"]["raw_register_digests"] for s in values.values())})


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--study",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    p.add_argument("--verify-against",type=Path,help="compare a fresh analysis with the published summary and write a receipt")
    args=p.parse_args()
    summarize(args.study,args.out,args.verify_against)
