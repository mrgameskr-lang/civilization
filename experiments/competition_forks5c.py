"""Realized single-year cabinet or standing-tax comparisons on a common opening."""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from civsim.model import GOODS, generate_world
from civsim.regions import regionalize
from civsim.storage import canonical_line
from experiments.capacity5 import RoadCapacityAudit
from experiments.political_forks5 import _evidence


def _digest(value):
    return sha256(canonical_line(value)).hexdigest()


def _country(record, owner, capacities):
    gov = record["government"]
    a = next(r for r in gov["accounts"] if r["id"] == owner)
    cabinet = next(r for r in record["competition"]["countries"] if r["id"] == owner)
    local = [r for r in record["regions"] if r["owner"] == owner]
    levies = [l for l in gov["levies"] if l["owner"] == owner]
    works = [p for p in gov["works"]["projects"] if p["owner"] == owner]
    relief = [s for s in gov["relief"]["shipments"] if s["owner"] == owner]
    freight = sum(s["cost_food"] for group in (gov["works"]["shipments"], relief)
                  for s in group if s["owner"] == owner)
    spoil = sum(d["spoil_food"] for d in gov["depots"] if d["owner"] == owner)
    spent = {g:sum(p["used"][g] for p in works) for g in GOODS}
    delivered = sum(s["quantity"] for s in relief)
    public_labor = sum(p["workers"] for p in works)
    remaining = sum(r["production"]["workers"] + r["production"]["soil_care"]["workers"]
                    + r["production"]["investment"]["construction_labor"] for r in local)
    if sum(r["opening"]["population"]//2 for r in local) != public_labor + remaining:
        raise ValueError("public labor unavailable after accounting for private production")
    deposits = {g:sum(l["deposited"][g] for l in levies) for g in GOODS}
    close = {g:a["public_open"][g] + deposits[g] - spent[g] for g in GOODS}
    close["food"] -= freight + spoil + delivered
    if close != a["public_close"]:
        raise ValueError("warehouse change differs from receipts, costs and shipments")
    choice = {k:a["decision"][k] for k in ("action","target_region","quantity","budget","selected_score")}
    edge = a["decision"]["target_edge"]
    choice["target_edge"] = list(edge) if edge is not None else None
    return {"owner":owner, "governing_faction":cabinet["governing_faction"], "tariff":cabinet["tariff"],
            "choice":choice, "executed":a["totals"]["action_executed"],
            "opening_vault":a["public_open"], "closing_vault":close, "deposited":deposits,
            "standing":{g:sum(l["standing_levy"][g] for l in levies) for g in GOODS},
            "supplemental_food":sum(l["extra_levy"]["food"] for l in levies),
            "handling_food":sum(l["handling_used"]["food"] for l in levies),
            "works_spent":spent, "public_labor":public_labor, "other_workers":remaining,
            "relief_food":delivered, "public_freight_food":freight, "warehouse_spoil":spoil,
            "capacities":dict(capacities[owner]), "harvest":sum(r["production"]["produced"]["food"] for r in local),
            "need":sum(r["consumption"]["food_need"] for r in local),
            "unmet":sum(r["consumption"]["food_unmet"] for r in local)}


def run_case(kind, seed, year, owner):
    from civsim.competition import (competition_snapshot, fork_election_year, fork_tax_year,
                                   start_competition, step_competition)
    if kind not in ("election","tax") or seed not in range(20) or year <= 0 or owner not in range(8):
        raise ValueError("expected an election or tax case in the development cohort")
    world = regionalize(generate_world(seed))
    sim = start_competition(world)
    audit = RoadCapacityAudit(world)
    prefix = sha256()
    for y in range(1, year):
        record = step_competition(sim, y, "C", tax_policy="fixed")
        prefix.update(canonical_line(record))
        audit.observe(record)
    opening = _digest(competition_snapshot(sim))
    if kind == "election":
        labels, records = ("elected","kept_incumbent"), fork_election_year(sim,year,owner)
    else:
        labels, records = ("fixed","platform"), fork_tax_year(sim,year)
    if opening != _digest(competition_snapshot(sim)):
        raise ValueError("single-year branches changed the shared opening")
    actual = step_competition(sim, year, "C", tax_policy="fixed")
    if canonical_line(actual) != canonical_line(records[0]):
        raise ValueError("first branch differs from the natural C trajectory")
    a,b = records
    if kind == "tax":
        if (a["government"]["works"] != b["government"]["works"] or a["border_market"] != b["border_market"]
                or [r["production"] for r in a["regions"]] != [r["production"] for r in b["regions"]]
                or [s["decision"] for s in a["government"]["accounts"]] !=
                   [s["decision"] for s in b["government"]["accounts"]]):
            raise ValueError("pre-collection economic inputs differ in tax branches")
    else:
        first = [x["decision"] for x in a["government"]["accounts"]]
        other = [x["decision"] for x in b["government"]["accounts"]]
        if any(x != y for x,y in zip(first,other,strict=True) if x["owner"] != owner):
            raise ValueError("single-country cabinet replacement changed another country's approval")
    result = {"kind":kind,"seed":seed,"year":year,"focus_country":owner,"prior_arm":"C","prior_tax_policy":"fixed",
              "prior_years":year-1, "prior_ledger_sha256":prefix.hexdigest(), "common_opening_sha256":opening}
    for label, record in zip(labels,records,strict=True):
        capacities = deepcopy(audit).observe(record)
        cab = next(c for c in record["competition"]["countries"] if c["id"] == owner)
        ranking = next(c["recommendation"] for c in record["politics"]["countries"] if c["id"] == owner)
        local = _evidence(record,owner)
        local["levy_receipts"] = [l for l in record["government"]["levies"] if l["owner"] == owner]
        result[label] = {"countries":[_country(record, i, capacities) for i in sorted(capacities)],
                         "election":cab["election"],"outgoing_choice":cab["outgoing_choice"],
                         "economic_choice":ranking["economic_choice"],"governing_choice":ranking["political_choice"],
                         "local_evidence":local,"record_sha256":_digest(record)}
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind",choices=("election","tax"))
    parser.add_argument("--seed",type=int,required=True)
    parser.add_argument("--year",type=int,required=True)
    parser.add_argument("--owner",type=int,required=True)
    parser.add_argument("--out",type=Path)
    args=parser.parse_args()
    data=json.dumps(run_case(args.kind,args.seed,args.year,args.owner),ensure_ascii=False,indent=2)+"\n"
    if args.out:
        with args.out.open("x",encoding="utf-8",newline="\n") as output:
            output.write(data)
    else:
        print(data,end="")
