"""Replay two single-year choices from identical openings on development seed 0's feedback path."""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from civsim.government import _advance_fiscal
from civsim.model import generate_world
from civsim.politics import political_snapshot, start_political, step_political
from civsim.regions import regionalize
from civsim.storage import canonical_line


def _digest(value):
    return sha256(canonical_line(value)).hexdigest()


def _evidence(record, owner):
    gov = record["government"]
    members = {r["id"] for r in record["regions"] if r["owner"] == owner}
    acc = next(a for a in gov["accounts"] if a["id"] == owner)
    rows = []
    for r in record["regions"]:
        if r["owner"] != owner:
            continue
        i = r["id"]
        vault = next(d for d in gov["depots"] if d["region"] == i)
        tax = next(d for d in gov["levies"] if d["region"] == i)
        rows.append({"region": i, "population": r["opening"]["population"], "soil_open": r["opening"]["soil"],
                     "produced": r["production"]["produced"], "meal": r["consumption"],
                     "depot_open": vault["opening"], "levied": tax["levied"], "depot_close": vault["closing"]})
    return {"world_unmet": sum(r["consumption"]["food_unmet"] for r in record["regions"]),
            "world_harvest": sum(r["production"]["produced"]["food"] for r in record["regions"]),
            "country_unmet": sum(r["meal"]["food_unmet"] for r in rows),
            "year_record_sha256": _digest(record), "budget": acc["decision"]["budget"],
            "country_totals": acc["totals"], "regions": rows,
            "projects": [p for p in gov["works"]["projects"] if p["owner"] == owner],
            "works_shipments": [s for s in gov["works"]["shipments"] if s["owner"] == owner],
            "relief_shipments": [s for s in gov["relief"]["shipments"] if s["owner"] == owner],
            "private_shipments": [s for s in record["domestic"]["shipments"] if s["source"] in members],
            "border_trades": [t for t in record["border_market"]["trades"]
                              if t["buyer"] in members or t["seller"] in members],
            "roads": [r for r in gov["roads"] if r["owner"] == owner]}


def _one_year(opening, year, prior_digest, actual):
    before = _digest(political_snapshot(opening))
    records = []
    for feedback in (False, True):
        branch = deepcopy(opening)
        if _digest(political_snapshot(branch)) != before:
            raise ValueError("branch differs from complete opening")
        records.append(_advance_fiscal(branch.fiscal, year, "integrated",
                                       political_open=branch.states, feedback=feedback))
    off, on = records
    if canonical_line(actual) != canonical_line(on) or _digest(political_snapshot(opening)) != before:
        raise ValueError("copied approval failed to reproduce the actual path or changed the source")
    if off["politics"]["countries"] != on["politics"]["countries"]:
        raise ValueError("candidate menus or rankings differ across branches")
    for a, b in zip(off["government"]["accounts"], on["government"]["accounts"], strict=True):
        if a["decision"]["candidates"] != b["decision"]["candidates"]:
            raise ValueError("economic constraints or candidate inputs changed")
    changed = [c for c in on["politics"]["countries"] if c["recommendation"]["changed"]]
    if len(changed) != 1:
        raise ValueError("the witness requires exactly one changed national choice")
    owner, ranking = changed[0]["id"], changed[0]["recommendation"]
    arm_keys = ("economic_choice", "political_choice")
    selected = {(r["action"], r["target_region"], tuple(r["target_edge"] or ()))
                for r in (ranking[k] for k in arm_keys)}
    candidates = [c for c in ranking["candidates"]
                  if (c["action"], c["target_region"], tuple(c["target_edge"] or ())) in selected]
    return {"seed": opening.world.seed, "year": year, "prior_feedback": True, "prior_years": year-1,
            "prior_records_sha256": prior_digest, "common_opening_sha256": before,
            "changed_country": owner, "changed_country_count": len(changed),
            "funded_candidates": candidates,
            "political_memory": [m for m in opening.states.values() if m["owner"] == owner],
            **{k: ranking[k] for k in arm_keys},
            "economic_approval": _evidence(off, owner), "political_approval": _evidence(on, owner)}


def study():
    sim = start_political(regionalize(generate_world(0)))
    digest = sha256()
    cases = []
    for year in range(1, 40):
        opening = deepcopy(sim) if year in (36, 39) else None
        actual = step_political(sim, year, True)
        if opening is not None:
            cases.append(_one_year(opening, year, digest.hexdigest(), actual))
        digest.update(canonical_line(actual))
    return {"development_seed": 0, "prior_policy": "integrated", "cases": cases}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    data = json.dumps(study(), ensure_ascii=False, indent=2) + "\n"
    if args.out:
        with args.out.open("x", encoding="utf-8", newline="\n") as output:
            output.write(data)
    else:
        print(data, end="")
