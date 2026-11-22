"""Recompute cohort summaries and choose actual counterexamples from published tables."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
from statistics import mean, median

from civsim.annual_game import create
from experiments.diffusion72 import ARMS, CHECKPOINTS, METRICS
from experiments.research71 import ROOT, write_json


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def contact_stats(regions):
    result = []
    ranges = ((0, 0), (1, 199), (200, 999), (1000, None))
    for low, high in ranges:
        sample = [r for r in regions if int(r["domestic_arrivals"]) >= low and
                  (high is None or int(r["domestic_arrivals"]) <= high)]
        contacts = [r for r in sample if int(r["first_contact"])]
        result.append({"arrival_range": [low, high], "regions": len(sample),
                       "contact": len(contacts), "transfer": sum(r["method"] == "transfer" for r in sample),
                       "independent": sum(r["method"] == "independent" for r in sample),
                       "pending": sum(not r["method"] for r in contacts),
                       "median_first_contact": median(int(r["first_contact"]) for r in contacts) if contacts else None})
    return result


def cohort(countries, regions, pairs, start, year):
    worlds = [r for r in pairs if start <= r["seed"] < start + 20 and r["year"] == year]
    totals = {}
    for arm in ARMS:
        group = [r for r in countries if r["arm"] == arm and start <= int(r["seed"]) < start + 20 and int(r["year"]) == year]
        totals[arm] = {k: sum(int(r[k]) for r in group) for k in METRICS}
    sites = [r for r in regions if r["arm"] == "diffusion" and start <= int(r["seed"]) < start + 20 and int(r["year"]) == year]
    transfers = [r for r in sites if r["method"] == "transfer"]
    delays = [int(r["adoption_year"]) - int(r["first_contact"]) for r in transfers]
    # Choose cases by a published rule; no hand selection of a favourable world.
    pending = [r for r in sites if not r["method"] and int(r["first_contact"])]
    unexposed = [r for r in sites if not r["method"] and not int(r["first_contact"])]

    def busiest(records):
        return max(records, key=lambda r: (int(r["domestic_arrivals"]), -int(r["seed"]), -int(r["region"])),
                   default=None)
    return {"cohort": "development" if start == 0 else "validation", "year": year, "arm_totals": totals,
            "paired_mean": {k: mean(w[k] for w in worlds) for k in (*METRICS, "support_delta", "shortage_rate_delta")},
            "signs": {k: {"higher": sum(w[k] > 0 for w in worlds), "lower": sum(w[k] < 0 for w in worlds),
                          "same": sum(w[k] == 0 for w in worlds)}
                      for k in ("population", "food", "border_exports", "shortage_rate_delta", "turnovers")},
            "worlds_with_transfer": len({r["seed"] for r in transfers}),
            "worlds_without_transfer": sorted(set(range(start, start + 20)) - {int(r["seed"]) for r in transfers}),
            "pending_regions": len(pending), "arrivals": contact_stats(sites),
            "contact_to_adoption_years": {"min": min(delays), "median": median(delays), "max": max(delays)} if delays else None,
            "busiest_pending_region": busiest(pending), "busiest_region_without_contact_or_adoption": busiest(unexposed),
            "lowest_population_delta": min(worlds, key=lambda w: (w["population"], w["seed"])),
            "highest_population_delta": max(worlds, key=lambda w: (w["population"], -w["seed"]))}


def summarize(folder):
    countries = read_csv(folder / "countries.csv")
    regions = read_csv(folder / "regions.csv")
    pairs = json.loads((folder / "paired.json").read_bytes())
    previous = read_csv(ROOT / "studies/research71/long/countries.csv")
    def key(row):
        return row["seed"], row["year"], row["owner"]
    controls = {key(row): row for row in countries if row["arm"] == "research"}
    archived = {key(row): row for row in previous if row["arm"] == "research"}
    if controls.keys() != archived.keys() or len(controls) != 40 * 3 * 8:
        raise ValueError("missing a published research-control country checkpoint")
    for identity, old in archived.items():
        for field, value in old.items():
            if controls[identity][field] != value:
                raise ValueError(f"7.1 country measurement differs at {identity} for {field}")
    degree = Counter()
    for seed in range(40):
        world = create(seed).economy.world
        count = Counter(i for edge in world.roads for i in (edge.a, edge.b))
        degree.update(count[r.id] for r in world.regions)
    return {"archived_country_checkpoints_verified": len(controls), "domestic_road_degree": dict(degree), "cohorts": [
        cohort(countries, regions, pairs, start, year) for start in (0, 20) for year in CHECKPOINTS]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    write_json(args.out, summarize(args.study))
