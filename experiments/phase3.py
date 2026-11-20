"""Four paired policy arms with cumulative world and investment metrics at each horizon."""

import argparse
import csv
import hashlib
import os
from dataclasses import asdict
from pathlib import Path
from statistics import fmean
from tempfile import TemporaryDirectory

from civsim.economy import BASE_PRICES
from civsim.engine import step
from civsim.investment import ASSETS, RECIPES, WORKER_VALUE
from civsim.model import GOODS, generate_world
from civsim.rules import Rules
from civsim.storage import canonical_line


ARMS = {
    "v1": Rules(),
    "v2": Rules("reallocate"),
    "inventory": Rules("reallocate", investment="inventory"),
    "capital": Rules("reallocate", investment="capital"),
}
IDENTIFIERS = {"seed", "arm", "horizon", "model_version", "initial_sha256", "years_sha256"}
BOOK_FIELDS = ("book_open_eighths", "book_additions_eighths", "book_depreciation_eighths", "book_close_eighths")


class Metrics:
    def __init__(self, world):
        self.initial_cash = sum(n.cash for n in world.nations)
        self.initial_deposit = sum(n.deposit for n in world.nations)
        self.initial_population = sum(n.population for n in world.nations)
        self.flow = dict.fromkeys((
            "food_need", "food_eaten", "food_deficit", "shortage_country_years", "trade_value",
            "tool_need_country_years", "saturated_country_years",
            "saturated_overproduction_country_years", "saturated_excess_country_years",
            "farm_tools_worn", "construction_labor", "gross_gain_value",
        ), 0)
        for good in GOODS:
            for field in (f"{good}_output", f"{good}_trade", f"build_{good}", f"upkeep_{good}",
                          f"net_gain_{good}"):
                self.flow[field] = 0
        asset_fields = ("built", "available", "operated", "retired", "terminal", "candidate_years",
                        "positive_return_years", "eligible_years", *BOOK_FIELDS)
        self.assets = {a: dict.fromkeys(asset_fields, 0) for a in ASSETS}
        self.digest = hashlib.sha256()

    def _investment(self, plan, year):
        self.flow["construction_labor"] += plan["construction_labor"]
        self.flow["gross_gain_value"] += plan["gross_gain_value"]
        for good in GOODS:
            self.flow[f"build_{good}"] += plan["build_used"][good]
            self.flow[f"upkeep_{good}"] += plan["upkeep_used"][good]
            self.flow[f"net_gain_{good}"] += plan["net_output_gain"][good]
        for kind, counts in self.assets.items():
            counts["available"] += sum(plan["opening_capital"][kind])
            counts["terminal"] += sum(plan["closing_capital"][kind])
            for key in ("built", "operated", "retired"):
                counts[key] += plan[key][kind]
            candidate = plan["candidates"].get(kind)
            if candidate is not None:
                counts["candidate_years"] += 1
                counts["positive_return_years"] += int(candidate["net_value"] > 0)
                counts["eligible_years"] += int(not candidate["constraints"])
            book = plan["book"][kind]
            if year == 1:
                counts["book_open_eighths"] += book["open_eighths"]
            counts["book_additions_eighths"] += book["additions_eighths"]
            counts["book_depreciation_eighths"] += book["depreciation_eighths"]
            counts["book_close_eighths"] += book["close_eighths"]

    def observe(self, record):
        self.digest.update(canonical_line(record))
        for counts in self.assets.values():
            counts["terminal"] = 0
            counts["book_close_eighths"] = 0
        for trade in record["market"]["trades"]:
            self.flow[f"{trade['good']}_trade"] += trade["quantity"]
            self.flow["trade_value"] += trade["value"]
        for nation in record["countries"]:
            prod = nation["production"]
            plan = prod.get("investment")
            if plan is not None:
                self._investment(plan, record["year"])
            meal = nation["consumption"]
            self.flow["food_need"] += meal["food_need"]
            self.flow["food_eaten"] += meal["food_eaten"]
            deficit = meal["food_unmet"]
            self.flow["food_deficit"] += deficit
            self.flow["shortage_country_years"] += int(deficit > 0)
            for good in GOODS:
                self.flow[f"{good}_output"] += prod["produced"][good]
            need = prod["tool_need"]
            wear = prod["used"]["tools"] if plan is None else plan["sector_used"]["tools"]
            self.flow["farm_tools_worn"] += wear
            self.flow["tool_need_country_years"] += int(need > 0)
            if need > 0 and wear == need:
                self.flow["saturated_country_years"] += 1
                made = prod["produced"]["tools"]
                stock = nation["closing"]["stock"]["tools"]
                self.flow["saturated_overproduction_country_years"] += int(
                    made > 0 and stock > nation["opening"]["stock"]["tools"]
                )
                self.flow["saturated_excess_country_years"] += int(made > wear and stock > need)

    def snapshot(self, world):
        nations = world.nations
        cash = sum(n.cash for n in nations)
        deposit = sum(n.deposit for n in nations)
        if cash != self.initial_cash or deposit + self.flow["ore_output"] != self.initial_deposit:
            raise ValueError(f"year {world.year}: world cash or deposit balance failed")
        build_value = sum(BASE_PRICES[g] * self.flow[f"build_{g}"] for g in GOODS)
        upkeep_value = sum(BASE_PRICES[g] * self.flow[f"upkeep_{g}"] for g in GOODS)
        labor_value = WORKER_VALUE * self.flow["construction_labor"]
        cost = build_value + upkeep_value + labor_value
        if self.flow["food_deficit"] != self.flow["food_need"] - self.flow["food_eaten"]:
            raise ValueError(f"year {world.year}: food shortfall differs from annual rations")
        if self.flow["gross_gain_value"] != sum(BASE_PRICES[g] * self.flow[f"net_gain_{g}"] for g in GOODS):
            raise ValueError(f"year {world.year}: local output valuation differs from physical gains")
        run = {
            "years_sha256": self.digest.hexdigest(), "initial_population": self.initial_population,
            "final_population": sum(n.population for n in nations), **self.flow,
            "initial_deposit": self.initial_deposit, "final_deposit": deposit,
            "depleted_nations": sum(n.deposit == 0 for n in nations),
            "final_tools_stock": sum(n.stock["tools"] for n in nations),
            "initial_cash": self.initial_cash, "final_cash": cash,
            "final_top1_share": max(n.cash for n in nations) / cash,
            "final_hhi": sum(n.cash**2 for n in nations) / cash**2,
            "build_value": build_value, "upkeep_value": upkeep_value,
            "construction_labor_value": labor_value, "investment_input_value": cost,
            "local_net_roi": (self.flow["gross_gain_value"] - cost) / cost if cost else None,
            "deficit_share": self.flow["food_deficit"] / self.flow["food_need"],
        }
        assets = []
        for kind, counts in self.assets.items():
            if counts["built"] - counts["retired"] != counts["terminal"]:
                raise ValueError(f"year {world.year}: unmatched {kind} asset")
            book = counts["book_open_eighths"] + counts["book_additions_eighths"] - counts["book_depreciation_eighths"]
            if book != counts["book_close_eighths"]:
                raise ValueError(f"year {world.year}: unmatched {kind} book balance")
            recipe = RECIPES[kind]
            available, operated, built = counts["available"], counts["operated"], counts["built"]
            assets.append({
                "asset": kind, **counts, "utilization": operated / available if available else None,
                "build_ore": built * recipe.build_ore, "build_tools": built * recipe.build_tools,
                "construction_labor": built * recipe.workers,
                "upkeep_ore": operated * recipe.upkeep_ore, "upkeep_tools": operated * recipe.upkeep_tools,
            })
        for key in ("build_ore", "build_tools", "construction_labor", "upkeep_ore", "upkeep_tools"):
            if sum(a[key] for a in assets) != run[key]:
                raise ValueError(f"year {world.year}: asset recipe total differs from posted {key}")
        run.update({k: sum(a[k] for a in assets) for k in BOOK_FIELDS})
        return run, assets


def _experiment(seeds, horizons):
    runs, assets = [], []
    for seed in range(seeds):
        common_hash = None
        for arm, rules in ARMS.items():
            world = generate_world(seed)
            initial_hash = hashlib.sha256(canonical_line(asdict(world))).hexdigest()
            if common_hash is not None and common_hash != initial_hash:
                raise ValueError(f"seed {seed}: initial worlds differ")
            common_hash = initial_hash
            metrics = Metrics(world)
            for year in range(1, max(horizons) + 1):
                metrics.observe(step(world, year, rules))
                if year in horizons:
                    run, classes = metrics.snapshot(world)
                    key = {"seed": seed, "arm": arm, "horizon": year}
                    runs.append({**key, "model_version": rules.version, "initial_sha256": initial_hash, **run})
                    assets.extend({**key, **row} for row in classes)
    return runs, assets


def _comparisons(runs, horizons):
    numeric = [k for k in runs[0] if k not in IDENTIFIERS]
    by_key = {(r["seed"], r["arm"], r["horizon"]): r for r in runs}
    paired = []
    for (seed, arm, year), row in by_key.items():
        if arm == "capital":
            base = by_key[seed, "inventory", year]
            paired.append({"seed": seed, "horizon": year, **{
                f"delta_{k}": row[k] - base[k] for k in numeric if k != "local_net_roi"
            }})
    means = []
    for arm in ARMS:
        for year in sorted(horizons):
            group = [r for r in runs if r["arm"] == arm and r["horizon"] == year]
            total_cost = sum(r["investment_input_value"] for r in group)
            total_gain = sum(r["gross_gain_value"] for r in group)
            mean = {"arm": arm, "horizon": year, "seeds": len(group),
                    "pooled_deficit_share": sum(r["food_deficit"] for r in group) / sum(r["food_need"] for r in group),
                    "roi_defined_seeds": sum(r["local_net_roi"] is not None for r in group),
                    "pooled_local_net_roi": (total_gain - total_cost) / total_cost if total_cost else None}
            for k in numeric:
                values = [r[k] for r in group if r[k] is not None]
                mean[k] = fmean(values) if values else None
            means.append(mean)
    return paired, means


def run_experiment(output: Path, *, seeds=20, horizons=(50, 200)):
    horizons = tuple(horizons)
    if type(seeds) is not int or seeds < 1:
        raise ValueError("seeds must be a positive integer")
    if (not horizons or any(type(y) is not int or y < 1 for y in horizons)
            or len(set(horizons)) != len(horizons)):
        raise ValueError("horizons must be distinct positive integers")
    output = Path(output)
    if os.path.lexists(output):
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent, prefix=".phase3-") as scratch:
        staging = Path(scratch) / "results"
        staging.mkdir()
        runs, assets = _experiment(seeds, horizons)
        paired, means = _comparisons(runs, horizons)
        for name, records in [("runs", runs), ("assets", assets), ("paired", paired), ("means", means)]:
            with (staging / f"{name}.csv").open("x", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=tuple(records[0]))
                writer.writeheader()
                writer.writerows(records)
        if os.path.lexists(output):
            raise FileExistsError(output)
        staging.rename(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--horizons", default="50,200", help="comma-separated positive years")
    args = parser.parse_args()
    try:
        horizons = tuple(int(y) for y in args.horizons.split(","))
        run_experiment(args.out, seeds=args.seeds, horizons=horizons)
    except (ValueError, OSError) as error:
        parser.exit(1, f"{parser.prog}: {error}\n")
    print(f"{args.seeds * len(ARMS)} runs, {len(horizons)} horizons. {args.out}")


if __name__ == "__main__":
    main()
