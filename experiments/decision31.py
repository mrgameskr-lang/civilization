"""Matched nine-year outcomes after one feasible decision, development seeds only."""

import argparse
from collections import Counter
import csv
import os
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from civsim import investment
from civsim.economy import BASE_PRICES
from civsim.engine import step
from civsim.investment import ASSETS
from civsim.model import GOODS, generate_world
from civsim.rules import Rules
from civsim.storage import canonical_line
from experiments.publication import publish_file


CONTROL = Rules("reallocate", investment="capital")


def eligible_actions(plan):
    return [k for k in ASSETS if not plan["candidates"][k]["constraints"]]


def first_choice(world, country_id, action, original_plan):
    """Restrict one decision menu; the simulator itself still pays, operates and audits."""
    if action != "defer" and action not in eligible_actions(original_plan):
        raise ValueError(f"ineligible action: {action}")
    natural = next((k for k in ASSETS if original_plan["built"][k]), "defer")
    original_candidate = investment._candidate

    def restrict(nation, key, *args):
        candidate = original_candidate(nation, key, *args)
        if nation.id == country_id:
            if candidate != original_plan["candidates"][key]:
                raise ValueError("focal candidate differs from matched initial decision")
            if key != action:
                candidate["constraints"].append("excluded_by_experimental_menu")
        return candidate

    if action == natural:
        record = step(world, world.year + 1, CONTROL)
    else:
        # This serial experiment patches the menu only for the decision year.
        with patch.object(investment, "_candidate", restrict):
            record = step(world, world.year + 1, CONTROL)
    built = record["countries"][country_id]["production"]["investment"]["built"]
    if built != {k: int(k == action) for k in ASSETS}:
        raise ValueError("decision was not implemented")
    return record


def _case(seed):
    world = generate_world(seed)
    for year in range(1, 201):
        # step() replaces country states after audit; this retains the unadvanced world.
        start = replace(world)
        observed = step(world, year, CONTROL)
        if year <= 50:
            continue
        for country in observed["countries"]:  # Engine emits ascending country IDs.
            plan = country["production"]["investment"]
            if "land" in eligible_actions(plan) and plan["built"]["land"] == 0:
                return start, country["id"], plan
    return None


def _follow(start, country_id, action, plan):
    world = replace(start)
    first = first_choice(world, country_id, action, plan)
    first_plan = first["countries"][country_id]["production"]["investment"]
    totals = Counter()
    for offset in range(9):
        record = first if offset == 0 else step(world, world.year + 1, CONTROL)
        focal = record["countries"][country_id]
        prod = focal["production"]
        totals["focal_food_shortfall"] += focal["consumption"]["food_unmet"]
        totals["world_food_shortfall"] += sum(c["consumption"]["food_unmet"] for c in record["countries"])
        # Labor diverted to construction already affects actual production. Goods
        # input includes upkeep, building and conversion; do not price labor again.
        totals["focal_net_production_value"] += sum(
            BASE_PRICES[g] * (prod["produced"][g] - prod["used"][g]) for g in GOODS)
        totals["focal_food_output"] += prod["produced"]["food"]
        if offset == 5:
            totals["focal_net_value_through_service_year5"] = totals["focal_net_production_value"]
    return {
        "forecast_net_value": plan["candidates"][action]["net_value"] if action != "defer" else 0,
        "first_build_tools": first_plan["build_used"]["tools"],
        "first_build_ore": first_plan["build_used"]["ore"],
        "first_build_workers": first_plan["construction_labor"],
        **totals, "focal_terminal_population": world.nations[country_id].population,
        "world_terminal_population": sum(n.population for n in world.nations),
    }


def run(output):
    output = Path(output)
    if os.path.lexists(output):
        raise FileExistsError(output)
    rows = []
    for seed in range(20):
        selected = _case(seed)
        if selected is None:
            rows.append({"seed": seed, "action": "no_matched_case"})
            continue
        start, country_id, plan = selected
        actions = eligible_actions(plan)
        natural = next(k for k in ASSETS if plan["built"][k])
        state = {"seed": seed, "year": start.year, "nations": [asdict(n) for n in start.nations]}
        matched = sha256(canonical_line(state)).hexdigest()
        outcomes = {a: _follow(start, country_id, a, plan) for a in ["defer", *actions]}
        for action, outcome in outcomes.items():
            row = {"seed": seed, "decision_year": start.year+1, "terminal_year": start.year+9,
                   "country": country_id, "state_sha256": matched, "eligible": ",".join(actions),
                   "natural": natural, "action": action, **outcome}
            for key in ("focal_net_value_through_service_year5", "focal_net_production_value", "focal_food_shortfall",
                        "world_food_shortfall", "focal_terminal_population", "world_terminal_population"):
                row[f"delta_{key}_vs_defer"] = outcome[key] - outcomes["defer"][key]
                row[f"delta_{key}_vs_natural"] = outcome[key] - outcomes[natural][key]
            rows.append(row)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = dict.fromkeys(key for row in rows for key in row)
    with TemporaryDirectory(dir=output.parent, prefix=".decision31-") as temp:
        staging = Path(temp, "choices.csv")
        with staging.open("x", encoding="utf-8", newline="") as out:
            writer = csv.DictWriter(out, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        publish_file(staging, output)
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="new branch-outcomes CSV")
    args = parser.parse_args()
    result = run(args.out)
    print(f"{len(result)} branch/no-match rows from 20 development seeds. {args.out}")
