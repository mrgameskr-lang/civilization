"""Paired investment-policy experiment, including all one-factor contrasts."""

import argparse
import csv
import hashlib
import json
import os
import platform
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from itertools import product
from pathlib import Path
from statistics import fmean
from tempfile import TemporaryDirectory

from civsim.economy import BASE_PRICES
from civsim.engine import step
from civsim.investment import ASSETS, WORKER_VALUE
from civsim.investment31 import class_accounts
from civsim.model import GOODS, generate_world
from civsim.rules import Rules
from civsim.storage import canonical_line
from experiments.phase3 import Metrics


# Bit order: diminishing returns, scale-sensitive policy, multiple selections.
ARMS = {"control": (0, 0, 0), "fixed-multi": (0, 0, 1),
        "diminishing-single": (1, 0, 0), "diminishing-multi": (1, 0, 1),
        "scaled-single": (0, 1, 0), "scaled-multi": (0, 1, 1),
        "combined-single": (1, 1, 0), "combined-multi": (1, 1, 1)}
FACTORS = ("diminishing", "scaled", "multi")
COMPARISONS = ("final_population", "food_deficit", "deficit_share", "final_hhi",
               "food_output", "ore_output", "tools_output", "final_soil", "final_deposit",
               "shortage_country_years", "final_top1_share", "depleted_nations", "built", "cost_value",
               "gross_gain_value", "local_net_value")


def _rules(arm):
    if arm == "control":
        return Rules("reallocate", investment="capital")
    return Rules("reallocate", investment="capital", policy31=arm)


def _value(quantities):
    return sum(quantities[g] * BASE_PRICES[g] for g in GOODS)


def _percentile(hist, percent):
    rank = (sum(hist.values()) * percent + 99) // 100
    cumulative = 0
    for value, count in sorted(hist.items()):
        cumulative += count
        if cumulative >= rank:
            return value
    return None


def summarize_run(world, arm, horizons):
    """Keep annual ledgers only long enough to verify, hash and aggregate each year."""
    seed = world.seed
    rules = _rules(arm)
    initial_sha = hashlib.sha256(canonical_line(asdict(world))).hexdigest()
    metrics = Metrics(world)
    total_land = sum(n.land for n in world.nations)
    initial_soil = sum(n.soil * n.land for n in world.nations) / total_land
    accounts = {a: Counter() for a in ASSETS}
    prospects = {a: Counter() for a in ASSETS}
    multi_years = 0
    runs, assets = [], []
    for y in range(1, max(horizons) + 1):
        record = step(world, y, rules)
        metrics.observe(record)
        for country in record["countries"]:
            plan = country["production"]["investment"]
            multi_years += int(sum(plan["built"].values()) > 1)
            postings = class_accounts(country, rules)
            for a, account in accounts.items():
                entry = postings[a]
                for g in GOODS:
                    account[f"build_{g}"] += entry["build_used"][g]
                    account[f"upkeep_{g}"] += entry["upkeep_used"][g]
                account["construction_labor"] += entry["construction_labor"]
                account["marginal_gain_value"] += entry["marginal_gain_value"]
                candidate = plan["candidates"][a]
                prospects[a][candidate["net_value"]] += 1
                account["eligible_unbuilt"] += int(not candidate["constraints"] and not plan["built"][a])
        if y not in horizons:
            continue
        flow = metrics.flow
        key = {"seed": seed, "arm": arm, "horizon": y}
        total_built = sum(m["built"] for m in metrics.assets.values())
        by_type = []
        for a in ASSETS:
            counts, acct, hist = metrics.assets[a], accounts[a], prospects[a]
            build = {g: acct[f"build_{g}"] for g in GOODS}
            upkeep = {g: acct[f"upkeep_{g}"] for g in GOODS}
            cost = _value(build) + _value(upkeep) + WORKER_VALUE * acct["construction_labor"]
            available, operated = counts["available"], counts["operated"]
            by_type.append({
                **key, "asset": a, **counts, **acct, "cost_value": cost,
                "build_value": _value(build), "upkeep_value": _value(upkeep),
                "marginal_net_value": acct["marginal_gain_value"] - cost,
                "marginal_net_roi": (acct["marginal_gain_value"] - cost) / cost if cost else None,
                "utilization": operated / available if available else None,
                "built_share": counts["built"] / total_built if total_built else None,
                "prospects": sum(hist.values()), "prospect_min": min(hist), "prospect_max": max(hist),
                "prospect_p25": _percentile(hist, 25), "prospect_p50": _percentile(hist, 50),
                "prospect_p75": _percentile(hist, 75),
            })
        for field in ("construction_labor", *(f"{k}_{g}" for k in ("build", "upkeep") for g in GOODS)):
            if sum(a[field] for a in by_type) != flow[field]:
                raise ValueError(f"{key}: class postings do not reconcile for {field}")
        cash = sum(n.cash for n in world.nations)
        deposit = sum(n.deposit for n in world.nations)
        if cash != metrics.initial_cash or metrics.initial_deposit - deposit != flow["ore_output"]:
            raise ValueError(f"{key}: world balances differ")
        if flow["food_deficit"] != flow["food_need"] - flow["food_eaten"]:
            raise ValueError(f"{key}: unmet need differs from ration consumption")
        cost = sum(a["cost_value"] for a in by_type)
        runs.append({
            **key, "model_version": rules.version, "initial_sha256": initial_sha,
            "years_sha256": metrics.digest.hexdigest(), "initial_population": metrics.initial_population,
            "final_population": sum(n.population for n in world.nations), **flow,
            "deficit_share": flow["food_deficit"] / flow["food_need"],
            "initial_cash": metrics.initial_cash, "final_cash": cash,
            "initial_soil": initial_soil, "final_soil": sum(n.soil * n.land for n in world.nations) / total_land,
            "minimum_soil": min(n.soil for n in world.nations),
            "final_hhi": sum(n.cash**2 for n in world.nations) / cash**2,
            "final_top1_share": max(n.cash for n in world.nations) / cash,
            "initial_deposit": metrics.initial_deposit, "final_deposit": deposit,
            "depleted_nations": sum(n.deposit == 0 for n in world.nations),
            "final_tools_stock": sum(n.stock["tools"] for n in world.nations),
            "multi_country_years": multi_years, "built": total_built,
            "available": sum(a["available"] for a in by_type), "operated": sum(a["operated"] for a in by_type),
            "cost_value": cost, "local_net_value": flow["gross_gain_value"] - cost,
            "local_net_roi": (flow["gross_gain_value"] - cost) / cost if cost else None,
            "marginal_interaction_gap": flow["gross_gain_value"] - sum(a["marginal_gain_value"] for a in by_type),
        })
        assets.extend(by_type)
    return runs, assets


def _seed(seed, horizons):
    records, assets = [], []
    for arm in ARMS:
        runs, types = summarize_run(generate_world(seed), arm, horizons)
        records.extend(runs)
        assets.extend(types)
    if len({r["initial_sha256"] for r in records}) != 1:
        raise ValueError(f"seed {seed}: initial worlds differ between arms")
    return records, assets


def contrasts(runs):
    """For each seed/horizon compare against 3.0 and along each edge of the 2×2×2 cube."""
    by_key = {(r["seed"], r["horizon"], r["arm"]): r for r in runs}
    policy = {v: k for k, v in ARMS.items()}
    paired, factors = [], []
    for (seed, horizon, arm), row in by_key.items():
        def contrast(baseline):
            other = by_key[seed, horizon, baseline]
            return {"seed": seed, "horizon": horizon, "control": baseline, "treatment": arm,
                    **{f"delta_{k}": row[k] - other[k] for k in COMPARISONS}}
        if arm != "control":
            paired.append(contrast("control"))
        for i, enabled in enumerate(ARMS[arm]):
            if enabled:
                bits = list(ARMS[arm])
                bits[i] = 0
                factors.append({"factor": FACTORS[i], **contrast(policy[tuple(bits)])})
    return paired, factors


def _model_hash():
    root = Path(__file__).resolve().parents[1] / "civsim"
    h = hashlib.sha256()
    for module in ("model", "rules", "engine", "economy", "investment", "investment31", "demography"):
        h.update(module.encode() + b"\0" + (root / f"{module}.py").read_bytes() + b"\0")
    return h.hexdigest()


def run_experiment(output, *, seed_start=0, seeds=20, horizons=(50, 100, 150, 200), workers=4, match_design=None):
    horizons = tuple(horizons)
    if (type(seed_start) is not int or type(seeds) is not int or seeds <= 0 or
            type(workers) is not int or workers <= 0 or not horizons or
            any(type(h) is not int or h <= 0 for h in horizons) or len(set(horizons)) != len(horizons)):
        raise ValueError("invalid seed count, worker count, or horizons")
    output = Path(output)
    if os.path.lexists(output):
        raise FileExistsError(output)
    design = _model_hash()
    if match_design is not None:
        ref = json.loads((Path(match_design) / "execution.json").read_text(encoding="utf-8"))
        if ref["model_sha256"] != design or ref["horizons"] != list(horizons):
            raise ValueError("reference model or horizons differ")
        if set(ref["seeds"]).intersection(range(seed_start, seed_start + seeds)):
            raise ValueError("development and holdout seeds overlap")
    output.parent.mkdir(exist_ok=True, parents=True)
    started = time.perf_counter()
    seed_list = list(range(seed_start, seed_start + seeds))
    with TemporaryDirectory(dir=output.parent, prefix=".investment31-") as temp:
        staging = Path(temp) / "matrix"
        staging.mkdir()
        if workers == 1:
            data = [_seed(s, horizons) for s in seed_list]
        else:
            with ProcessPoolExecutor(max_workers=min(seeds, workers)) as pool:
                data = list(pool.map(_seed, seed_list, [horizons] * seeds))
        runs = [r for seed_runs, _ in data for r in seed_runs]
        assets = [r for _, seed_assets in data for r in seed_assets]
        pairs, factors = contrasts(runs)
        means = []
        for arm, horizon in product(ARMS, sorted(horizons)):
            group = [r for r in runs if r["arm"] == arm and r["horizon"] == horizon]
            measures = [k for k in group[0] if k not in
                        ("seed", "arm", "horizon", "model_version", "initial_sha256", "years_sha256", "local_net_roi")]
            cost = sum(r["cost_value"] for r in group)
            means.append({"arm": arm, "horizon": horizon, "seeds": len(group),
                          **{k: fmean(r[k] for r in group) for k in measures},
                          "pooled_deficit_share": sum(r["food_deficit"] for r in group) / sum(r["food_need"] for r in group),
                          "pooled_net_roi": sum(r["local_net_value"] for r in group) / cost if cost else None})
        for name, records in (("runs", runs), ("assets", assets), ("paired", pairs),
                              ("factors", factors), ("means", means)):
            with (staging / f"{name}.csv").open("x", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=tuple(records[0]))
                writer.writeheader()
                writer.writerows(records)
        if design != _model_hash():
            raise RuntimeError("model source changed during experiment")
        meta = {"seeds": seed_list, "horizons": list(horizons), "arms": list(ARMS),
                "primary_contrast": "combined-multi minus control", "workers": min(seeds, workers),
                "python": platform.python_version(), "platform": platform.platform(),
                "model_sha256": design, "duration_seconds": time.perf_counter() - started,
                "runs": seeds * len(ARMS), "annual_transitions": seeds * len(ARMS) * max(horizons)}
        (staging / "execution.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        if os.path.lexists(output):
            raise FileExistsError(output)
        staging.rename(output)
    return meta


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--seed-start", type=int, default=0)
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--horizons", default="50,100,150,200")
    parser.add_argument("--match-design", type=Path, help="prior run with the same design and separate seeds")
    args = parser.parse_args()
    try:
        meta = run_experiment(args.out, seed_start=args.seed_start, seeds=args.seeds, workers=args.workers,
                              horizons=tuple(int(v) for v in args.horizons.split(",")), match_design=args.match_design)
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(1, f"{parser.prog}: {error}\n")
    print(f"{meta['runs']} paths, {meta['annual_transitions']} annual transitions, {meta['duration_seconds']:.3f} s")


if __name__ == "__main__":
    main()
