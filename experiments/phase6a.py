"""Matched diplomacy study with independently posted international transactions."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack, contextmanager
import csv
import gzip
import hashlib
import io
from itertools import combinations
import json
import os
from pathlib import Path
import platform
import shutil
from statistics import fmean
from tempfile import TemporaryDirectory
import time

from civsim.collective import collective_snapshot
from civsim.collective_rules import ACTIVE
from civsim.model import GOODS, generate_world
from civsim.regions import regionalize
from civsim.storage import canonical_line
from experiments.phase5a import _ratio, _read, _sha, _write, disparity
from experiments.phase5d import _json


ARMS = ("A", "B", "C", "D")
ARCHIVE = Path(__file__).resolve().parents[1] / "examples/phase5d/study"
TRADE = tuple("trade_"+g for g in GOODS)
SHIP = (*TRADE, "trade_value", "trade_freight_food", "trades", "migrants", "aid_dispatched",
        "aid_received", "aid_freight_food", "aid_handling_food", "trade_denied", "exit_denied", "entry_denied")
FISCAL = ("relief_food", "public_freight_food", "public_spoil_food", "collection_cost_food",
          "works_ore", "works_tools", "public_labor")
NATIONAL = ("food_need", "food_eaten", "food_deficit", "births", "deaths", "immigrants", "emigrants",
            "trade_partner_years", "migration_partner_years", "import_value", "export_value",
            "aid_sent", "aid_received", "aid_freight_food", "aid_handling_food", "trade_freight_food",
            "civil_freight_food", "active_group_years", "participants", "withheld_workers", "turnovers",
            "policy_changes", "member_years", "support_x_members", "discontent_x_members",
            "within_country_ration_gap", "aid_exposed_region_years", *FISCAL,
            *("aid_"+g+"_"+m for g in ("farm","industry","consumer")
              for m in ("members", "positive", "negative", "zero", "delta_x_members")),
            *(p+g for g in GOODS for p in ("produced_", "used_", "meal_used_", "import_", "export_", "levied_", "refused_")))
ENDPOINT = ("opening_population", "closing_population", "opening_cash", "closing_cash",
            *("closing_"+s+"_"+g for s in ("private", "public") for g in GOODS))
EVENT = ("seed", "arm", "year", "a", "b", "kind", "source", "target", "details_json")
PAIR_POLICY = ("observations", "agreement_years", "agreements_started", "trade_restriction_direction_years",
               "exit_restriction_direction_years", "entry_restriction_direction_years", "aid_requested_directions",
               "aid_offered_directions", "aid_accepted_directions", "aid_authorized","agreement_directions_kept",
               "agreement_directions_breached","agreement_directions_no_opportunity","relation_improved","relation_worsened")
RELATION = ("relation", "trust", "tension", "cooperation", "reciprocity")
DIRECTION_POLICY = ("import_dependence","export_exposure","food_import_share","pact_score","pact_willing",
                    "aid_request","aid_offer","aid_accepted","aid_quantity",
                    "trade_limit_permille","migration_limit_permille","migration_accept_permille")
KINDS = ("pact_proposed","pact_rejected","pact_started","pact_expired","pact_breached","pact_terminated",
         "aid_requested","aid_offered","aid_request_rejected","aid_offer_rejected","aid_accepted",
         "aid_delivered","aid_shortfall","trade_restricted","migration_exit_restricted","migration_entry_restricted")
KEY = ("seed", "arm", "year")
PANELS = ("country-years", "pair-years", "events")


@contextmanager
def compressed(path):
    with path.open("xb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", compresslevel=4, mtime=0) as gz:
        with io.TextIOWrapper(gz, encoding="utf8", newline="") as stream:
            yield stream


def emit(stream, fields, header=False):
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    if header:
        writer.writeheader()
    return writer


def digest_file(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def physical(record, borders, owners):
    """Signed physical postings. Shared capacity is audited once for each undirected edge."""
    edges = {(x, y): Counter(dict.fromkeys(SHIP, 0)) for road in borders
             for x, y in ((road.a, road.b), (road.b, road.a))}
    pairs = defaultdict(Counter)
    for trade in record["border_market"]["trades"]:
        c = edges[trade["seller"], trade["buyer"]]
        c.update({"trade_"+trade["good"]:trade["quantity"], "trade_value":trade["value"],
                  "trade_freight_food":trade["cost_food"], "trades":1})
    for move in record["moves"]:
        x, y = move["source"], move["target"]
        if owners[x] != owners[y]:
            edges[x, y]["migrants"] += move["people"]
    evidence = record.get("diplomacy", {}).get("physical") or {}
    for shipment in evidence.get("aid", {}).get("shipments", []):
        c = edges[shipment["source"], shipment["target"]]
        c.update(aid_dispatched=shipment["quantity"], aid_received=shipment["received"],
                 aid_freight_food=shipment["cost_food"], aid_handling_food=shipment["handling_food"])
        if shipment["quantity"] != shipment["received"] + shipment["handling_food"]:
            raise ValueError("handing loss differs from cross-border aid postings")
    for t in evidence.get("trade_attempts", []):
        edges[t["source"], t["target"]]["trade_denied"] += t["denied"]
    for m in evidence.get("migration_attempts", []):
        edges[m["source"], m["target"]].update(exit_denied=m["denied_exit"], entry_denied=m["denied_entry"])
    for (x,y), c in edges.items():
        pairs[owners[x],owners[y]].update(c)
    capacities = Counter()
    checks = {(r["a"],r["b"]):r for r in evidence.get("roads", [])}
    for road in borders:
        a,b = road.a,road.b
        private = sum(edges[x,y][g] for x,y in ((a,b),(b,a)) for g in TRADE)
        aid = edges[a,b]["aid_dispatched"]+edges[b,a]["aid_dispatched"]
        if private + aid > road.capacity:
            raise ValueError("shared international road capacity exceeded")
        if checks:
            row = checks[a,b]
            if (row["capacity"],row["private_cargo"],row["aid_cargo"],row["unused"]) != (
                road.capacity,private,aid,road.capacity-private-aid
            ):
                raise ValueError("international road utilization differs from posted shipments")
        capacities[tuple(sorted((owners[a],owners[b])))] += road.capacity
    return edges, pairs, capacities


def country_years(record, flows):
    gov = record["government"]
    cash = {a["id"]:a for a in gov["accounts"]}
    data = {i: Counter(dict.fromkeys(NATIONAL, 0)) for i in cash}
    trade_partners, migrant_partners = defaultdict(set), defaultdict(set)
    for (a,b),f in flows.items():
        source, target = data[a], data[b]
        source.update(export_value=f["trade_value"], trade_freight_food=f["trade_freight_food"],
                      emigrants=f["migrants"], aid_sent=f["aid_dispatched"], aid_freight_food=f["aid_freight_food"],
                      aid_handling_food=f["aid_handling_food"])
        target.update(import_value=f["trade_value"], immigrants=f["migrants"], aid_received=f["aid_received"])
        for g in GOODS:
            source["export_"+g] += f["trade_"+g]
            target["import_"+g] += f["trade_"+g]
        if f["trades"]:
            trade_partners[a].add(b)
            trade_partners[b].add(a)
        if f["migrants"]:
            migrant_partners[a].add(b)
            migrant_partners[b].add(a)
    meals = {r["id"]:(r["owner"],r["consumption"]["food_need"],r["consumption"]["food_eaten"]) for r in record["regions"]}
    _, gaps = disparity(meals)
    for r in record["regions"]:
        c, p, meal, d = data[r["owner"]], r["production"], r["consumption"], r["demography"]
        c.update(food_need=meal["food_need"],food_eaten=meal["food_eaten"],food_deficit=meal["food_unmet"],
                 births=d["births"],deaths=d["deaths"],withheld_workers=p["withheld_workers"],
                 within_country_ration_gap=gaps[r["id"]])
        for g in GOODS:
            c["produced_"+g] += p["produced"][g]
            c["used_"+g] += p["used"][g]
            c["meal_used_"+g] += meal["used"][g]
    for r in record["politics"]["regions"]:
        c = data[r["owner"]]
        aid = r["closing"]["evidence"].get("foreign_aid", {})
        exposed = aid.get("released_food",0)>0 or aid.get("received_food",0)>0
        if exposed:
            c["aid_exposed_region_years"] += 1
        for name, g in r["closing"]["groups"].items():
            c.update(member_years=g["members"], support_x_members=g["members"]*g["support"],
                     discontent_x_members=g["members"]*g["discontent"])
            if exposed and g["members"]:
                prefix = "aid_"+name+"_"
                direct = g.get("foreign_aid_support_delta", 0)
                sign = "positive" if direct>0 else "negative" if direct<0 else "zero"
                c[prefix+sign] += 1
                c[prefix+"members"] += g["members"]
                c[prefix+"delta_x_members"] += g["members"]*direct
    for r in record["collective"]["regions"]:
        for g in r["groups"].values():
            data[r["owner"]].update(active_group_years=int(g["action"] in ACTIVE), participants=g["participants"])
    for response in record["collective"]["responses"]:
        data[response["id"]]["policy_changes"] += int(response["before"] != response["after"])
    for r in record["competition"]["countries"]:
        data[r["id"]]["turnovers"] += int(r["election"]["turnover"])
    for node in record["domestic"]["nodes"]:
        data[node["owner"]]["civil_freight_food"] += node["cost_food"]
    for levy in gov["levies"]:
        for g in GOODS:
            data[levy["owner"]]["refused_"+g] += levy["refused"][g]
    result = {}
    for r in record["countries"]:
        i = r["id"]
        c, account = data[i], cash[i]
        c.update(trade_partner_years=len(trade_partners[i]), migration_partner_years=len(migrant_partners[i]))
        c.update({k:account["totals"][k] for k in FISCAL})
        opening, closing = r["opening"], r["closing"]
        if (opening["cash"]+c["export_value"]-c["import_value"] != closing["cash"] or
                opening["population"]+c["births"]-c["deaths"]+c["immigrants"]-c["emigrants"] != closing["population"]):
            raise ValueError("independent national cash or population closure failed")
        for g in GOODS:
            c["levied_"+g] = account["totals"]["levied_"+g]
            private = (account["private_open"][g] + c["produced_"+g] - c["used_"+g] - c["meal_used_"+g] +
                       c["import_"+g] - c["export_"+g] - c["levied_"+g])
            public = account["public_open"][g] + c["levied_"+g]
            if g == "food":
                private += c["relief_food"] - c["trade_freight_food"] - c["civil_freight_food"]
                public += (c["aid_received"] - c["aid_sent"] - c["aid_freight_food"] - c["relief_food"]
                           - c["public_freight_food"] - c["public_spoil_food"] - c["collection_cost_food"])
            else:
                public -= c["works_"+g]
            if (private,public) != (account["private_close"][g],account["public_close"][g]):
                raise ValueError(f"national private/public account mismatch: {i}/{g}")
        result[i] = {**c, "opening_population":opening["population"], "closing_population":closing["population"],
                     "opening_cash":opening["cash"], "closing_cash":closing["cash"],
                     **{"closing_"+s+"_"+g:account[s+"_close"][g] for s in ("private","public") for g in GOODS}}
    return result


def rates(c):
    return {"deficit_share":_ratio(c["food_deficit"],c["food_need"]),
            "within_country_disparity":_ratio(c["within_country_ration_gap"],c["food_need"]),
            "mean_support":_ratio(c["support_x_members"],c["member_years"]),
            "mean_discontent":_ratio(c["discontent_x_members"],c["member_years"])}


def pair_years(record, listings, flows, capacities):
    section = record.get("diplomacy")
    diplomatic = {} if section is None else {(p["a"],p["b"]):p for p in section["pairs"]}
    if section is not None and diplomatic.keys() != set(listings):
        raise ValueError("diplomacy misses a country pair")
    counts = defaultdict(Counter)
    for e in (section or {}).get("events", []):
        if e["kind"] not in KINDS:
            raise ValueError("unrecognized diplomatic event "+e["kind"])
        counts[e["a"],e["b"]]["event_"+e["kind"]] += 1
    results = {}
    for a,b in listings:
        pair = diplomatic.get((a,b))
        metrics = dict.fromkeys(PAIR_POLICY, 0)
        state = dict.fromkeys((*RELATION,*(s+k for s in ("ab_","ba_") for k in DIRECTION_POLICY)))
        if pair:
            policy = pair["policy"]
            ds = policy["directions"]
            metrics.update(observations=1, agreement_years=int(policy["agreement_active"]),
                           agreements_started=int(policy["agreement_started"]),
                           trade_restriction_direction_years=sum(d["trade_limit_permille"]<1000 for d in ds),
                           exit_restriction_direction_years=sum(d["migration_limit_permille"]<1000 for d in ds),
                           entry_restriction_direction_years=sum(d["migration_accept_permille"]<1000 for d in ds),
                           aid_requested_directions=sum(bool(d["aid_request"]) for d in ds),
                           aid_offered_directions=sum(bool(d["aid_offer"]) for d in ds),
                           aid_accepted_directions=sum(bool(d["aid_accepted"]) for d in ds),
                           aid_authorized=sum(d["aid_quantity"] for d in ds))
            state = {k:pair["closing"][k] for k in RELATION}
            for d in ds:
                prefix = "ab_" if d["source"]==a else "ba_"
                state.update({prefix+k:d[k] for k in DIRECTION_POLICY})
            for f in pair["flows"]["directions"]:
                direction = f["source"],f["target"]
                posted = flows[direction]
                if (any(f["goods"][g]!=posted["trade_"+g] for g in GOODS) or
                    f["trade_value"]!=posted["trade_value"] or f["migrants"]!=posted["migrants"] or
                    f["aid_sent"]!=posted["aid_dispatched"] or f["aid_received"]!=posted["aid_received"]):
                    raise ValueError("pair observation differs from physical account")
                if policy["agreement_active"]:
                    metrics["agreement_directions_kept"] += int(bool(f["access_kept"]))
                    metrics["agreement_directions_breached"] += int(bool(f["agreement_breach"]))
                    metrics["agreement_directions_no_opportunity"] += int(not f["trade_opportunity"])
            if sum(metrics[k] for k in ("agreement_directions_kept","agreement_directions_breached",
                                        "agreement_directions_no_opportunity")) != 2*int(policy["agreement_active"]):
                raise ValueError("treaty directions lack a unique performance classification")
            change = state["relation"]-pair["opening"]["relation"]
            metrics.update(relation_improved=int(change>0),relation_worsened=int(change<0))
        metrics.update({"event_"+k:counts[a,b]["event_"+k] for k in KINDS})
        metrics["physical_capacity"] = capacities[a,b]
        metrics.update({prefix+k:flows[src,dst][k] for prefix,src,dst in (("ab_",a,b),("ba_",b,a)) for k in SHIP})
        results[a,b] = metrics, state
    return results


def _seed(job):
    from civsim.diplomacy import diplomacy_snapshot, start_diplomacy, step_diplomacy
    seed, horizons, folder = job
    data = {k:[] for k in ("runs","countries","pairs","borders")}
    with ExitStack() as stack:
        panels = {k:stack.enter_context(compressed(Path(folder)/f"{seed}-{k}.gz")) for k in PANELS}
        writers = {"events":emit(panels["events"], EVENT, True)}
        for arm in ARMS:
            world = regionalize(generate_world(seed))
            sim = start_diplomacy(world)
            initial, legacy = _sha(diplomacy_snapshot(sim)), _sha(collective_snapshot(sim.collective))
            owners = {r.id:r.owner for r in world.regions}
            initial_countries = {n.id:(n.population,n.cash) for n in world.nations}
            listings = list(combinations(sorted(initial_countries), 2))
            countries, pairs, edges = defaultdict(Counter),defaultdict(Counter),defaultdict(Counter)
            digest, projected = hashlib.sha256(), hashlib.sha256()
            for year in range(1, max(horizons)+1):
                record = step_diplomacy(sim, year, arm)
                line = canonical_line(record)
                digest.update(line)
                if arm == "A":
                    if "diplomacy" in record: raise ValueError("A must be the unmodified control")
                elif arm == "B":
                    projected.update(canonical_line({k:v for k,v in record.items() if k!="diplomacy"}))
                key = {"seed":seed,"arm":arm,"year":year}
                edge, flow, cap = physical(record, world.borders, owners)
                annual = country_years(record, flow)
                relation = pair_years(record, listings, flow, cap)
                observed = {r["id"]:r for r in record.get("diplomacy",{}).get("countries",[])}
                for i,c in annual.items():
                    countries[i].update({k:c[k] for k in NATIONAL})
                    country = observed.get(i)
                    row = {**key,"owner":i,**c,"opening_party":country["party"] if country else None,
                           "prior_shortage_permille":country["shortage_permille"] if country else None}
                    if "country-years" not in writers: writers["country-years"] = emit(panels["country-years"], tuple(row), True)
                    writers["country-years"].writerow(row)
                for (a,b), (measures, state) in relation.items():
                    pairs[a,b].update(measures)
                    row = {**key,"a":a,"b":b,**measures,**state}
                    if "pair-years" not in writers: writers["pair-years"] = emit(panels["pair-years"],tuple(row),True)
                    writers["pair-years"].writerow(row)
                for i,v in edge.items(): edges[i].update(v)
                for event in record.get("diplomacy",{}).get("events",[]):
                    writers["events"].writerow({**key,**{k:event[k] for k in ("a","b","kind","source","target")},
                        "details_json":json.dumps(event,sort_keys=True,ensure_ascii=False,separators=(",",":"))})
                if year not in horizons: continue
                total = Counter()
                for i,c in countries.items():
                    p, money = initial_countries[i]
                    snapshot = {**c, **{k:annual[i][k] for k in ENDPOINT}, "opening_population":p,"opening_cash":money}
                    total.update(snapshot)
                    data["countries"].append({**key,"owner":i,**snapshot,**rates(snapshot)})
                pair_metrics = Counter()
                for (a,b),c in pairs.items():
                    state = relation[a,b][1]
                    data["pairs"].append({**key,"a":a,"b":b,**c,**state})
                    pair_metrics.update(c)
                for road in world.borders:
                    for x,y in ((road.a,road.b),(road.b,road.a)):
                        data["borders"].append({**key, "source_region":x,"target_region":y,"source_country":owners[x],
                            "target_country":owners[y],"distance":road.distance,"shared_capacity_per_year":road.capacity,
                            **edges[x,y]})
                foreign = {k:pair_metrics["ab_"+k]+pair_metrics["ba_"+k] for k in SHIP}
                data["runs"].append({**key,"initial_sha256":initial,"initial_5d_sha256":legacy,"years_sha256":digest.hexdigest(),
                    "projected_5d_sha256":digest.hexdigest() if arm=="A" else projected.hexdigest() if arm=="B" else None,
                    **total,**rates(total), **{k:pair_metrics[k] for k in (*PAIR_POLICY,*("event_"+x for x in KINDS),"physical_capacity")},
                    **{"border_"+k:v for k,v in foreign.items()},
                    **{"closing_mean_"+k:fmean(p[1][k] for p in relation.values()) if arm!="A" else None for k in RELATION}})
    return data


def _assemble(panel, seeds, folder, out):
    with compressed(out) as output:
        first = None
        for seed in seeds:
            with gzip.open(folder/f"{seed}-{panel}.gz", "rt", encoding="utf8", newline="") as stream:
                header = stream.readline()
                if first is None:
                    output.write(header)
                    first = header
                elif header != first:
                    raise ValueError("inconsistent panel schema")
                shutil.copyfileobj(stream, output)


DELTAS = ("closing_population","food_need","food_deficit","deficit_share","within_country_disparity",
          "border_trade_value",*("border_trade_"+g for g in GOODS),"border_migrants","aid_received","border_aid_freight_food",
          "border_trade_denied","border_exit_denied","border_entry_denied","agreement_years","active_group_years","mean_support","turnovers")


def run_study(output, *, sample, seeds=20, horizons=(50,100,200), workers=8, verify=None):
    output = Path(output)
    if os.path.lexists(output): raise FileExistsError(output)
    horizons = tuple(horizons)
    if (sample not in ("dev","holdout") or type(seeds) is not int or not 1<=seeds<=20 or not horizons
            or any(type(y) is not int or y<=0 for y in horizons) or len(set(horizons))!=len(horizons)
            or type(workers) is not int or workers<1):
        raise ValueError("invalid cohorts, horizons or workers")
    start = time.perf_counter()
    output.parent.mkdir(parents=True,exist_ok=True)
    first = 0 if sample=="dev" else 20
    bound = range(first,first+seeds)
    with TemporaryDirectory(dir=output.parent,prefix=".diplomacy-") as temp:
        stage = Path(temp,"result")
        stage.mkdir()
        jobs = [(s,horizons,temp) for s in bound]
        if workers==1: results=list(map(_seed,jobs))
        else:
            with ProcessPoolExecutor(max_workers=min(workers,seeds)) as pool: results=list(pool.map(_seed,jobs))
        tables = {k:[r for partial in results for r in partial[k]] for k in results[0]}
        runs = tables["runs"]
        historical = {(int(r["seed"]),int(r["year"])):r for r in _read(ARCHIVE/sample/"runs.csv") if r["arm"]=="on"}
        lookup = {(r["seed"],r["arm"],r["year"]):r for r in runs}
        matches = Counter()
        paired = []
        for r in runs:
            s,arm,y = r["seed"],r["arm"],r["year"]
            control = lookup[s,"A",y]
            if r["initial_sha256"]!=control["initial_sha256"]:
                raise ValueError("diplomatic experiments differ at opening")
            if arm=="B" and r["projected_5d_sha256"] != control["years_sha256"]:
                raise ValueError("observation changed control history")
            if arm in ("A","B") and y in (50,100,200):
                saved = historical[s,y]
                if (r["initial_5d_sha256"],r["projected_5d_sha256"]) != (saved["initial_sha256"],saved["years_sha256"]):
                    raise ValueError(f"5D archive mismatch at {s} {arm} {y}")
                matches[arm]+=1
            comparisons = {"A":(),"B":("A",),"C":("B",),"D":("C","B")}
            for other in comparisons[arm]:
                paired.append({"seed":s,"year":y,"arm":arm,"against":other,
                               **{"delta_"+k:r[k]-lookup[s,other,y][k] for k in DELTAS}})
        table_means = []
        for arm in ARMS:
            for y in horizons:
                group = [r for r in runs if r["arm"]==arm and r["year"]==y]
                means = {k:(fmean(r[k] for r in group) if isinstance(v,(int,float)) else None)
                         for k,v in group[0].items() if k not in KEY and not k.endswith("sha256")}
                table_means.append({"arm":arm,"year":y,"seeds":len(group),**means,
                    "pooled_deficit_share":_ratio(sum(r["food_deficit"] for r in group),sum(r["food_need"] for r in group))})
        for k in PANELS: _assemble(k, bound, Path(temp), stage/(k+".csv.gz"))
        for k in ("runs","countries","pairs"): _write(stage/(k+".csv"),tables[k])
        with compressed(stage/"borders.csv.gz") as stream:
            emit(stream,tuple(tables["borders"][0]),True).writerows(tables["borders"])
        _write(stage/"means.csv",table_means)
        _write(stage/"paired.csv",paired)
        manifest = {p.name:digest_file(p) for p in sorted(stage.iterdir())}
        if verify and any(digest_file(Path(verify)/name)!=value for name,value in manifest.items()):
            raise ValueError("scientific tables differ from independent primary execution")
        meta = {"sample":sample,"first_seed":first,"seeds":seeds,"workers":min(workers,seeds),"horizons":horizons,
                "paths":seeds*len(ARMS),"annual_transitions":seeds*len(ARMS)*max(horizons),
                "archive_5d_A":matches["A"],"archive_5d_B":matches["B"],"replayed_checkpoints":len(runs) if verify else 0,
                "table_sha256":manifest,"python":platform.python_version(),"wall_seconds":time.perf_counter()-start}
        _json(stage/"execution.json",meta)
        if os.path.lexists(output): raise FileExistsError(output)
        stage.rename(output)
    return meta


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out",required=True,type=Path)
    p.add_argument("--sample",required=True,choices=("dev","holdout"))
    p.add_argument("--seeds",type=int,default=20)
    p.add_argument("--workers",type=int,default=8)
    p.add_argument("--horizons",default="50,100,200")
    p.add_argument("--verify-against",type=Path)
    args = p.parse_args()
    print(json.dumps(run_study(args.out,sample=args.sample,seeds=args.seeds,workers=args.workers,
                               horizons=tuple(int(y) for y in args.horizons.split(",")),verify=args.verify_against)))


if __name__=="__main__": main()
