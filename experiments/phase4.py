"""Four matched regional policies, two checkpoint horizons, and same-opening freight tests."""

import argparse
import csv
import hashlib
import json
import os
import platform
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path
from statistics import fmean
from tempfile import TemporaryDirectory

from civsim.investment import ASSETS
from civsim.logistics import ship
from civsim.model import GOODS, generate_world
from civsim.regional_engine import RegionalPolicy, step_regional
from civsim.regions import regionalize
from civsim.storage import canonical_line


POLICIES = {"limited": RegionalPolicy(), "unlimited": RegionalPolicy(logistics="unlimited"),
            "limited-national": RegionalPolicy(investment_scope="national"),
            "limited-no-care": RegionalPolicy(soil_care=False)}
DELTAS = ("final_population", "food_deficit", "deficit_share", "food_output", "ore_output",
          "tools_output", "domestic_cost_food", "border_cost_food", "cargo_tile_steps",
          "final_soil", "final_deposit", "final_cash_hhi")
DIAGNOSTICS = ("frozen_limited_unmet", "frozen_unlimited_unmet", "region_years_cap_worse",
               "region_years_cap_better", "region_years_cap_equal")


def _evidence(world, record, focal, kind):
    """Recreate the two freight stages on one identical post-border opening only."""
    constrained = record["domestic"]
    original = {r["id"]: r for r in constrained["nodes"]}
    clones = [replace(r, population=original[r.id]["population"], stock=original[r.id]["opening"].copy())
              for r in world.regions]
    alternate = ship(clones, world.roads, "unlimited", width=world.width)
    region_id = focal["region"]
    owner = original[region_id]["owner"]
    def view(ledger):
        local = [n for n in ledger["nodes"] if n["owner"] == owner]
        return {
            "nodes": [{"id": n["id"], "population": n["population"], "food_open": n["opening"]["food"],
                       "food_close": n["closing"]["food"], "unmet": n["unmet_after"]["food"],
                       "cost_food": n["cost_food"]} for n in local],
            "food_shipments": [t for t in ledger["shipments"]
                               if t["good"] == "food" and original[t["source"]]["owner"] == owner],
            "roads": [e for e in ledger["roads"] if original[e["a"]]["owner"] == owner],
        }
    measured = next(n for n in alternate["nodes"] if n["id"] == region_id)["unmet_after"]["food"]
    if measured != focal["other_unmet"]:
        raise ValueError("same-opening case disagrees with capacity diagnostic")
    return {"seed": world.seed, "year": record["year"], "owner": owner, "kind": kind, **focal,
            "limited": view(constrained), "unlimited": view(alternate)}


def _run(seed, arm, horizons):
    original = generate_world(seed)
    native = hashlib.sha256(canonical_line(asdict(original))).hexdigest()
    world = regionalize(original)
    initial = hashlib.sha256(canonical_line(asdict(world))).hexdigest()
    digest = hashlib.sha256()
    population = sum(r.population for r in world.regions)
    deposit = sum(r.deposit for r in world.regions)
    cash = sum(r.cash for r in world.regions)
    regions = {r.id: Counter() for r in world.regions}
    roads = {(e.a, e.b): Counter() for e in world.roads}
    totals = Counter()
    diag = Counter()
    examples = {}
    runs, regional, edges = [], [], []
    for year in range(1, max(horizons) + 1):
        record = step_regional(world, year, POLICIES[arm], diagnose_capacity=arm == "limited")
        diagnostic = record.pop("capacity_diagnostic", ())
        digest.update(canonical_line(record))
        for t in diagnostic:
            limited, unlimited = t["actual_unmet"], t["other_unmet"]
            diag["frozen_limited_unmet"] += limited
            diag["frozen_unlimited_unmet"] += unlimited
            kind = "worse" if limited > unlimited else "better" if limited < unlimited else "equal"
            diag[f"region_years_cap_{kind}"] += 1
            if kind != "equal" and kind not in examples:
                examples[kind] = _evidence(world, record, t, kind)
        for c in record["regions"]:
            entry = regions[c["id"]]
            p, m, d = c["production"], c["consumption"], c["demography"]
            care, inv = p["soil_care"], p["investment"]
            increments = {
                "food_need": m["food_need"], "food_eaten": m["food_eaten"], "food_deficit": m["food_unmet"],
                "shortage_region_years": int(m["food_unmet"] > 0), "births": d["births"], "deaths": d["deaths"],
                "food_spoiled": m["food_spoiled"], "care_packages": care["packages"], "care_labor": care["workers"],
                "care_ore": care["used"]["ore"], "care_tools": care["used"]["tools"],
                "care_tile_years": care["treated_tiles"], "care_recovery": care["recovery"],
                "build_labor": inv["construction_labor"], "build_tools": inv["build_used"]["tools"],
                "build_ore": inv["build_used"]["ore"], "upkeep_tools": inv["upkeep_used"]["tools"],
                "upkeep_ore": inv["upkeep_used"]["ore"], "asset_gross_gain": inv["gross_gain_value"],
                **{f"{g}_output": p["produced"][g] for g in GOODS},
                **{f"built_{k}": inv["built"][k] for k in ASSETS},
                **{f"operated_{k}": inv["operated"][k] for k in ASSETS},
            }
            entry.update(increments)
            totals.update(increments)
        freight = record["domestic"]
        for t in freight["nodes"]:
            regions[t["id"]]["freight_cost_food"] += t["cost_food"]
            for g in GOODS:
                regions[t["id"]][f"domestic_in_{g}"] += t["imports"][g]
                regions[t["id"]][f"domestic_out_{g}"] += t["exports"][g]
        for e in freight["roads"]:
            k = roads[e["a"], e["b"]]
            k["used"] += e["used"]
            k["cost_food"] += e["cost_food"]
            k["saturated_years"] += int(e["capacity"] > 0 and e["used"] >= e["capacity"])
            totals["road_load"] += e["used"]
            totals["nominal_road_capacity"] += e["capacity"]
            totals["saturated_edge_years"] += int(e["capacity"] > 0 and e["used"] >= e["capacity"])
            totals["cargo_tile_steps"] += e["used"] * e["distance"]
        totals["domestic_cost_food"] += freight["cost_food"]
        totals["shipment_distance"] += sum(s["distance"] for s in freight["shipments"])
        totals["domestic_shipments"] += len(freight["shipments"])
        for g in GOODS:
            totals[f"domestic_{g}"] += freight["delivered"][g]
        for t in record["border_market"]["trades"]:
            totals[f"border_{t['good']}"] += t["quantity"]
            totals["border_cost_food"] += t["cost_food"]
            totals["border_value"] += t["value"]
        if year not in horizons:
            continue
        if arm == "limited" and diag["frozen_limited_unmet"] != totals["food_deficit"]:
            raise ValueError("frozen opening food shortfall differs from realized shortage")
        final_deposit = sum(r.deposit for r in world.regions)
        final_population = sum(r.population for r in world.regions)
        if (deposit - final_deposit != totals["ore_output"] or sum(r.cash for r in world.regions) != cash
                or population + totals["births"] - totals["deaths"] != final_population
                or totals["food_deficit"] != totals["food_need"] - totals["food_eaten"]):
            raise ValueError("world stock, cash, demographic, or ration balance mismatch")
        key = {"seed": seed, "arm": arm, "year": year}
        for k in ("border_cost_food", "border_value", *(f"border_{g}" for g in GOODS)):
            totals.setdefault(k, 0)
        runs.append({
            **key, "initial_national_sha256": native, "initial_regional_sha256": initial,
            "years_sha256": digest.hexdigest(), "initial_population": population, "final_population": final_population,
            **totals, "deficit_share": totals["food_deficit"] / totals["food_need"],
            "final_soil": sum(r.soil*r.farmland for r in world.regions) / max(1,sum(r.farmland for r in world.regions)),
            "initial_deposit": deposit, "final_deposit": final_deposit, "final_cash": cash,
            "final_cash_hhi": sum(n.cash*n.cash for n in world.nations) / (cash*cash),
            **{g+"_stock": sum(r.stock[g] for r in world.regions) for g in GOODS},
            **{k: diag[k] if arm == "limited" else None for k in DIAGNOSTICS},
        })
        for r in world.regions:
            regional.append({**key, "region": r.id, "owner": r.owner, "land": r.land, "farmland": r.farmland,
                             "population": r.population, "cash": r.cash, "soil": r.soil, "deposit": r.deposit,
                             **{g+"_stock": r.stock[g] for g in GOODS}, **regions[r.id]})
        for e in world.roads:
            edges.append({**key, "a": e.a, "b": e.b, "distance": e.distance, "annual_capacity": e.capacity,
                          **roads[e.a,e.b]})
    return runs, regional, edges, list(examples.values())


def _job(job):
    return _run(*job)


def run_study(output, *, seeds=20, horizons=(50, 200), workers=6):
    output = Path(output)
    horizons = tuple(horizons)
    if os.path.lexists(output):
        raise FileExistsError(output)
    if (any(type(v) is not int or v < 1 for v in (seeds, workers, *horizons)) or not horizons
            or len(set(horizons)) != len(horizons)):
        raise ValueError("positive seeds/workers and distinct positive horizons required")
    jobs = [(seed, arm, horizons) for seed in range(seeds) for arm in POLICIES]
    output.parent.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    with TemporaryDirectory(dir=output.parent, prefix=".regional-study-") as scratch:
        stage = Path(scratch) / "study"
        stage.mkdir()
        if workers == 1:
            results = [_job(job) for job in jobs]
        else:
            with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as pool:
                results = list(pool.map(_job, jobs))
        runs, regions, roads, cases = [[row for result in results for row in result[i]] for i in range(4)]
        lookup = {(r["seed"],r["arm"],r["year"]): r for r in runs}
        paired = []
        for r in runs:
            ref = lookup[r["seed"],"limited",r["year"]]
            if r["initial_regional_sha256"] != ref["initial_regional_sha256"]:
                raise ValueError("different regional opening for matched arms")
            if r["arm"] != "limited":
                paired.append({"seed": r["seed"],"arm":r["arm"],"year":r["year"],
                               **{f"delta_{k}":r[k]-ref[k] for k in DELTAS}})
        means = []
        for arm in POLICIES:
            for year in horizons:
                group = [r for r in runs if r["arm"] == arm and r["year"] == year]
                avg = {"arm":arm, "year":year, "seeds":len(group)}
                for k,v in group[0].items():
                    if k in ("seed","arm","year") or isinstance(v,str):
                        continue
                    avg[k] = None if v is None else fmean(r[k] for r in group)
                avg["pooled_deficit_share"] = sum(r["food_deficit"] for r in group) / sum(r["food_need"] for r in group)
                means.append(avg)
        for name, data in (("runs", runs), ("regions", regions), ("roads", roads), ("paired", paired), ("means", means)):
            with (stage / f"{name}.csv").open("x", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=tuple(data[0]))
                writer.writeheader()
                writer.writerows(data)
        (stage / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        meta = {"seed_start":0, "seeds":seeds, "horizons":horizons, "workers":workers,
                "policies":{k:asdict(v) for k,v in POLICIES.items()}, "python":platform.python_version(),
                "wall_seconds":time.perf_counter()-start, "runs":len(jobs), "annual_transitions":len(jobs)*max(horizons)}
        (stage/"execution.json").write_text(json.dumps(meta,indent=2)+"\n", encoding="utf-8")
        if os.path.lexists(output):
            raise FileExistsError(output)
        stage.rename(output)
    return meta


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--horizons", default="50,200")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    try:
        result = run_study(args.out, seeds=args.seeds, horizons=tuple(int(v) for v in args.horizons.split(",")),
                           workers=args.workers)
    except (OSError,ValueError) as error:
        parser.exit(1, f"{parser.prog}: {error}\n")
    print(f"{result['runs']} paths; {result['annual_transitions']} annual transitions; {result['wall_seconds']:.3f} s")


if __name__ == "__main__":
    main()
