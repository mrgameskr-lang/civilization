"""Reconcile zero-year geographic partitions to the published national generator."""
import argparse
import csv
import hashlib
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from civsim.model import GOODS, generate_world
from civsim.regions import audit_geography, audit_regions, regionalize
from civsim.storage import canonical_line
from experiments.publication import publish_file


def check_world(seed):
    country_world = generate_world(seed)
    spatial = regionalize(country_world)
    audit_geography(spatial)
    audit_regions(spatial)
    for original in country_world.nations:
        local = [r for r in spatial.regions if r.owner == original.id]
        for field in ("population", "land", "cash", "deposit"):
            if sum(getattr(r, field) for r in local) != getattr(original, field):
                raise ValueError(f"seed {seed}, nation {original.id}: incorrect {field}")
        for good in GOODS:
            if sum(r.stock[good] for r in local) != original.stock[good]:
                raise ValueError(f"seed {seed}, nation {original.id}: incorrect {good}")
    return {"seed": seed, "initial_world_sha256": hashlib.sha256(canonical_line(asdict(country_world))).hexdigest(),
            "regional_world_sha256": hashlib.sha256(canonical_line(asdict(spatial))).hexdigest(),
            "countries": len(spatial.nations), "regions": len(spatial.regions), "tiles": len(spatial.tiles),
            "farmland": sum(r.farmland for r in spatial.regions), "domestic_roads": len(spatial.roads),
            "border_roads": len(spatial.borders), "population": sum(r.population for r in spatial.regions),
            "deposit": sum(r.deposit for r in spatial.regions), "cash": sum(r.cash for r in spatial.regions),
            **{g: sum(r.stock[g] for r in spatial.regions) for g in GOODS}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=40)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.seeds < 1:
        parser.error("seed count must be positive")
    if args.out.exists():
        raise FileExistsError(args.out)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=args.out.parent) as stage:
        table = Path(stage, "regions.csv")
        with table.open("x", encoding="utf-8", newline="") as stream:
            writer = None
            for seed in range(args.seeds):
                row = check_world(seed)
                if writer is None:
                    writer = csv.DictWriter(stream, fieldnames=list(row))
                    writer.writeheader()
                writer.writerow(row)
        publish_file(table, args.out)
    print(f"{args.seeds} regional worlds reconciled with original national endowments")


if __name__ == "__main__":
    main()
