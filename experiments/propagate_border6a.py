"""Follow the two predefined development trade forks for one ordinary endogenous year."""
import argparse
import csv
import gzip
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from civsim.collective import _commit_collective
from civsim.diplomacy import (_diplomatic_year, diplomacy_snapshot, fork_diplomacy_year,
                               start_diplomacy, step_diplomacy)
from civsim.model import GOODS, generate_world
from civsim.regions import regionalize
from experiments.diplomacy_forks6a import choose, validate_intervention
from experiments.phase5a import _sha
from experiments.phase5d import _json
from experiments.phase6a import digest_file
from experiments.publication import publish_file


def _check(ok,message):
    if not ok:
        raise ValueError(message)


def _opened_step(sim,year,setting):
    # Commit the complete staged transition just as step_diplomacy does, then restore its public entry point.
    fiscal,row = _diplomatic_year(sim,year,"D",setting)
    _commit_collective(sim.collective,fiscal,row)
    sim.pairs = {(p["a"],p["b"]):deepcopy(p["closing"]) for p in row["diplomacy"]["pairs"]}
    sim.arm = "D"
    return row


def _region_metrics(row):
    food_imports = Counter()
    owners = {r["id"]:r["owner"] for r in row["regions"]}
    for t in row["border_market"]["trades"]:
        if t["good"]=="food" and owners[t["seller"]]!=owners[t["buyer"]]:
            food_imports[t["buyer"]] += t["quantity"]
    result = {}
    for r in row["regions"]:
        metrics = {"opening_population":r["opening"]["population"],"closing_population":r["closing"]["population"],
                   "food_imports":food_imports[r["id"]],"food_need":r["consumption"]["food_need"],
                   "food_deficit":r["consumption"]["food_unmet"]}
        for g in GOODS:
            metrics["opening_"+g] = r["opening"]["stock"][g]
            metrics["produced_"+g] = r["production"]["produced"][g]
        result[r["id"]] = metrics
    return result


def _compare_frame(actual,opened):
    ids = {r["id"]:r["owner"] for r in actual["regions"]}
    regular,changed = _region_metrics(actual),_region_metrics(opened)
    _check(ids=={r["id"]:r["owner"] for r in opened["regions"]},"branch region identities diverged")
    def compare(a,b):
        return {"actual":dict(a),"opened":dict(b),"opened_minus_actual":{k:b[k]-a[k] for k in a}}
    regions,totals = [],[Counter(),Counter()]
    for i,owner in sorted(ids.items()):
        regions.append({"region":i,"owner":owner,**compare(regular[i],changed[i])})
        totals[0].update(regular[i])
        totals[1].update(changed[i])
    return {"year":actual["year"],"actual_annual_sha256":_sha(actual),"opened_annual_sha256":_sha(opened),
            "world":compare(*totals),"regions":regions,
            "production_changed_regions":{g:[r["region"] for r in regions if r["opened_minus_actual"]["produced_"+g]]
                                          for g in GOODS}}


def _verify_carry(first,following):
    _check(following["year"]==first["year"]+1 and following["diplomacy"]["arm"]=="D"
           and following["diplomacy"]["intervention"] is None,"next year must use ordinary D")
    for left,right,key in ((first["regions"],following["regions"],"id"),
                           (first["countries"],following["countries"],"id"),
                           (first["government"]["depots"],following["government"]["depots"],"region"),
                           (first["politics"]["regions"],following["politics"]["regions"],"id"),
                           (first["competition"]["countries"],following["competition"]["countries"],"id")):
        _check({r[key]:r["closing"] for r in left}=={r[key]:r["opening"] for r in right},
               "region, country, warehouse or political closing state lost")
    prior,now = first["diplomacy"]["pairs"],following["diplomacy"]["pairs"]
    _check({(p["a"],p["b"]):p["closing"] for p in prior}=={(p["a"],p["b"]):p["opening"] for p in now},
           "bilateral memory did not carry into the next year")
    before,after = first["collective"]["regions"],following["collective"]["regions"]
    def groups(rows,field):
        return {(r["id"],name):group[field] for r in rows for name,group in r["groups"].items()}
    _check(groups(before,"closing")==groups(after,"prior"),"collective-action memory did not carry")
    edges = lambda roads,field: {(e["a"],e["b"]):e[field] for e in roads}
    _check(edges(first["government"]["roads"],"closing_units")==edges(following["government"]["roads"],"opening_units"),
           "domestic road stocks did not carry")


def follow_case(sim,case):
    year,setting = case["year"],case["intervention"]
    _check(case["arm"]=="D" and 0<=case["seed"]<20 and setting["kind"]=="open_trade",
           "follow-up requires a development trade case")
    digest = _sha(diplomacy_snapshot(sim))
    actual_sim,opened_sim = deepcopy(sim),deepcopy(sim)
    actual = step_diplomacy(actual_sim,year,"D")
    opened = _opened_step(opened_sim,year,setting)
    validate_intervention(actual,opened,setting)
    t = _compare_frame(actual,opened)
    standard,alternative = fork_diplomacy_year(sim,year,setting)
    t["actual_fork_sha256"],t["opened_fork_sha256"] = _sha(standard),_sha(alternative)
    _check(t["actual_annual_sha256"]==t["actual_fork_sha256"] and t["opened_annual_sha256"]==t["opened_fork_sha256"],
           "initial decision year differs from the frozen one-year fork")
    _check({r["id"]:r["production"] for r in actual["regions"]}=={r["id"]:r["production"] for r in opened["regions"]},
           "post-production intervention changed production")
    t["all_production_records_identical"] = True
    follow_actual,follow_opened = (step_diplomacy(branch,year+1,"D") for branch in (actual_sim,opened_sim))
    _verify_carry(actual,follow_actual)
    _verify_carry(opened,follow_opened)
    follow = _compare_frame(follow_actual,follow_opened)
    follow["both_use_ordinary_D"] = True
    _check(_sha(diplomacy_snapshot(sim))==digest,"source was mutated")
    return {**case,"opening_sha256":digest,"t":t,"t_plus_1":follow}


def run_followups(study,output,*,forks=None,verify=None):
    study,output = Path(study),Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    receipt = json.loads((study/"execution.json").read_text(encoding="utf8"))
    source = study/"pair-years.csv.gz"
    source_hash = digest_file(source)
    _check(receipt["sample"]=="dev" and receipt["seeds"]==20 and receipt["first_seed"]==0
           and max(receipt["horizons"])==200 and receipt["table_sha256"][source.name]==source_hash,
           "expected the verified original 20-seed development panel")
    with gzip.open(source,"rt",encoding="utf8",newline="") as stream:
        cases = [c for c in choose(csv.DictReader(stream)) if c["intervention"]["kind"]=="open_trade"]
    _check({c["selection"] for c in cases}=={"earliest","highest_exposure"} and len(cases)==2,
           "both prespecified selectors must have a natural trade case")
    original = {}
    if forks:
        frozen = json.loads(Path(forks).read_text(encoding="utf8"))
        _check(frozen["pair_years_sha256"]==source_hash,"unmatched source panel in published forks")
        original = {c["selection"]:c for c in frozen["cases"] if c["intervention"]["kind"]=="open_trade"}
    results = []
    for case in cases:
        sim = start_diplomacy(regionalize(generate_world(case["seed"])))
        for y in range(1,case["year"]):
            step_diplomacy(sim,y,"D")
        result = follow_case(sim,case)
        if forks:
            ref = original[case["selection"]]
            _check(all(ref[k]==v for k,v in case.items()) and ref["opening_sha256"]==result["opening_sha256"]
                   and ref["actual"]["annual_sha256"]==result["t"]["actual_annual_sha256"]
                   and ref["alternative"]["annual_sha256"]==result["t"]["opened_annual_sha256"],
                   "two-year reconstruction differs from published primary trade fork")
        results.append(result)
    output.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as temp:
        staged = Path(temp,"result.json")
        _json(staged,{"design":"Post-hoc development follow-up of the prespecified earliest and highest-exposure trade cases.",
                      "estimand":"One direction fully opened only at t. Both branches follow ordinary D at t+1.",
                      "differences":"opened minus actual. Food imports are gross private international food receipts.",
                      "pair_years_sha256":source_hash,"cases":results})
        if verify:
            _check(digest_file(staged)==digest_file(Path(verify)),"independent follow-up bytes differ")
        publish_file(staged,output)
    return len(results)


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--forks",type=Path)
    parser.add_argument("--verify",type=Path)
    opts = parser.parse_args()
    print(f"{run_followups(opts.study,opts.out,forks=opts.forks,verify=opts.verify)} two-year trade comparisons")
