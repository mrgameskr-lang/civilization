"""Evaluate every labor policy and settlement order on paired, seeded worlds."""

import argparse
import csv
import hashlib
import os
from dataclasses import asdict
from itertools import permutations
from pathlib import Path
from tempfile import TemporaryDirectory

from civsim.engine import step
from civsim.model import GOODS, generate_world
from civsim.rules import Rules
from civsim.storage import canonical_line


def measure_records(nations, records):
    """Reduce audited annual records without retaining past years in memory."""
    total_cash = sum(n.cash for n in nations)
    if total_cash <= 0:
        raise ValueError("cash shares require positive world cash")
    countries = {
        n.id: {
            "nation_id": n.id, "name": n.name, "initial_cash": n.cash, "final_cash": n.cash,
            "min_cash": n.cash, "first_zero_year": None, "zero_years": 0, "near_zero_years": 0,
            "final_cash_share": n.cash / total_cash, "peak_cash_share": n.cash / total_cash,
            **{f"net_{g}_cash": 0 for g in GOODS}, "food_deficit": 0, "shortage_years": 0,
        }
        for n in nations
    }
    initial_population = sum(n.population for n in nations)
    run = {
        "initial_population": initial_population, "final_population": initial_population,
        "food_deficit": 0, "shortage_country_years": 0,
        **{f"{g}_output": 0 for g in GOODS}, **{f"{g}_trade": 0 for g in GOODS},
        "trade_value": 0, "farm_overflow": 0, "reassigned_mine": 0, "reassigned_factory": 0,
    }
    digest = hashlib.sha256()
    for record in records:
        digest.update(canonical_line(record))
        year = record["year"]
        for trade in record["market"]["trades"]:
            good = trade["good"]
            amount = trade["quantity"] * trade["unit_price"]
            countries[trade["seller"]][f"net_{good}_cash"] += amount
            countries[trade["buyer"]][f"net_{good}_cash"] -= amount
            run[f"{good}_trade"] += trade["quantity"]
            run["trade_value"] += amount
        run["final_population"] = 0
        for row in record["countries"]:
            nation = countries[row["id"]]
            close, production, meal = row["closing"], row["production"], row["consumption"]
            run["final_population"] += close["population"]
            for good in GOODS:
                run[f"{good}_output"] += production["produced"][good]
            assigned = production["workers"] * production["farm_share"] // 1000
            run["farm_overflow"] += assigned - production["active_farmers"]
            if "reassigned" in production:
                run["reassigned_mine"] += production["reassigned"]["mine"]
                run["reassigned_factory"] += production["reassigned"]["factory"]
            deficit = meal["food_need"] - meal["food_eaten"]
            nation["food_deficit"] += deficit
            nation["shortage_years"] += int(deficit > 0)
            cash = close["cash"]
            explained_cash = nation["initial_cash"] + sum(nation[f"net_{g}_cash"] for g in GOODS)
            if cash != explained_cash:
                raise ValueError(f"year {year}, nation {row['id']}: unexplained cash change")
            nation["final_cash"] = cash
            nation["min_cash"] = min(nation["min_cash"], cash)
            if cash == 0:
                nation["zero_years"] += 1
                if nation["first_zero_year"] is None:
                    nation["first_zero_year"] = year
            nation["near_zero_years"] += int(cash * 100 <= nation["initial_cash"])
            nation["final_cash_share"] = cash / total_cash
            nation["peak_cash_share"] = max(nation["peak_cash_share"], nation["final_cash_share"])

    rows = list(countries.values())
    run.update(
        food_deficit=sum(n["food_deficit"] for n in rows),
        shortage_country_years=sum(n["shortage_years"] for n in rows),
        final_top1_share=max(n["final_cash"] for n in rows) / total_cash,
        final_hhi=sum(n["final_cash"] ** 2 for n in rows) / total_cash**2,
        zero_country_years=sum(n["zero_years"] for n in rows),
        near_zero_country_years=sum(n["near_zero_years"] for n in rows),
    )
    return {"years_sha256": digest.hexdigest(), **run}, rows


def _write_matrix(directory, seeds, years):
    with (directory / "runs.csv").open("x", encoding="utf-8", newline="") as runs_file, (
        directory / "countries.csv"
    ).open("x", encoding="utf-8", newline="") as countries_file:
        run_writer = None
        for seed in range(seeds):
            common_initial = None
            for labor in ("idle", "reallocate"):
                for order in permutations(GOODS):
                    rules = Rules(labor=labor, order=order)
                    world = generate_world(seed)
                    initial_hash = hashlib.sha256(canonical_line(asdict(world))).hexdigest()
                    if common_initial is not None and common_initial != initial_hash:
                        raise ValueError(f"seed {seed}: different initial world across scenarios")
                    common_initial = initial_hash
                    records = (step(world, year, rules=rules) for year in range(1, years + 1))
                    run, countries = measure_records(world.nations, records)
                    scenario = {"seed": seed, "labor": labor, "order": "-".join(order),
                                "model_version": rules.version, "years": years}
                    run_row = {**scenario, "initial_sha256": initial_hash, **run}
                    if run_writer is None:
                        run_writer = csv.DictWriter(runs_file, fieldnames=tuple(run_row))
                        country_writer = csv.DictWriter(countries_file, fieldnames=(*scenario, *countries[0]))
                        run_writer.writeheader()
                        country_writer.writeheader()
                    run_writer.writerow(run_row)
                    country_writer.writerows({**scenario, **n} for n in countries)


def run_experiment(output: Path, *, seeds: int = 20, years: int = 50):
    """Publish two compact CSVs after all experiments and cash reconciliations succeed."""
    if any(type(value) is not int or value < 1 for value in (seeds, years)):
        raise ValueError("seeds and years must be positive integers")
    output = Path(output)
    if os.path.lexists(output):
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent, prefix=".phase2-") as scratch:
        staging = Path(scratch) / "matrix"
        staging.mkdir()
        _write_matrix(staging, seeds, years)
        if os.path.lexists(output):
            raise FileExistsError(output)
        staging.rename(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="new output directory")
    parser.add_argument("--seeds", default=20, type=int, help="use consecutive seeds from zero")
    parser.add_argument("--years", default=50, type=int, help="years per run")
    args = parser.parse_args()
    try:
        run_experiment(args.out, seeds=args.seeds, years=args.years)
    except (ValueError, OSError) as error:
        parser.exit(1, f"{parser.prog}: {error}\n")
    print(f"{args.seeds * 12} runs, {args.years} years each. {args.out}")


if __name__ == "__main__":
    main()
