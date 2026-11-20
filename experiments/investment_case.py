"""Export the same country's history under inventory-only and productive investment."""

import argparse
import csv
from pathlib import Path

from civsim.engine import step
from civsim.investment import ASSETS
from civsim.model import GOODS, generate_world
from civsim.rules import Rules


def _case_row(seed, arm, year, country):
    opening, closing = country["opening"], country["closing"]
    prod, meal, people = country["production"], country["consumption"], country["demography"]
    plan = prod["investment"]
    return {
        "seed": seed, "arm": arm, "year": year, "nation_id": country["id"], "name": opening["name"],
        "population_open": opening["population"], "population_close": closing["population"],
        "births": people["births"], "deaths": people["deaths"],
        "immigrants": people["immigrants"], "emigrants": people["emigrants"],
        "soil_open": opening["soil"], "soil_close": closing["soil"], "climate": country["climate"],
        "cash_open": opening["cash"], "cash_close": closing["cash"],
        "deposit_open": opening["deposit"], "deposit_close": closing["deposit"],
        **{f"{g}_open": opening["stock"][g] for g in GOODS},
        **{f"{g}_close": closing["stock"][g] for g in GOODS},
        "production_workers": prod["workers"], "active_farmers": prod["active_farmers"],
        "construction_labor": plan["construction_labor"], "tool_target": plan["tool_target"],
        "tool_need": prod["tool_need"], "farm_tools_used": plan["sector_used"]["tools"],
        **{f"built_{a}": plan["built"][a] for a in ASSETS},
        **{f"operated_{a}": plan["operated"][a] for a in ASSETS},
        **{f"retired_{a}": plan["retired"][a] for a in ASSETS},
        **{f"build_{g}": plan["build_used"][g] for g in ("ore", "tools")},
        **{f"upkeep_{g}": plan["upkeep_used"][g] for g in ("ore", "tools")},
        **{f"{g}_output": prod["produced"][g] for g in GOODS},
        "reference_food_output": plan["reference_output"]["food"],
        "gross_gain_value": plan["gross_gain_value"], "food_need": meal["food_need"],
        "food_eaten": meal["food_eaten"], "food_unmet": meal["food_unmet"],
    }


def write_case(output: Path, *, seed: int, nation: int, years: int):
    if type(years) is not int or years <= 0:
        raise ValueError("years must be a positive integer")
    arms = {arm: (generate_world(seed), Rules("reallocate", investment=arm))
            for arm in ("inventory", "capital")}
    world, _ = arms["inventory"]
    if type(nation) is not int or not 0 <= nation < len(world.nations):
        raise ValueError(f"nation must be an ID from 0 through {len(world.nations) - 1}")

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    stream = output.open("x", encoding="utf-8", newline="")
    try:
        with stream:
            writer = None
            for year in range(1, years + 1):
                for arm, (world, rules) in arms.items():
                    record = step(world, year, rules)
                    country = next(c for c in record["countries"] if c["id"] == nation)
                    row = _case_row(seed, arm, year, country)
                    if writer is None:
                        writer = csv.DictWriter(stream, fieldnames=tuple(row))
                        writer.writeheader()
                    writer.writerow(row)
    except BaseException:
        output.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--nation", type=int, required=True)
    parser.add_argument("--years", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        write_case(args.out, seed=args.seed, nation=args.nation, years=args.years)
    except (ValueError, OSError) as error:
        parser.exit(1, f"{parser.prog}: {error}\n")
    print(f"{2 * args.years} country-year rows written to {args.out}")


if __name__ == "__main__":
    main()
