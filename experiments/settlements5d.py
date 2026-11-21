"""Illustrative development seed with specified initial settlement sizes and no subsequent subsidy."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path

from civsim.collective import collective_snapshot, start_collective, step_collective
from civsim.collective_rules import ACTIVE
from civsim.model import generate_world
from civsim.regions import regionalize, sync_nations
from civsim.storage import canonical_line


def run(size):
    world = regionalize(generate_world(0))
    for r in world.regions:
        old = r.population
        r.cash = r.cash*size//old
        r.stock = {g: value*size//old for g, value in r.stock.items()}
        r.population = size
    sync_nations(world)
    sim = start_collective(world)
    initial = hashlib.sha256(canonical_line(collective_snapshot(sim))).hexdigest()
    annual = hashlib.sha256()
    totals = Counter()
    checkpoints = []
    for year in range(1, 201):
        row = step_collective(sim, year)
        annual.update(canonical_line(row))
        for area in row["collective"]["regions"]:
            for g in area["groups"].values():
                totals["potential_group_years"] += 1
                totals["size_at_least_8"] += int(g["members"] >= 8)
                totals["discontent_at_least_35"] += int(g["discontent"] >= 35)
                totals["active_group_years"] += int(g["action"] in ACTIVE)
                totals["starts"] += int(g["action"] in ACTIVE and g["duration"] == 1)
        totals["food_need"] += sum(r["consumption"]["food_need"] for r in row["regions"])
        totals["food_unmet"] += sum(r["consumption"]["food_unmet"] for r in row["regions"])
        if year in (50, 100, 200):
            checkpoints.append({"year": year, "population": sum(r.population for r in sim.world.regions),
                                **totals, "annual_sha256": annual.hexdigest()})
    return {"seed": 0, "initial_residents_per_region": size, "initial_population": size*32,
            "initial_sha256": initial, "checkpoints": checkpoints}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verify-against", type=Path)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output already exists")
    with ProcessPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(run, (6, 30, 150)))
    payload = (json.dumps(rows, ensure_ascii=False, indent=2)+"\n").encode("utf-8")
    if args.verify_against and payload != args.verify_against.read_bytes():
        raise ValueError("settlement replay mismatch")
    with args.out.open("xb") as f:
        f.write(payload)
    print([(r["initial_residents_per_region"], r["checkpoints"][-1]["starts"]) for r in rows])
