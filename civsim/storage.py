"""Portable UTF-8 run files, streamed annual replay and atomic publication."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from . import MODEL_VERSION
from .audit import audit
from .engine import step
from .model import generate_world


SCHEMA = 1


def _line(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def write_run(directory: Path, *, seed=42, width=48, height=32, nations=8, years=50):
    """Write and validate a run in a sibling staging directory, then publish once."""
    directory = Path(directory)
    if directory.exists():
        raise FileExistsError(f"run already exists: {directory}")
    if type(years) is not int or years < 1:
        raise ValueError("years must be a positive integer")
    world = generate_world(seed, width, height, nations)
    manifest = {"schema": SCHEMA, "model_version": MODEL_VERSION, "years": years,
                "seed": seed, "width": width, "height": height, "nations": nations}
    directory.parent.mkdir(exist_ok=True, parents=True)
    with TemporaryDirectory(dir=directory.parent, prefix=".civsim-") as scratch:
        staging = Path(scratch) / "run"
        staging.mkdir()
        (staging / "manifest.json").write_bytes(_line(manifest))
        (staging / "world.json").write_bytes(_line(asdict(world)))
        with (staging / "years.jsonl").open("wb") as file:
            for year in range(1, years + 1):
                file.write(_line(step(world, year)))
        staging.rename(directory)


def _manifest(directory):
    manifest = json.loads((directory / "manifest.json").read_bytes())
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise ValueError("unsupported run schema")
    if type(manifest.get("years")) is not int or manifest["years"] < 1:
        raise ValueError("invalid year count")
    return manifest


def _rows(directory, years, digest=None):
    count = 0
    with (directory / "years.jsonl").open("rb") as file:
        for count, line in enumerate(file, 1):
            if digest is not None:
                digest.update(line)
            row = json.loads(line)
            if not isinstance(row, dict) or row.get("year") != count or count > years:
                raise ValueError(f"unexpected year at row {count}")
            yield row
    if count != years:
        raise ValueError(f"expected {years} years, found {count}")


def read_years(directory):
    """Stream a run in order. Validate completeness when the iterator is exhausted."""
    path = Path(directory)
    yield from _rows(path, _manifest(path)["years"])


def verify_run(directory):
    """Audit stored ledgers, regenerate the map and every trace, return exact file SHA-256."""
    path = Path(directory)
    meta = _manifest(path)
    if meta.get("model_version") != MODEL_VERSION:
        raise ValueError("incompatible model version for replay")
    world = generate_world(meta["seed"], meta["width"], meta["height"], meta["nations"])
    initial = json.loads((path / "world.json").read_bytes())
    if _line(initial) != _line(asdict(world)):
        raise ValueError("year 0: initial world differs from seed")
    digest = hashlib.sha256()
    for row in _rows(path, meta["years"], digest):
        year = row["year"]
        try:
            audit(row)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"year {year}: {error}") from error
        if _line(step(world, year)) != _line(row):
            raise ValueError(f"year {year}: recorded inputs or results differ from replay")
    return digest.hexdigest()

