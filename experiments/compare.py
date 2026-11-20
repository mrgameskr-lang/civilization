"""Paired, single-factor contrasts across the 2 × 6 phase-two design."""

import argparse
import csv
from itertools import permutations
from pathlib import Path
from statistics import fmean, median, quantiles

from civsim.model import GOODS


ORDERS = tuple("-".join(order) for order in permutations(GOODS))
METRICS = (
    "final_population", "food_deficit", "shortage_country_years",
    "food_output", "ore_output", "tools_output", "food_trade", "ore_trade", "tools_trade",
    "trade_value", "farm_overflow", "reassigned_mine", "reassigned_factory",
    "final_top1_share", "final_hhi", "zero_country_years", "near_zero_country_years",
)


def paired_stats(a, b):
    """Summarize differences B minus A; dict keys identify independent starting worlds."""
    if not a or a.keys() != b.keys():
        raise ValueError("each scenario needs the same nonempty set of seeds")
    delta = {s: round(b[s] - a[s], 12) for s in sorted(a)}
    values = list(delta.values())
    # A one-seed smoke run has no distributional information.
    q1, _, q3 = quantiles(values, n=4, method="inclusive") if len(values) > 1 else values * 3
    margin = 1.5 * (q3 - q1)
    low, high = min(values), max(values)
    outliers = [s for s, d in delta.items() if d < q1 - margin or d > q3 + margin]
    return {
        "seeds": len(values), "a_mean": fmean(a.values()), "b_mean": fmean(b.values()),
        "mean_delta": fmean(values), "median_delta": median(values),
        "increased": sum(d > 0 for d in values), "equal": values.count(0),
        "decreased": sum(d < 0 for d in values),
        "min_delta": low, "max_delta": high,
        "min_seeds": " ".join(str(s) for s, d in delta.items() if d == low),
        "max_seeds": " ".join(str(s) for s, d in delta.items() if d == high),
        "q1_delta": q1, "q3_delta": q3,
        "outlier_seeds": " ".join(map(str, outliers)),
    }


def _read_scenarios(path):
    scenarios = {(labor, order): {} for labor in ("idle", "reallocate") for order in ORDERS}
    world_hashes = {}
    years = set()
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            seed = int(row["seed"])
            years.add(int(row["years"]))
            if world_hashes.setdefault(seed, row["initial_sha256"]) != row["initial_sha256"]:
                raise ValueError(f"seed {seed}: initial world mismatch")
            key = (row["labor"], row["order"])
            if key not in scenarios or seed in scenarios[key]:
                raise ValueError(f"unexpected or duplicate scenario {key} for seed {seed}")
            scenarios[key][seed] = {metric: float(row[metric]) for metric in METRICS}
    if len(years) != 1 or not world_hashes:
        raise ValueError("scenario durations must match and dataset must be nonempty")
    if any(rows.keys() != world_hashes.keys() for rows in scenarios.values()):
        raise ValueError("incomplete set of paired scenarios")
    return scenarios


def _contrasts():
    for order in ORDERS:
        yield "labor", ("idle", order), ("reallocate", order)
    for labor in ("idle", "reallocate"):
        for order in ORDERS[1:]:
            yield "order", (labor, ORDERS[0]), (labor, order)


def compare(path: Path, output: Path):
    """Publish a table of 16 contrasts per metric, protecting existing results."""
    scenarios = _read_scenarios(path)
    results = []
    for factor, a, b in _contrasts():
        for metric in METRICS:
            x = {s: row[metric] for s, row in scenarios[a].items()}
            y = {s: row[metric] for s, row in scenarios[b].items()}
            results.append({"factor": factor, "a_labor": a[0], "a_order": a[1],
                            "b_labor": b[0], "b_order": b[1], "metric": metric,
                            **paired_stats(x, y)})
    with output.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs_csv", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    compare(args.runs_csv, args.out)
