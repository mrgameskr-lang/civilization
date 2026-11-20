"""Long-run 3.0 capital histories and paired post-year-50 interventions."""

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import platform
from collections import defaultdict
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from civsim.engine import step
from civsim.model import GOODS, generate_world
from civsim.rules import Rules
from civsim.storage import canonical_line


POLICY = Rules(labor="reallocate", investment="capital")
STABILITY_ARMS = ("baseline", "soil_floor", "deep_ore", "cash")
CHECKPOINTS = (50, 100, 150, 200, 300, 400, 500)
EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def apply_opening(world, arm, year, seam):
    """Change one boundary condition. Transfers use the pre-policy population."""
    if year < 51:
        return
    if arm == "deep_ore" and year == 51:
        for nation in world.nations:
            nation.deposit += seam[nation.id]
    if arm != "cash":
        return
    population = sum(n.population for n in world.nations)
    if not population:
        return
    paid = {n.id: n.cash // 5 for n in world.nations}
    pool = sum(paid.values())
    shares = {n.id: divmod(pool * n.population, population) for n in world.nations}
    extra = pool - sum(q for q, _ in shares.values())
    largest = sorted(shares, key=lambda i: (-shares[i][1], i))[:extra]
    for n in world.nations:
        n.cash += shares[n.id][0] + int(n.id in largest) - paid[n.id]


def regime_events(net_by_year):
    """A regime becomes observable after five consecutive years with the same sign class."""
    established = streak = None
    events = []
    length = 0
    for year, net in net_by_year:
        regime = "growth" if net > 0 else "non_growth"
        length = length + 1 if regime == streak else 1
        streak = regime
        if length == 5 and established != regime:
            events.append({"previous": established or "", "regime": regime, "start_year": year - 4,
                           "confirmed_year": year})
            established = regime
    return events


def _flows(record):
    values = {c["id"]: dict.fromkeys(
        [f"{good}_{side}" for good in GOODS for side in ("imports", "exports")]
        + ["imports_value", "exports_value"], 0) for c in record["countries"]}
    for t in record["market"]["trades"]:
        buyer, seller = values[t["buyer"]], values[t["seller"]]
        buyer[f"{t['good']}_imports"] += t["quantity"]
        seller[f"{t['good']}_exports"] += t["quantity"]
        buyer["imports_value"] += t["value"]
        seller["exports_value"] += t["value"]
    return values


def _ratio(num, den):
    return round(num / den, 8) if den else ""


def _rates(row):
    return {
        "shortfall_share": _ratio(row["food_deficit"], row["food_need"]),
        "farm_utilization": _ratio(row["farmers"], row["farm_capacity"]),
        "mine_utilization": _ratio(row["ore_mined"], row["mine_capacity"]),
        "asset_utilization": _ratio(row["assets_operated"], row["assets_open"]),
    }


def _collect(seed, arm, world, year, seam):
    pre = {n.id: (n.cash, n.deposit) for n in world.nations}
    apply_opening(world, arm, year, seam)
    record = step(world, year, POLICY)
    flows = _flows(record)
    rows = []
    for n, c in zip(world.nations, record["countries"]):
        o, end, p = c["opening"], c["closing"], c["production"]
        u, d, capital = c["consumption"], c["demography"], p["investment"]
        if arm == "soil_floor" and year >= 51:
            # The year's harvest and erosion are model outputs. Repair is posted
            # after the audited transition and affects only subsequent harvests.
            n.soil = max(n.soil, o["soil"])
        cash_before, deposit_before = pre[n.id]
        row = {"seed": seed, "arm": arm, "year": year, "nation_id": n.id, "name": n.name,
               "pop_open": o["population"], "pop_close": n.population,
               "births": d["births"], "deaths": d["deaths"], "immigrants": d["immigrants"],
               "emigrants": d["emigrants"], "net_migration": d["immigrants"] - d["emigrants"],
               "food_output": p["produced"]["food"], "food_need": u["food_need"],
               "food_eaten": u["food_eaten"], "food_deficit": u["food_unmet"],
               "food_stock": n.stock["food"], "food_spoiled": u["food_spoiled"],
               "soil_open": o["soil"], "soil_model_close": end["soil"], "soil_close": n.soil,
               "soil_restored": n.soil - end["soil"], "land": n.land, "climate": p["climate"],
               "farmers": p["active_farmers"], "farm_capacity": p["land_capacity"],
               "deposit_before_policy": deposit_before, "deposit_added": o["deposit"] - deposit_before,
               "ore_mined": p["produced"]["ore"], "mine_capacity": p["mining_capacity"], "deposit_close": n.deposit,
               "tools_made": p["produced"]["tools"], "tools_stock": n.stock["tools"],
               "assets_open": sum(sum(cohorts) for cohorts in o["capital"].values()),
               "assets_operated": sum(capital["operated"].values()),
               "cash_before_policy": cash_before, "cash_transfer": o["cash"] - cash_before,
               "cash_close": n.cash, **flows[n.id]}
        if n.deposit != deposit_before + row["deposit_added"] - row["ore_mined"]:
            raise ValueError("unexplained deposit change")
        if n.cash != cash_before + row["cash_transfer"] + row["exports_value"] - row["imports_value"]:
            raise ValueError("unexplained cash change")
        rows.append({**row, **_rates(row)})
    if sum(r["cash_transfer"] for r in rows) != 0:
        raise ValueError("redistribution changed global currency supply")
    return record, rows


def _world(rows):
    first = rows[0]
    totals = {key: sum(r[key] for r in rows) for key in first
              if key not in {"seed", "arm", "year", "nation_id", "name", "soil_open", "soil_close",
                             "soil_model_close", "climate", *tuple(_rates(first))}}
    for field in ("soil_open", "soil_close", "soil_model_close", "climate"):
        totals[field] = _ratio(sum(r[field] * r["land"] for r in rows), totals["land"])
    return {"seed": first["seed"], "arm": first["arm"], "year": first["year"], **totals,
            **_rates(totals), "top_cash_share": _ratio(max(r["cash_close"] for r in rows), totals["cash_close"]),
            "empty_deposits": sum(r["deposit_close"] == 0 for r in rows),
            "short_countries": sum(r["food_deficit"] > 0 for r in rows)}


def _writer(stack, directory, name):
    if name.endswith(".gz"):
        raw = stack.enter_context((directory / name).open("xb"))
        packed = stack.enter_context(gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6))
        stream = stack.enter_context(io.TextIOWrapper(packed, encoding="utf-8", newline=""))
    else:
        stream = stack.enter_context((directory / name).open("x", encoding="utf-8", newline=""))
    writer = None

    def write(row):
        nonlocal writer
        if writer is None:
            writer = csv.DictWriter(stream, fieldnames=tuple(row), lineterminator="\n")
            writer.writeheader()
        writer.writerow(row)

    return write


def _turns(seed, arm, history, save):
    for nation_id, series in history.items():
        events = regime_events((y, net) for y, net, _ in series)
        entity = {"seed": seed, "arm": arm, "nation_id": nation_id}
        for event in events:
            if arm == "baseline" or event["confirmed_year"] > 50:
                save["transitions.csv"]({**entity, **event})
        post = [(y, net, natural) for y, net, natural in series if y > 50]
        def first_year(predicate):
            return next((y for y, net, natural in post if predicate(net, natural)), "")
        regime_50 = next((e["regime"] for e in reversed(events) if e["confirmed_year"] <= 50), "")
        save["turning_points.csv"]({
            **entity, "regime_at_50": regime_50,
            "first_natural_decrease_after_50": first_year(lambda net, natural: natural < 0),
            "first_population_decrease_after_50": first_year(lambda net, natural: net < 0),
            "first_decline_despite_nonnegative_natural": first_year(lambda net, natural: net < 0 <= natural),
            "first_growth_despite_negative_natural": first_year(lambda net, natural: natural < 0 < net),
            "first_sustained_growth_to_non_growth_after_50": next((e["start_year"] for e in events
                if e["start_year"] > 50 and e["previous"] == "growth" and e["regime"] == "non_growth"), ""),
            "first_sustained_non_growth_to_growth_after_50": next((e["start_year"] for e in events
                if e["start_year"] > 50 and e["previous"] == "non_growth" and e["regime"] == "growth"), ""),
        })


def _published_prefixes():
    with (EXAMPLES / "phase3" / "runs.csv").open(encoding="utf-8", newline="") as stream:
        return {(int(r["seed"]), int(r["horizon"])): r["years_sha256"] for r in csv.DictReader(stream)
                if r["arm"] == "capital"}


def _simulate(directory, count, baseline_years, treatment_years):
    outputs = ("country_year.csv.gz", "world_year.csv.gz", "transitions.csv", "turning_points.csv",
               "checkpoints.csv", "paired.csv", "prefix_hashes.csv")
    prefixes = _published_prefixes()
    with ExitStack() as stack:
        save = {name: _writer(stack, directory, name) for name in outputs}
        for seed in range(count):
            initial = generate_world(seed)
            seam = {n.id: n.deposit for n in initial.nations}
            matching = {}
            for arm in STABILITY_ARMS:
                if arm == "baseline":
                    world, history, digest = initial, defaultdict(list), hashlib.sha256()
                    start, stop = 1, baseline_years
                else:
                    world, history = deepcopy(snapshot), deepcopy(first_50)
                    start, stop = 51, treatment_years
                intervals = dict.fromkeys(("food_deficit", "food_need", "births", "deaths", "ore_mined",
                                            "soil_restored", "deposit_added", "food_imports"), 0)
                for year in range(start, stop + 1):
                    record, nations = _collect(seed, arm, world, year, seam)
                    glob = _world(nations)
                    save["world_year.csv.gz"](glob)
                    for row in nations:
                        save["country_year.csv.gz"](row)
                    for i, r in [("world", glob), *((r["nation_id"], r) for r in nations)]:
                        history[i].append((year, r["pop_close"]-r["pop_open"], r["births"]-r["deaths"]))
                    if arm == "baseline" and year <= 200:
                        digest.update(canonical_line(record))
                        if (seed, year) in prefixes:
                            actual = digest.hexdigest()
                            if actual != prefixes[seed, year]:
                                raise ValueError(f"3.0 prefix mismatch at seed {seed}, year {year}")
                            save["prefix_hashes.csv"]({"seed":seed, "year":year, "sha256":actual})
                    if arm == "baseline" and year == 50:
                        snapshot, first_50 = deepcopy(world), deepcopy(history)
                    if year > 50:
                        for k in intervals:
                            intervals[k] += glob[k]
                    if year in CHECKPOINTS or year == stop or year == treatment_years:
                        result = {**glob, **{f"since_51_{k}": v for k, v in intervals.items()},
                                  "since_51_shortfall_share": _ratio(intervals["food_deficit"], intervals["food_need"])}
                        save["checkpoints.csv"](result)
                        if arm == "baseline":
                            matching[year] = result
                        else:
                            baseline = matching[year]
                            measures = ("pop_close", "food_deficit", "since_51_food_deficit",
                                        "since_51_shortfall_share", "since_51_births", "since_51_deaths",
                                        "since_51_ore_mined", "since_51_food_imports", "soil_close", "deposit_close",
                                        "top_cash_share", "assets_operated")
                            save["paired.csv"]({"seed":seed, "arm":arm, "year":year,
                                               **{"delta_"+k: result[k]-baseline[k] for k in measures}})
                _turns(seed, arm, history, save)


def run_study(output, *, seeds=20, baseline_years=500, treatment_years=200):
    if type(seeds) is not int or seeds < 1 or not 51 <= treatment_years <= baseline_years:
        raise ValueError("need seeds >= 1 and 51 <= treatment horizon <= baseline horizon")
    output = Path(output)
    if os.path.lexists(output):
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent, prefix=".stability31-") as scratch:
        staging = Path(scratch) / "results"
        staging.mkdir()
        _simulate(staging, seeds, baseline_years, treatment_years)
        manifest = {"model_version": POLICY.version, "labor": POLICY.labor, "investment": POLICY.investment,
                    "trade_order": POLICY.order, "seeds": [0, seeds-1], "baseline_years": baseline_years,
                    "intervention_years": [51,treatment_years], "regime_confirmation_years": 5,
                    "python": platform.python_version(),
                    "sha256": {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(staging.iterdir())}}
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        if os.path.lexists(output):
            raise FileExistsError(output)
        staging.rename(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--baseline-years", type=int, default=500)
    parser.add_argument("--treatment-years", type=int, default=200)
    args = parser.parse_args()
    run_study(args.out, seeds=args.seeds, baseline_years=args.baseline_years,
              treatment_years=args.treatment_years)
    print(f"Published {args.seeds} paired seeds; baseline {args.baseline_years}, "
          f"three interventions through {args.treatment_years}: {args.out}")


if __name__ == "__main__":
    main()
