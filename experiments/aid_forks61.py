"""Invoice-level counterfactuals with fixed approvals, geography and domestic policy."""
import argparse
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

from civsim.diplomacy61 import fork61, snapshot61, start61, step61
from civsim.model import generate_world
from civsim.regions import regionalize
from experiments.aid_incidence61 import meal_incidence
from experiments.phase5a import _sha
from experiments.phase5d import _json
from experiments.phase6a import digest_file
from experiments.publication import publish_file


def _open(seed):
    return start61(regionalize(generate_world(seed)))


def _check_shared(actual, alternative):
    for a,b in zip(actual["regions"],alternative["regions"],strict=True):
        if a["opening"]!=b["opening"] or a["production"]!=b["production"]:
            raise ValueError("opening stocks, residents or pre-intervention production differ")
    da,db = (r["diplomacy"] for r in (actual,alternative))
    if da["countries"]!=db["countries"] or da["borders"]!=db["borders"]:
        raise ValueError("decision inputs differ")
    for a,b in zip(da["pairs"],db["pairs"],strict=True):
        if (a["a"],a["b"],a["opening"],a["policy"])!=(b["a"],b["b"],b["opening"],b["policy"]):
            raise ValueError("another bilateral decision changed")
    if ([a["decision"] for a in actual["government"]["accounts"]]
            != [a["decision"] for a in alternative["government"]["accounts"]]):
        raise ValueError("other public spending decisions changed")


def view(row, donor, recipient):
    ctx = row["diplomacy"]
    direction = next(d for p in ctx["pairs"] for d in p["policy"]["directions"]
                     if (d["source"],d["target"])==(donor,recipient))
    aid = ctx["physical"]["aid"]
    invoices = [s for s in aid["shipments"] if (s["donor"],s["recipient"])==(donor,recipient)]
    account = next(d for d in aid["directions"] if (d["source"],d["target"])==(donor,recipient))
    all_donor_cost = sum(s["quantity"]+s["cost_food"] for s in aid["shipments"] if s["donor"]==donor)
    public = {r["region"]:r for r in row["government"]["depots"]}
    groups = {r["id"]:r["closing"]["groups"] for r in row["politics"]["regions"]}
    regions, countries = {}, {}
    for r in row["regions"]:
        i,n = r["id"],r["owner"]
        meal = r["consumption"]
        regions[str(i)] = {"owner":n,"food_eaten":meal["food_eaten"],"food_unmet":meal["food_unmet"],
                           "population":r["closing"]["population"],"public_food":public[i]["closing"]["food"],
                           "aid_received":sum(s["received"] for s in aid["shipments"] if s["target"]==i),
                           "aid_released":sum(s["quantity"]+s["cost_food"] for s in aid["shipments"] if s["source"]==i)}
        c = countries.setdefault(str(n),Counter())
        c.update({k:v for k,v in regions[str(i)].items() if k!="owner"})
        regions[str(i)]["groups"] = {name:{k:g.get(k,0) for k in ("members","support","discontent","foreign_aid_support_delta")}
                                     for name,g in groups[i].items()}
    return {"annual_sha256":_sha(row),"planned_budget":direction["aid_budget"],"shortest_distance":direction["border_distance"],
            "estimated_freight":direction["aid_freight_estimate"],"total_donor_debit":all_donor_cost,
            "direction":account,"invoices":invoices,"regions":regions,"countries":countries}


def compare(seed, year, arm, donor, recipient, treatment):
    sim = _open(seed)
    for y in range(1,year):
        step61(sim,y,arm)
    opening = _sha(snapshot61(sim))
    toggle = {"capped":True} if treatment=="add_cap" else {"suppress_aid":(donor,recipient)}
    actual, alternative = fork61(sim,year,arm,**toggle)
    _check_shared(actual,alternative)
    if _sha(snapshot61(sim))!=opening or _sha(step61(sim,year,arm))!=_sha(actual):
        raise ValueError("fork failed deterministic reconstruction of normal year")
    left,right = (view(r,donor,recipient) for r in (actual,alternative))
    changed = {}
    for i,region in left["regions"].items():
        other = right["regions"][i]
        changed[i] = {k:other[k]-region[k] for k in ("food_eaten","food_unmet","public_food","population",
                                                     "aid_received","aid_released")}
    target_regions = {str(s["target"]) for s in left["invoices"]}
    return {"seed":seed,"year":year,"arm":arm,"donor":donor,"recipient":recipient,"intervention":treatment,
            "opening_sha256":opening,"actual":left,"alternative":right,"delta_alternative_minus_actual":changed,
            "delta_eaten_original_receiving_depots":sum(changed[i]["food_eaten"] for i in target_regions),
            "delta_eaten_recipient_country":sum(changed[i]["food_eaten"] for i,r in left["regions"].items() if r["owner"]==recipient),
            "delta_eaten_world":sum(r["food_eaten"] for r in changed.values())}


def select_meal_case():
    # Supplementary development illustration: select by all-aid meal contrast, then remove one funded direction.
    sim = _open(0)
    best = None
    for y in range(1,51):
        row = step61(sim,y,"B")
        shipments = row["diplomacy"]["physical"]["aid"]["shipments"]
        if not shipments:
            continue
        delta = meal_incidence(row,sim.world)
        for s in shipments:
            rank = (abs(delta[s["target"]]),s["received"],-y,-s["target"],-s["donor"])
            if best is None or rank>best[0]:
                best = (rank,y,s["donor"],s["recipient"])
    return None if best is None else best[1:]


def run(out,verify=None):
    out = Path(out)
    if out.exists() or out.is_symlink():
        raise FileExistsError(out)
    cases = [compare(0,4,"E",2,3,t) for t in ("add_cap","suppress_direction")]
    selected = select_meal_case()
    if selected:
        y,donor,recipient = selected
        cases.append(compare(0,y,"B",donor,recipient,"suppress_direction"))
    result = {"difference":"alternative minus actual, food units and resident counts",
              "selection":"Issue 13 twice. Supplement: among seed 0 B years 1–50, largest absolute all-aid meal change at an actual receiving depot. Break ties by net load then earliest year, region, donor.",
              "cases":cases}
    out.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=out.parent) as tmp:
        data = Path(tmp)/"cases.json"
        _json(data,result)
        if verify and digest_file(data)!=digest_file(verify):
            raise ValueError("counterfactual replay differs")
        publish_file(data,out)
    print(f"{len(cases)} same-opening forks: {digest_file(out)}")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",required=True,type=Path)
    parser.add_argument("--verify",type=Path)
    a=parser.parse_args()
    run(a.out,a.verify)
