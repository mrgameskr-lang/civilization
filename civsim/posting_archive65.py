"""Write and replay a fixed-world annual register of nominal peacetime affiliations."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from experiments.publication import publish_file

from .posting_engine65 import run
from .storage import canonical_line


def manifest(seed, years):
    if type(seed) is not int or type(years) is not int or years < 1:
        raise ValueError("expected an integer seed and a positive number of years")
    return {
        "schema": "m1-register/1",
        "base_revision": "0c2c2cb843ff530ee9cf5eaf740d221c3bfbae96",
        "policy": "B",
        "semantics": "registered_assignment",
        "seed": seed,
        "years": years,
    }


def annual_lines(header):
    years = header["years"]
    path = run(header["seed"], years, policy="B")
    for year, (economy, _, register) in zip(range(1, years + 1), path, strict=True):
        if economy["year"] != year or register is None:
            raise ValueError(f"missing economic year or annual register at {year}")
        yield canonical_line({
            "year": year,
            "economic_sha256": hashlib.sha256(canonical_line(economy)).hexdigest(),
            "register": register,
        })


def write(output, *, seed, years):
    output = Path(output)
    if os.path.lexists(output):
        raise FileExistsError(output)
    header = manifest(seed, years)
    output.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with TemporaryDirectory(dir=output.parent) as scratch:
        staged = Path(scratch) / "register.jsonl"
        with staged.open("xb") as stream:
            first = canonical_line(header)
            stream.write(first)
            digest.update(first)
            for line in annual_lines(header):
                stream.write(line)
                digest.update(line)
        publish_file(staged, output)
    return digest.hexdigest()


def verify(path):
    with Path(path).open("rb") as stream:
        first = stream.readline()
        header = json.loads(first)
        if not isinstance(header, dict):
            raise ValueError("expected an archive header")
        expected = manifest(header.get("seed"), header.get("years"))
        if first != canonical_line(expected):
            raise ValueError("unrecognized archive schema, policy, revision or encoding")
        digest = hashlib.sha256(first)
        for year, line in enumerate(annual_lines(expected), 1):
            if line != stream.readline():
                raise ValueError(f"year {year} differs from replay")
            digest.update(line)
        if stream.read(1):
            raise ValueError("unexpected additional data")
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("write")
    create.add_argument("--out", required=True, type=Path)
    create.add_argument("--seed", required=True, type=int)
    create.add_argument("--years", required=True, type=int)
    commands.add_parser("verify").add_argument("archive", type=Path)
    args = parser.parse_args()
    if args.command == "write":
        print(write(args.out, seed=args.seed, years=args.years))
    else:
        print(verify(args.archive))


if __name__ == "__main__":
    main()
