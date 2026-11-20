"""Extend the primary paired policies to year 500 on the original development seeds."""
import argparse
import csv
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from civsim.engine import step
from civsim.model import generate_world
from civsim.rules import Rules


def trajectory(job):
    seed, policy = job
    world = generate_world(seed)
    rules = Rules("reallocate", investment="capital", policy31=policy)
    checkpoints = (50, 100, 150, 200, 300, 400, 500)
    population = start = low = high = sum(n.population for n in world.nations)
    births = deaths = unmet = need = 0
    previous = 0
    rows = []
    for year in range(1, checkpoints[-1] + 1):
        record = step(world, year, rules)
        for country in record["countries"]:
            demo, meal = country["demography"], country["consumption"]
            births += demo["births"]
            deaths += demo["deaths"]
            unmet += meal["food_unmet"]
            need += meal["food_need"]
        population = sum(n.population for n in world.nations)
        low = min(low, population)
        high = max(high, population)
        if year in checkpoints:
            if births - deaths != population - start:
                raise ValueError(f"seed {seed}, year {year}: population mismatch")
            rows.append({"seed": seed, "policy": policy, "year": year, "interval_start": previous + 1,
                         "population": population, "population_delta": population - start,
                         "interval_min_population": low, "interval_max_population": high,
                         "births": births, "deaths": deaths, "food_unmet": unmet, "food_need": need,
                         "interval_unmet_share": unmet / need if need else 0,
                         "deposit": sum(n.deposit for n in world.nations),
                         "empty_deposits": sum(n.deposit == 0 for n in world.nations)})
            previous = year
            start = low = high = population
            births = deaths = unmet = need = 0
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--workers", default=4, type=int)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        raise FileExistsError(args.out)
    jobs = [(seed, policy) for seed in range(20) for policy in ("off", "combined-multi")]
    with TemporaryDirectory(dir=args.out.parent) as tmp, ProcessPoolExecutor(max_workers=args.workers) as pool:
        path = Path(tmp, "result.csv")
        with path.open("x", encoding="utf-8", newline="") as stream:
            writer = None
            for rows in pool.map(trajectory, jobs):
                if writer is None:
                    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                    writer.writeheader()
                writer.writerows(rows)
        # Exclusive creation preserves historical experiment artifacts in concurrent runs.
        with args.out.open("xb") as target:
            target.write(path.read_bytes())
    print("40 paired-arm trajectories, 20,000 audited world-years, 280 checkpoints")


if __name__ == "__main__":
    main()
