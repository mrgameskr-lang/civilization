"""Check shared border capacity, inactive neighbors and treaty events against published panels."""
import argparse
from collections import Counter, defaultdict
import csv
import gzip
import hashlib
import json
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory

from experiments.publication import publish_file


ARMS = ("A","B","C","D")
GOODS = ("food","ore","tools")
EVENTS = ("pact_rejected","pact_breached","pact_terminated","pact_expired",
          "aid_request_rejected","aid_offer_rejected","aid_shortfall")
FILES = ("borders.csv.gz","pair-years.csv.gz","events.csv.gz","country-years.csv.gz")


def check(value, label):
    if not value:
        raise ValueError(label)


def road_bounds(capacities, total):
    """Min/max #full roads in one year consistent with known capacities and total integer load."""
    check(all(c>0 for c in capacities) and 0<=total<=sum(capacities),"impossible annual cargo")
    lower = max(0,total-sum(c-1 for c in capacities))
    remaining,upper = total,0
    for cap in sorted(capacities):
        if cap>remaining:
            break
        remaining -= cap
        upper += 1
    return lower,upper


def lifetime_bounds(capacity,total,years):
    check(capacity>0 and years>0 and 0<=total<=capacity*years,"impossible cumulative cargo")
    return max(0,total-years*(capacity-1)),total//capacity


def rows(path):
    with gzip.open(path,"rt",encoding="utf8",newline="") as stream:
        yield from csv.DictReader(stream)


def paired_edges(records, horizon):
    directions,hubs = {},defaultdict(Counter)
    for row in records:
        if int(row["year"])!=horizon:
            continue
        seed,arm = int(row["seed"]),row["arm"]
        a,b = int(row["source_region"]),int(row["target_region"])
        src,dst = int(row["source_country"]),int(row["target_country"])
        key = seed,arm,a,b
        check(key not in directions and a!=b and src!=dst,"invalid cumulative regional direction")
        sent,net,loss,fee = (int(row[k]) for k in ("aid_dispatched","aid_received","aid_handling_food","aid_freight_food"))
        check(sent==net+loss and min(sent,net,loss,fee)>=0,"aid does not reconcile")
        physical = (int(row["shared_capacity_per_year"]),int(row["distance"]))
        directions[key] = (src,dst,physical,sum(int(row["trade_"+g]) for g in GOODS)+sent)
        if sent:
            hubs[seed,arm,src,a].update(sent=sent,received=net,handling=loss,freight=fee)
    edges=defaultdict(list)
    for (seed,arm,x,y),(src,dst,geom,cargo) in directions.items():
        rev = directions.get((seed,arm,y,x))
        check(rev is not None and (rev[0],rev[1],rev[2])==(dst,src,geom),"unmatched or inconsistent direction")
        if src>dst:
            continue
        total=cargo+rev[3]
        lifetime_bounds(geom[0],total,horizon)
        edges[seed,arm,src,dst].append(dict(a=x,b=y,capacity=geom[0],distance=geom[1],cargo=total,
                                            ab_cargo=cargo,ba_cargo=rev[3]))
    return edges,hubs


def sample(folder):
    folder=Path(folder)
    meta=json.loads((folder/"execution.json").read_text(encoding="utf8"))
    horizon=max(meta["horizons"])
    for file in FILES:
        with (folder/file).open("rb") as f:
            check(hashlib.file_digest(f,"sha256").hexdigest()==meta["table_sha256"][file],"source hash differs: "+file)
    edges,hubs=paired_edges(rows(folder/FILES[0]),horizon)
    by_arm={a:Counter() for a in ARMS}
    by_pair=defaultdict(Counter)
    relations=defaultdict(list)
    summaries={arm:{} for arm in ARMS}
    expected_events=Counter()
    for r in rows(folder/FILES[1]):
        seed,arm,year,a,b=int(r["seed"]),r["arm"],int(r["year"]),int(r["a"]),int(r["b"])
        key=seed,arm,a,b
        p,c=by_pair[key],by_arm[arm]
        check(a<b and year==p["years"]+1 and year<=horizon,"missing or duplicate pair-year")
        p["years"]+=1
        c["all_pair_years"]+=1
        paths=edges.get(key,())
        caps=[e["capacity"] for e in paths]
        capacity=int(r["physical_capacity"])
        check(sum(caps)==capacity,"crossing capacity differs between pair and physical road tables")
        observed=int(r["observations"])
        check(observed==int(arm!="A"),"unexpected observed pair")
        if year==horizon and observed:
            relations[arm,bool(paths)].append(int(r["relation"]))
        for evt in EVENTS:
            expected_events[arm,evt]+=int(r["event_"+evt])
        ab,ba=(sum(int(r[d+"trade_"+g]) for g in GOODS) for d in ("ab_","ba_"))
        cargo_ab=ab+int(r["ab_aid_dispatched"])
        cargo_ba=ba+int(r["ba_aid_dispatched"])
        total=cargo_ab+cargo_ba
        pact=int(r["agreement_years"])
        check(pact in (0,1) and total<=capacity and (paths or not pact),"activity outside adjacent pair")
        if not paths:
            continue
        p.update(ever_trade=int(ab+ba>0),ever_pact=pact,ab=cargo_ab,ba=cargo_ba)
        lower,upper=road_bounds(caps,total)
        p.update(year_low=lower,year_high=upper)
        c.update(adjacent_pair_years=1,adjacent_no_trade_years=int(ab+ba==0),
                 adjacent_no_pact_years=1-pact,pact_years_no_trade=int(pact and ab+ba==0),
                 network_full_years=int(total==capacity),network_full_one_way_years=int(max(cargo_ab,cargo_ba)==capacity),
                 single_road_full_years=int(len(paths)==1 and total==capacity),
                 single_road_years=int(len(paths)==1),cargo=total,capacity=capacity)
        if total==capacity:
            case={"seed":seed,"year":year,"country_a":a,"country_b":b,"roads":len(paths),
                  "capacity":capacity,"forward":cargo_ab,"reverse":cargo_ba}
            if len(paths)==1:
                case.update(source_region=paths[0]["a"],target_region=paths[0]["b"])
            prior=summaries[arm].get("full_network_example")
            def order(value):
                return (value["roads"]!=1,value["seed"],value["year"],value["country_a"],value["country_b"])
            if prior is None or order(case)<order(prior):
                summaries[arm]["full_network_example"]=case
    for (seed,arm,a,b),p in by_pair.items():
        check(p["years"]==horizon,"incomplete pair series")
        paths=edges.get((seed,arm,a,b))
        if not paths:
            continue
        check((p["ab"],p["ba"])==tuple(sum(e[k] for e in paths) for k in ("ab_cargo","ba_cargo")),
              "directional cargo differs between annual and cumulative panels")
        c=by_arm[arm]
        bounds=[lifetime_bounds(e["capacity"],e["cargo"],horizon) for e in paths]
        low=max(sum(q[0] for q in bounds),p["year_low"])
        high=min(sum(q[1] for q in bounds),p["year_high"])
        check(low<=high,"incompatible annual and cumulative saturation bounds")
        c.update(adjacent_seed_pairs=1,never_trade_pairs=int(not p["ever_trade"]),
                 never_pact_pairs=int(not p["ever_pact"]),road_years=horizon*len(paths),
                 full_road_years_lower=low,full_road_years_upper=high)
        for e in paths:
            entry=dict(seed=seed,source=e["a"],target=e["b"],cargo=e["cargo"],
                       capacity=e["capacity"]*horizon,forward=e["ab_cargo"],reverse=e["ba_cargo"])
            incumbent=summaries[arm].get("highest_utilization_road")
            if incumbent is None or entry["cargo"]*incumbent["capacity"]>incumbent["cargo"]*entry["capacity"]:
                summaries[arm]["highest_utilization_road"]=entry
    event_counts=Counter()
    for r in rows(folder/FILES[2]):
        if r["kind"] in EVENTS:
            event_counts[r["arm"],r["kind"]]+=1
    check(event_counts==expected_events,"separate events panel differs from pair-year totals")
    example_rank={}
    for r in rows(folder/FILES[3]):
        if not int(r["aid_exposed_region_years"]):
            continue
        arm=r["arm"]
        groups={g:{k:int(r["aid_"+g+"_"+k]) for k in ("positive","negative","zero","members","delta_x_members")}
                for g in ("farm","industry","consumer")}
        seed,y,i=int(r["seed"]),int(r["year"]),int(r["owner"])
        rank=(sum(g["negative"] for g in groups.values()),int(r["aid_sent"]),-seed,-y,-i)
        if arm not in example_rank or rank>example_rank[arm]:
            example_rank[arm]=rank
            summaries[arm]["exposed_country_year_example"]=dict(seed=seed,year=y,owner=i,
                exposed_region_years=int(r["aid_exposed_region_years"]),sent=int(r["aid_sent"]),
                received=int(r["aid_received"]),groups=groups)
    for arm,c in by_arm.items():
        check(c["all_pair_years"]==28*meta["seeds"]*horizon,"wrong eight-nation pair-year denominator")
        d=summaries[arm]
        d["counts"]=dict(c)
        if arm=="A":
            for k in ("adjacent_no_pact_years","never_pact_pairs","pact_years_no_trade"):
                d["counts"][k]=None
        d["events"]={k:event_counts[arm,k] for k in EVENTS}
        d["closing_relations"]={}
        for name,adjacent in (("adjacent",True),("nonadjacent",False)):
            values=relations[arm,adjacent]
            d["closing_relations"][name]=(dict(n=len(values),negative=sum(v<0 for v in values),
                                                   zero=values.count(0),positive=sum(v>0 for v in values),
                                                   median=median(values)) if values else None)
        locations=[(k,v) for k,v in hubs.items() if k[1]==arm]
        if locations:
            (seed,_,owner,region),counter=min(locations,key=lambda e:(-e[1]["handling"],e[0]))
            d["largest_origin_handling_loss"]=dict(seed=seed,owner=owner,region=region,**counter)
    return {"sample":meta["sample"],"seeds":meta["seeds"],"years":horizon,"arms":summaries,
            "source_sha256":{k:meta["table_sha256"][k] for k in FILES}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    if args.out.exists() or args.out.is_symlink():
        raise FileExistsError(args.out)
    result={k:sample(args.study/k) for k in ("dev","holdout")}
    check(all(sample_name==v["sample"] for sample_name,v in result.items()),"incorrect sample order")
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=args.out.parent) as tmp:
        path=Path(tmp,"diagnostics.json")
        path.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf8",newline="\n")
        publish_file(path,args.out)


if __name__=="__main__":
    main()
