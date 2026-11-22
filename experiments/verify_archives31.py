"""Replay each unique historical path and check every archived initial/annual hash."""

import argparse
import csv
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import hashlib
from pathlib import Path

from civsim.engine import step
from civsim.model import generate_world
from civsim.rules import Rules
from civsim.storage import canonical_line, verify_run
from experiments.phase3 import ARMS


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _check_path(job):
    (seed, rules), checkpoints = job
    world = generate_world(seed)
    initial = hashlib.sha256(canonical_line(asdict(world))).hexdigest()
    digest = hashlib.sha256()
    count = 0
    for year in range(1, max(checkpoints) + 1):
        digest.update(canonical_line(step(world, year, rules)))
        for archive, init, annual in checkpoints.get(year, ()):
            if (initial, digest.hexdigest()) != (init, annual):
                raise ValueError(f"{archive} seed={seed} year={year} {rules} hash mismatch")
            count += 1
    return count


def verify_archives(workers):
    jobs = defaultdict(lambda: defaultdict(list))
    for archive in ("phase2-seeds-0-19", "phase3"):
        with (EXAMPLES / archive / "runs.csv").open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                if "arm" in row:
                    rules, years = ARMS[row["arm"]], int(row["horizon"])
                else:
                    rules, years = Rules(row["labor"], tuple(row["order"].split("-"))), int(row["years"])
                jobs[int(row["seed"]), rules][years].append(
                    (archive, row["initial_sha256"], row["years_sha256"])
                )
    with ProcessPoolExecutor(max_workers=workers) as pool:
        count = sum(pool.map(_check_path, jobs.items()))
    print(f"{count} archived checkpoint rows: exact initial and annual SHA-256 matches, "
          f"{len(jobs)} distinct seed/policy trajectories")
    for manifest in sorted(EXAMPLES.rglob("manifest.json")):
        if "phase31" not in manifest.relative_to(EXAMPLES).parts:
            print(f"{manifest.parent.relative_to(EXAMPLES).as_posix()}  {verify_run(manifest.parent)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=4)
    verify_archives(parser.parse_args().workers)
