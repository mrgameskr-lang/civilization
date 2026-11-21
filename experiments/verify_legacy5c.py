"""Replay archived 5.0B feedback-off controls and compare their fiscal and political journals."""
import argparse
import csv
from concurrent.futures import ProcessPoolExecutor
import hashlib
from pathlib import Path

from civsim.model import generate_world
from civsim.politics import political_snapshot, start_political, step_political
from civsim.regions import regionalize
from civsim.storage import canonical_line


def _replay(item):
    seed, refs = item
    sim = start_political(regionalize(generate_world(seed)))
    initial = hashlib.sha256(canonical_line(political_snapshot(sim))).hexdigest()
    full, fiscal = hashlib.sha256(), hashlib.sha256()
    for year in range(1, max(refs)+1):
        record = step_political(sim, year, False)
        full.update(canonical_line(record))
        fiscal.update(canonical_line({k:v for k,v in record.items() if k!="politics"}))
        if year in refs and (initial, full.hexdigest(), fiscal.hexdigest()) != refs[year]:
            raise ValueError(f"5.0B feedback-off replay differs at seed {seed} year {year}")
    return len(refs)


def replay(workers):
    cases = {}
    directory = Path(__file__).resolve().parents[1]/"examples"/"phase5b"/"study"
    for sample in ("dev", "holdout"):
        with (directory/sample/"runs.csv").open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if row["arm"]=="off":
                    cases.setdefault(int(row["seed"]), {})[int(row["year"])] = tuple(
                        row[k] for k in ("initial_political_sha256", "years_sha256", "fiscal_sha256"))
    if set(cases)!=set(range(40)) or any(set(v)!={50,100,200} for v in cases.values()):
        raise ValueError("incomplete historical control matrix")
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return sum(pool.map(_replay, cases.items()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    print(f"{replay(args.workers)} archived 5.0B feedback-off checkpoints matched")
