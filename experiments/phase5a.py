"""Matched, separately published development and holdout public-finance experiments."""
import argparse
import csv
import hashlib
import json
import os
import platform
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path
from statistics import fmean
from tempfile import TemporaryDirectory

from civsim.model import GOODS, generate_world
from civsim.regions import regionalize
from civsim.storage import canonical_line


MODES = ("none", "relief", "infrastructure", "integrated")
ACTIONS = ("defer", "reserve", "relief", "road", "soil")
FISCAL = (
    "levied_food", "levied_ore", "levied_tools", "relief_food", "public_freight_food",
    "road_build_units", "road_maintained_units", "road_lost_units", "works_ore", "works_tools",
    "public_labor", "soil_packages", "public_spoil_food", "collection_cost_food", "base_capacity",
    "effective_capacity", "next_capacity", "public_cargo", "action_executed",
)
PAIRED = ("final_population", "food_need", "food_deficit", "deficit_share", "shortage_region_years",
          "regional_ration_disparity", "within_country_ration_disparity", "food_output", "final_soil",
          "civil_freight_food", "border_freight_food", "public_freight_food", "total_freight_food",
          "civil_road_load", "public_cargo", "final_effective_capacity", "final_cash_hhi")
ARCHIVE = Path(__file__).resolve().parents[1] / "examples" / "phase4" / "study" / "runs.csv"


def disparity(rations):
    """Per-place absolute distance to the annual fulfilled share, measured in rations."""
    nation_need, nation_eaten = Counter(), Counter()
    for owner, need, eaten in rations.values():
        nation_need[owner] += need
        nation_eaten[owner] += eaten
    world_need, world_eaten = sum(nation_need.values()), sum(nation_eaten.values())
    world, within = {}, {}
    for region, (owner, need, eaten) in rations.items():
        world[region] = abs(eaten * world_need - need * world_eaten) / max(1, world_need)
        within[region] = abs(eaten * nation_need[owner] - need * nation_eaten[owner]) / max(1, nation_need[owner])
    return world, within


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else 0.0


def _sha(record):
    return hashlib.sha256(canonical_line(record)).hexdigest()


def _rates(row):
    need = row["food_need"]
    return {"deficit_share": _ratio(row["food_deficit"], need),
            "regional_ration_disparity": _ratio(row["absolute_world_ration_gap"], need),
            "within_country_ration_disparity": _ratio(row["absolute_national_ration_gap"], need)}


def _take_case(record, reg, reference, diff, kind, seed, mode):
    govt = record["government"]
    region, owner = reg["id"], reg["owner"]
    decision = next(a["decision"] for a in govt["accounts"] if a["id"] == owner)
    depot = next(a for a in govt["depots"] if a["region"] == region)
    levy = next(a for a in govt["levies"] if a["region"] == region)
    delivery = next(a for a in govt["relief"]["nodes"] if a["id"] == region)
    selection = next(c for c in decision["candidates"] if c["action"] == decision["action"]
                     and c["target_region"] == decision["target_region"] and c["target_edge"] == decision["target_edge"])
    shipments = [s for s in govt["relief"]["shipments"] if region in (s["source"], s["target"])]
    return {
        "seed": seed, "mode": mode, "year": record["year"], "owner": owner, "region": region,
        "kind": kind, "delta_unmet": diff,
        "none": dict(zip(("food_need", "food_unmet", "harvest", "population_close"), reference, strict=True)),
        "policy": {"food_need": reg["consumption"]["food_need"], "food_unmet": reg["consumption"]["food_unmet"],
                   "harvest": reg["production"]["produced"]["food"], "population_close": reg["closing"]["population"]},
        "decision": {k: decision[k] for k in ("action", "quantity", "target_region", "target_edge", "budget",
                                              "selected_score")},
        "selected_candidate": selection,
        "depot": depot, "levied": levy["levied"], "post_trade_private_food": levy["private_open"]["food"],
        "before_relief_food": delivery["private_food_open"], "after_relief_food": delivery["private_food_close"],
        "relief_shipments": shipments,
        "local_works": [p for p in govt["works"]["projects"] if p["source"] == region or p["target"] == region],
    }


def _seed(job):
    # A whole matched seed is one worker job. Its control observations never leave that process.
    from civsim.government import fiscal_snapshot, start_government, step_government
    seed, horizons = job
    runs, countries, regions, cases = [], [], [], []
    reference = {}
    for mode in MODES:
        world = regionalize(generate_world(seed))
        initial_region = _sha(asdict(world))
        sim = start_government(world)
        initial_fiscal = _sha(fiscal_snapshot(sim))
        init_pop = sum(n.population for n in world.nations)
        init_cash = sum(n.cash for n in world.nations)
        digest, projection = hashlib.sha256(), hashlib.sha256()
        local, fiscal = defaultdict(Counter), defaultdict(Counter)
        endpoint_capacity, best, evidence = {}, {}, {}
        for year in range(1, max(horizons) + 1):
            record = step_government(sim, year, mode)
            gov = record["government"]
            digest.update(canonical_line(record))
            if mode == "none":
                projection.update(canonical_line({k: v for k, v in record.items() if k != "government"}))
            rations = {r["id"]: (r["owner"], r["consumption"]["food_need"], r["consumption"]["food_eaten"])
                       for r in record["regions"]}
            world_gap, national_gap = disparity(rations)
            for r in record["regions"]:
                region, m, p = r["id"], r["consumption"], r["production"]
                short = m["food_unmet"]
                local[region].update({"food_need": m["food_need"], "food_eaten": m["food_eaten"],
                    "food_deficit": short, "shortage_region_years": int(short > 0),
                    "absolute_world_ration_gap": world_gap[region], "absolute_national_ration_gap": national_gap[region],
                    "births": r["demography"]["births"], "deaths": r["demography"]["deaths"],
                    **{f"{g}_output": p["produced"][g] for g in GOODS}})
                if mode == "none":
                    reference[year, region] = (m["food_need"], short, p["produced"]["food"], r["closing"]["population"])
                else:
                    base = reference[year, region]
                    diff = short - base[1]
                    kind = "higher_unmet" if diff > 0 else "lower_unmet"
                    if abs(diff) > best.get(kind, 0):
                        best[kind] = abs(diff)
                        evidence[kind] = _take_case(record, r, base, diff, kind, seed, mode)
            for a in gov["accounts"]:
                owner, t, decision = a["id"], a["totals"], a["decision"]
                f = fiscal[owner]
                f.update({k: t[k] for k in FISCAL})
                f["admin_units_assigned"] += decision["admin_units"]
                for action in ACTIONS:
                    chosen = action == decision["action"]
                    f[f"plans_{action}"] += int(chosen)
                    f[f"executions_{action}"] += t["action_executed"] if chosen else 0
                endpoint_capacity[owner] = t["effective_capacity"]
            for levy in gov["levies"]:
                i = levy["region"]
                local[i].update({"levied_" + g: levy["levied"][g] for g in GOODS})
                local[i].update({"standing_levy_" + g: levy["standing_levy"][g] for g in GOODS})
                local[i].update({"extra_levy_" + g: levy["extra_levy"][g] for g in GOODS})
            for node in gov["relief"]["nodes"]:
                local[node["id"]]["relief_received_food"] += node["private_food_close"] - node["private_food_open"]
            for road in gov["roads"]:
                owner = road["owner"]
                combined = road["private_use"] + road["works_use"] + road["relief_use"]
                fiscal[owner]["total_road_load"] += combined
                fiscal[owner]["saturated_road_years"] += int(road["capacity"] > 0 and combined == road["capacity"])
            if mode != "none":
                by_id = {r["id"]: r for r in record["regions"]}
                for s in gov["relief"]["shipments"]:
                    if s["source"] != s["target"] and "first_remote_relief" not in evidence:
                        target = s["target"]
                        ref = reference[year, target]
                        delta = by_id[target]["consumption"]["food_unmet"] - ref[1]
                        evidence["first_remote_relief"] = _take_case(
                            record, by_id[target], ref, delta, "first_remote_relief", seed, mode)
                for project in gov["works"]["projects"]:
                    action = project["action"]
                    kind = "first_" + action
                    if action in ("soil", "build") and kind not in evidence:
                        target = project["target"]
                        ref = reference[year, target]
                        delta = by_id[target]["consumption"]["food_unmet"] - ref[1]
                        evidence[kind] = _take_case(record, by_id[target], ref, delta, kind, seed, mode)
            for node in record["domestic"]["nodes"]:
                fiscal[node["owner"]]["civil_freight_food"] += node["cost_food"]
            for e in record["domestic"]["roads"]:
                fiscal[rations[e["a"]][0]]["civil_road_load"] += e["used"]
            for owner in fiscal:
                fiscal[owner].setdefault("border_freight_food", 0)
                fiscal[owner].setdefault("border_trade_value", 0)
            for t in record["border_market"]["trades"]:
                owner = rations[t["seller"]][0]
                fiscal[owner]["border_freight_food"] += t["cost_food"]
                fiscal[owner]["border_trade_value"] += t["value"]
            if year not in horizons:
                continue
            key = {"seed": seed, "mode": mode, "year": year}
            region_by_owner = defaultdict(Counter)
            aggregate = Counter()
            for r in record["regions"]:
                i, owner, close = r["id"], r["owner"], r["closing"]
                state = {"final_population": close["population"], "final_cash": close["cash"],
                         "final_deposit": close["deposit"], "farmland": close["farmland"],
                         "soil_times_farmland": close["soil"] * close["farmland"]}
                c = {**local[i], **state}
                region_by_owner[owner].update(c)
                regions.append({**key, "region": i, "owner": owner, **c, "soil": close["soil"], **_rates(c)})
            for a in gov["accounts"]:
                owner = a["id"]
                c = {**region_by_owner[owner], **fiscal[owner], "final_effective_capacity": endpoint_capacity[owner],
                     "total_freight_food": sum(fiscal[owner][k] for k in (
                         "civil_freight_food", "border_freight_food", "public_freight_food")),
                     **{f"public_reserve_{g}": a["public_close"][g] for g in GOODS},
                     **{f"private_stock_{g}": a["private_close"][g] for g in GOODS}}
                food_out = sum(c[k] for k in ("relief_food", "public_freight_food", "public_spoil_food",
                                              "collection_cost_food"))
                if (c["public_reserve_food"] != c["levied_food"] - food_out
                        or any(c["public_reserve_" + g] != c["levied_" + g] - c["works_" + g]
                               for g in ("ore", "tools"))
                        or c["relief_received_food"] != c["relief_food"]
                        or c["civil_road_load"] + c["public_cargo"] != c["total_road_load"]
                        or c["total_road_load"] > c["effective_capacity"]):
                    raise ValueError("country public balances or occupied road capacity differ from postings")
                countries.append({**key, "owner": owner, **c, "final_soil": _ratio(c["soil_times_farmland"], c["farmland"]),
                                  **_rates(c)})
                aggregate.update(c)
            if (aggregate["food_need"] - aggregate["food_eaten"] != aggregate["food_deficit"]
                    or aggregate["final_cash"] != init_cash
                    or init_pop + aggregate["births"] - aggregate["deaths"] != aggregate["final_population"]):
                raise ValueError("world rations, cash, or demographic identities failed")
            latest = record["countries"]
            runs.append({**key, "initial_regional_sha256": initial_region, "initial_fiscal_sha256": initial_fiscal,
                         "years_sha256": digest.hexdigest(),
                         "control_regional_sha256": projection.hexdigest() if mode == "none" else "",
                         "initial_population": init_pop, "initial_cash": init_cash, **aggregate, **_rates(aggregate),
                         "final_cash_hhi": _ratio(sum(n["closing"]["cash"]**2 for n in latest), init_cash**2),
                         "final_soil": _ratio(aggregate["soil_times_farmland"], aggregate["farmland"])})
        cases.extend(evidence.values())
    return runs, countries, regions, cases


def _read(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _write(path, rows):
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _archive_checks(runs):
    saved = {(int(r["seed"]), int(r["year"])): r for r in _read(ARCHIVE) if r["arm"] == "limited"}
    matches = 0
    for r in runs:
        if r["mode"] != "none" or r["year"] not in (50, 200):
            continue
        reference = saved.get((r["seed"], r["year"]))
        if (reference is None or r["control_regional_sha256"] != reference["years_sha256"]
                or r["initial_regional_sha256"] != reference["initial_regional_sha256"]):
            raise ValueError(f"4.0 archive mismatch at seed {r['seed']}, year {r['year']}")
        matches += 1
    return matches


def _verify_trace(runs, reference):
    previous = _read(Path(reference) / "runs.csv")
    fields = ("seed", "mode", "year", "initial_regional_sha256", "initial_fiscal_sha256", "years_sha256",
              "control_regional_sha256")
    def fingerprint(records):
        return sorted(tuple(str(row[f]) for f in fields) for row in records)
    if fingerprint(previous) != fingerprint(runs):
        raise ValueError("independent checkpoint replay mismatch")
    return len(runs)


def run_study(output, *, sample, seeds=20, horizons=(50, 100, 200), workers=8, verify=None):
    output = Path(output)
    if os.path.lexists(output):
        raise FileExistsError(output)
    horizons = tuple(horizons)
    if (sample not in ("dev", "holdout") or type(seeds) is not int or not 1 <= seeds <= 20
            or type(workers) is not int or workers < 1 or not horizons or len(set(horizons)) != len(horizons)
            or any(type(h) is not int or h < 1 for h in horizons)):
        raise ValueError("expected dev or holdout, 1..20 seeds and distinct positive horizons")
    start_seed = 0 if sample == "dev" else 20
    jobs = [(seed, horizons) for seed in range(start_seed, start_seed + seeds)]
    start = time.perf_counter()
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent, prefix=".fiscal-study-") as scratch:
        stage = Path(scratch) / "results"
        stage.mkdir()
        if workers == 1:
            results = [_seed(j) for j in jobs]
        else:
            with ProcessPoolExecutor(max_workers=min(workers, seeds)) as pool:
                results = list(pool.map(_seed, jobs))
        runs, countries, regions, cases = [[r for data in results for r in data[i]] for i in range(4)]
        indexed = {(r["seed"], r["mode"], r["year"]): r for r in runs}
        paired = []
        for r in runs:
            ref = indexed[r["seed"], "none", r["year"]]
            if any(r[k] != ref[k] for k in ("initial_regional_sha256", "initial_fiscal_sha256")):
                raise ValueError("initial public or private endowment differs across arms")
            if r["mode"] != "none":
                paired.append({"seed": r["seed"], "mode": r["mode"], "year": r["year"],
                               **{f"delta_{k}": r[k] - ref[k] for k in PAIRED}})
        means = []
        for mode in MODES:
            for year in horizons:
                g = [r for r in runs if r["mode"] == mode and r["year"] == year]
                means.append({"mode": mode, "year": year, "seeds": len(g),
                              **{k: fmean(row[k] for row in g) for k, v in g[0].items()
                                 if k not in ("seed", "year") and isinstance(v, (int, float))},
                              **{"pooled_" + k: v for k, v in _rates({
                                  k: sum(row[k] for row in g) for k in (
                                      "food_deficit", "food_need", "absolute_world_ration_gap",
                                      "absolute_national_ration_gap")}).items()}})
        archive_count = _archive_checks(runs) if sample == "dev" else 0
        replay_count = _verify_trace(runs, verify) if verify is not None else 0
        for name, data in (("runs", runs), ("countries", countries), ("regions", regions), ("paired", paired),
                           ("means", means)):
            _write(stage / (name + ".csv"), data)
        (stage / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8", newline="\n")
        tables = sorted(p.name for p in stage.iterdir())
        if verify is not None:
            for name in tables:
                if (stage / name).read_bytes() != (Path(verify) / name).read_bytes():
                    raise ValueError(f"independent experiment table differs: {name}")
        summary = {"sample": sample, "seed_start": start_seed, "seeds": seeds, "horizons": horizons,
                   "modes": MODES, "workers": min(seeds, workers), "paths": len(jobs) * len(MODES),
                   "transitions": len(jobs) * len(MODES) * max(horizons), "replayed_checkpoints": replay_count,
                   "archived_control_checkpoints": archive_count, "replayed_tables": tables if verify is not None else [],
                   "python": platform.python_version(),
                   "wall_seconds": time.perf_counter() - start}
        (stage / "execution.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
        if os.path.lexists(output):
            raise FileExistsError(output)
        stage.rename(output)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--sample", required=True, choices=("dev", "holdout"))
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--horizons", default="50,100,200")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--verify-against", type=Path)
    args = parser.parse_args()
    try:
        summary = run_study(args.out, sample=args.sample, seeds=args.seeds, workers=args.workers,
                            horizons=tuple(int(h) for h in args.horizons.split(",")), verify=args.verify_against)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{parser.prog}: {error}\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
