"""Find the largest local first-year food shortfall increase in the development seeds."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from civsim.government import fiscal_snapshot, start_government, step_government
from civsim.model import generate_world
from civsim.regions import regionalize
from civsim.storage import canonical_line


def _pair(seed):
    opens, records = [], []
    for mode in ("none", "integrated"):
        sim = start_government(regionalize(generate_world(seed)))
        opens.append(canonical_line(fiscal_snapshot(sim)))
        records.append(step_government(sim, 1, mode))
    a, b = records
    if opens[0] != opens[1] or a["border_market"] != b["border_market"]:
        raise ValueError(f"initial world or border market differed in seed {seed}")
    for x, y in zip(a["regions"], b["regions"], strict=True):
        if any(x[k] != y[k] for k in ("id", "owner", "opening", "climate", "production")):
            raise ValueError(f"regional opening or production differed in seed {seed}")
    for rec in records:
        gov = rec["government"]
        if gov["works"]["projects"] or gov["works"]["shipments"] or gov["relief"]["shipments"]:
            raise ValueError(f"public work or relief confounds the tax comparison in seed {seed}")
    return sha256(opens[0]).hexdigest(), records


def _details(record, owner, target):
    gov = record["government"]
    members = {r["id"] for r in record["regions"] if r["owner"] == owner}
    nodes = {n["id"]: n for n in record["domestic"]["nodes"]}
    depots = {d["region"]: d for d in gov["depots"]}
    rows = []
    for levy in gov["levies"]:
        i = levy["region"]
        if i in members:
            rows.append({"region": i, "food_before_tax": levy["private_open"]["food"],
                         "protected_food": levy["protected"]["food"],
                         "standing_food_tax": levy["standing_levy"]["food"],
                         "extra_food_tax": levy["extra_levy"]["food"],
                         "food_after_tax": levy["private_close"]["food"],
                         "private_food_before_meal": nodes[i]["closing"]["food"],
                         "meal": record["regions"][i]["consumption"],
                         "depot_spoiled_food": depots[i]["spoil_food"],
                         "depot_closing_food": depots[i]["closing"]["food"]})
    return {"decision": gov["accounts"][owner]["decision"]["action"], "regions": rows,
            "food_shipments_to_target": [s for s in record["domestic"]["shipments"]
                                        if s["good"] == "food" and s["target"] == target],
            "roads": [e for e in gov["roads"] if e["owner"] == owner]}


def study():
    changed, counts = [], Counter()
    best, best_delta = None, 0
    for seed in range(20):
        opening_sha, records = _pair(seed)
        for a, b in zip(records[0]["regions"], records[1]["regions"], strict=True):
            baseline, policy = (r["consumption"]["food_unmet"] for r in (a, b))
            delta = policy - baseline
            counts["increased" if delta > 0 else "decreased" if delta < 0 else "unchanged"] += 1
            if delta:
                row = {"seed":seed, "owner":a["owner"], "region":a["id"], "none":baseline,
                       "integrated":policy, "difference":delta}
                changed.append(row)
                if delta > best_delta:
                    best_delta = delta
                    best = {**row, "initial_fiscal_sha256": opening_sha,
                            "arms": {rec["government"]["mode"]: _details(rec, a["owner"], a["id"])
                                     for rec in records}}
    return {"year": 1, "seed_range_inclusive": [0, 19], "world_pairs": 20,
            "region_pairs": counts.total(), "increased": counts["increased"],
            "unchanged": counts["unchanged"], "decreased": counts["decreased"],
            "changed_regions": changed, "largest_increase": best}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="write UTF-8 JSON to this file")
    args = parser.parse_args()
    if args.out:
        from tempfile import TemporaryDirectory
        from .publication import publish_file
        if args.out.exists():
            parser.exit(1, f"output already exists: {args.out}\n")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=args.out.parent) as tmp:
            staged = Path(tmp, "case.json")
            staged.write_bytes((json.dumps(study(), indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
            publish_file(staged, args.out)
    else:
        print(json.dumps(study(), indent=2, ensure_ascii=False))
