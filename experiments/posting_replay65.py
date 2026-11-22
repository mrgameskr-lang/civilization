"""Check the PR 18 economy, consultations and optional register through M1's unchanged A path."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
import hashlib
import io
from pathlib import Path
from time import perf_counter

from civsim.posting_engine65 import run
from civsim.storage import canonical_line
from experiments.verify_civic_off64 import publish_receipt


BASE = Path(__file__).resolve().parents[1] / "examples" / "phase6c1-followup" / "pledges"
PINS = {
    "dev": "4c6a17872a515c1e46fa79c04f46846bf75410790272b579fd1623ade388eaeb",
    "holdout": "886771ba045a79578ca708a6883d6d9d58562d868504433ddb652079e4ef111f",
}
FIELDS = ("economic_years_sha256", "civic_years_sha256", "register_sha256")


def baseline():
    refs = {seed: {} for seed in range(40)}
    for cohort, expected in PINS.items():
        raw = (BASE / cohort / "runs.csv").read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(f"historical {cohort} file changed")
        for row in csv.DictReader(io.StringIO(raw.decode("utf8"), newline="")):
            if (row["mode"], row["pledges"]) == ("consult", "on"):
                seed, year = int(row["seed"]), int(row["year"])
                if year in refs[seed]:
                    raise ValueError("duplicate historical checkpoint")
                refs[seed][year] = {name: row[name] for name in FIELDS}
    if any(set(years) != {50, 100, 200} for years in refs.values()):
        raise ValueError("incomplete PR 18 checkpoint grid")
    return refs, PINS.copy()


def check_seed(job):
    seed, expected = job
    digests = {field: hashlib.sha256() for field in FIELDS}
    checked = []
    years = max(expected)
    path = run(seed, years, policy="A", consult=True, pledges=True)
    for year, (economy, consultations, commitments) in zip(range(1, years + 1), path, strict=True):
        if economy["year"] != year:
            raise ValueError("economic year out of sequence")
        digests[FIELDS[0]].update(canonical_line(economy))
        for name, mode, pairs in ((FIELDS[1], "consult", consultations),
                                  (FIELDS[2], "consult_on", commitments)):
            digests[name].update(canonical_line({
                "mode": mode, "year": year, "pairs": [pairs[key] for key in sorted(pairs)],
            }))
        if year in expected:
            observed = {name: digest.hexdigest() for name, digest in digests.items()}
            if observed != expected[year]:
                raise ValueError(f"PR 18 mismatch at seed {seed}, year {year}")
            checked.append({"seed": seed, "year": year, **observed})
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.workers < 1 or args.out.exists():
        parser.error("specify a positive worker count and a new output path")
    start = perf_counter()
    refs, pins = baseline()
    with ProcessPoolExecutor(max_workers=min(40, args.workers)) as pool:
        checkpoints = [row for group in pool.map(check_seed, refs.items()) for row in group]
    receipt = {
        "base_commit": "0c2c2cb843ff530ee9cf5eaf740d221c3bfbae96",
        "policy": "A", "consult": True, "pledges": True, "input_sha256": pins,
        "world_years": 8000, "checkpoints": checkpoints, "streams_per_checkpoint": len(FIELDS),
        "wall_seconds": round(perf_counter() - start, 3),
    }
    publish_receipt(args.out, receipt)
    print(f"{len(checkpoints)} checkpoints, {len(FIELDS)} streams each, {receipt['wall_seconds']} seconds")


if __name__ == "__main__":
    main()
