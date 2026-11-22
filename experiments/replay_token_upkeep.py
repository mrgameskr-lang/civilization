"""Recompute fresh games and compare uncompressed ledgers and per-seed published results."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import gzip
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from civsim.storage import canonical_line
from experiments.token_upkeep_case import case
from experiments.token_upkeep_study import run_seed


def verify(root):
    start = perf_counter()
    cases = {}
    with TemporaryDirectory() as tmp:
        current = Path(tmp)/"case"
        case(current)
        case_dir = root/"case"
        if {p.name for p in current.iterdir()} != {p.name for p in case_dir.iterdir()}:
            raise ValueError("different short game inventory")
        for p in sorted(current.iterdir()):
            reference = (case_dir/p.name).read_bytes()
            fresh = p.read_bytes()
            if p.suffix == ".gz":
                reference, fresh = gzip.decompress(reference), gzip.decompress(fresh)
            if reference != fresh:
                raise ValueError(f"case replay differs: {p.name}")
            cases[p.name] = sha256(fresh).hexdigest()
    seeds = {}
    with ProcessPoolExecutor(max_workers=2) as pool:
        for result in pool.map(run_seed,(0,20)):
            name = f"seed-{result['seed']:02}.json"
            fresh = canonical_line(result)
            if fresh != (root/"study"/name).read_bytes():
                raise ValueError(f"200-year replay differs: {name}")
            seeds[name] = sha256(fresh).hexdigest()
    return {"case_payloads":cases, "seed_files":seeds, "years":200, "arms_per_seed":3,
            "seconds":round(perf_counter()-start,3), "completed_utc":datetime.now(timezone.utc).isoformat()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    parser.add_argument("--out",type=Path,required=True)
    args = parser.parse_args()
    data = verify(args.root)
    with args.out.open("xb") as f:
        f.write(canonical_line(data))
    print(data)
