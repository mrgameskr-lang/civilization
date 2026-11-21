"""Export every country-year from paths verified against the phase 5D primary journals."""
import argparse
import csv
import gzip
import hashlib
import io
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from civsim.collective import start_collective, step_collective
from civsim.collective_rules import ACTIVE
from civsim.model import GOODS, generate_world
from civsim.regions import regionalize
from civsim.storage import canonical_line


def panel(job):
    seed, arm, hashes = job
    sim = start_collective(regionalize(generate_world(seed)))
    rows = []
    digest = hashlib.sha256()
    for year in range(1, 201):
        row = step_collective(sim, year, arm == "on")
        digest.update(canonical_line(row))
        if year in hashes and digest.hexdigest() != hashes[year]:
            raise ValueError(f"primary journal mismatch at {seed}/{arm}/{year}")
        context = row.get("collective", {})
        responses = {r["id"]: r for r in context.get("responses", [])}
        for country, cabinet in zip(row["countries"], row["competition"]["countries"], strict=True):
            owner = country["id"]
            if owner != cabinet["id"]:
                raise ValueError("cabinet owner mismatch")
            regions = [r for r in row["regions"] if r["owner"] == owner]
            groups = [g for r in context.get("regions", []) if r["owner"] == owner for g in r["groups"].values()]
            levies = [r for r in row["government"]["levies"] if r["owner"] == owner]
            needs = sum(r["consumption"]["food_need"] for r in regions)
            unmet = sum(r["consumption"]["food_unmet"] for r in regions)
            response = responses.get(owner)
            rows.append({"seed": seed, "arm": arm, "year": year, "owner": owner,
                         "opening_population": country["opening"]["population"],
                         "closing_population": country["closing"]["population"], "food_need": needs,
                         "food_unmet": unmet, "deficit_share": unmet/needs if needs else "",
                         **{g+"_output": sum(r["production"]["produced"][g] for r in regions) for g in GOODS},
                         "incumbent": cabinet["governing_faction"], "turnover": int(cabinet["election"]["turnover"]),
                         "active_groups": sum(g["action"] in ACTIVE for g in groups),
                         "participants": sum(g["participants"] for g in groups),
                         "withheld_workers": sum(g["withheld_workers"] for g in groups),
                         "response": response["kind"] if response else "",
                         "approval_changed": int(bool(response and response["before"] != response["after"])),
                         **{field+"_"+good: sum(l[field][good] if field in l else 0 for l in levies)
                            for field in ("levied", "refused", "foregone_concession") for good in GOODS}})
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", choices=("dev", "holdout"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output already exists")
    base = Path(__file__).resolve().parents[1] / "examples/phase5d/study" / args.sample
    paths = {}
    with (base/"runs.csv").open(encoding="utf-8", newline="") as source:
        for r in csv.DictReader(source):
            paths.setdefault((int(r["seed"]), r["arm"]), {})[int(r["year"])] = r["years_sha256"]
    if len(paths) != 40 or any(set(h) != {50, 100, 200} for h in paths.values()):
        raise ValueError("incomplete reference series")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=args.out.parent) as tmp:
        archive = Path(tmp)/"country-years.csv.gz"
        with ProcessPoolExecutor(max_workers=args.workers) as pool, archive.open("wb") as raw:
            with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as gz:
                with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                    writer = None
                    for rows in pool.map(panel, [(s, a, h) for (s, a), h in sorted(paths.items())]):
                        if writer is None:
                            writer = csv.DictWriter(text, fieldnames=tuple(rows[0]), lineterminator="\n")
                            writer.writeheader()
                        writer.writerows(rows)
        if args.out.exists():
            raise FileExistsError(args.out)
        archive.rename(args.out)
    print(f"{len(paths)*8*200} country-years; {len(paths)*3} primary digests matched")
