"""Portable UTF-8 run files, streamed annual replay and atomic publication."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from .audit import audit
from .engine import step
from .model import generate_world
from .rules import LEGACY, Rules


SCHEMA = 1


def canonical_line(value):
    """Canonical UTF-8 ledger bytes shared by persisted runs and experiment digests."""
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def write_run(directory: Path, *, seed=42, width=48, height=32, nations=8, years=50,
              rules: Rules = LEGACY):
    """Write and validate a run in a sibling staging directory, then publish once."""
    directory = Path(directory)
    if directory.exists():
        raise FileExistsError(f"run already exists: {directory}")
    if type(years) is not int or years < 1:
        raise ValueError("years must be a positive integer")
    world = generate_world(seed, width, height, nations)
    manifest = {"schema": SCHEMA, "model_version": rules.version, "years": years,
                "seed": seed, "width": width, "height": height, "nations": nations}
    if rules != LEGACY:
        manifest["rules"] = {"labor": rules.labor, "order": list(rules.order)}
        if rules.investment != "off":
            manifest["rules"]["investment"] = rules.investment
        if rules.policy31 != "off":
            manifest["rules"]["policy31"] = rules.policy31
    directory.parent.mkdir(exist_ok=True, parents=True)
    with TemporaryDirectory(dir=directory.parent, prefix=".civsim-") as scratch:
        staging = Path(scratch) / "run"
        staging.mkdir()
        (staging / "manifest.json").write_bytes(canonical_line(manifest))
        (staging / "world.json").write_bytes(canonical_line(asdict(world)))
        with (staging / "years.jsonl").open("wb") as file:
            for year in range(1, years + 1):
                file.write(canonical_line(step(world, year, rules)))
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


def _replay_rules(meta):
    version = meta.get("model_version")
    if version == LEGACY.version:
        if "rules" in meta:
            raise ValueError("legacy manifest cannot contain a rules override")
        return LEGACY
    if version not in ("2.0", "3.0", "3.1"):
        raise ValueError(f"incompatible model version for replay: {version!r}")
    config = meta.get("rules")
    required = {"labor", "order"}
    if version in ("3.0", "3.1"):
        required.add("investment")
    if version == "3.1":
        required.add("policy31")
    if not isinstance(config, dict) or set(config) != required:
        raise ValueError(f"version {version} rule keys must be {sorted(required)}")
    order = config["order"]
    if not isinstance(config["labor"], str) or not isinstance(order, list) or not all(
        isinstance(good, str) for good in order
    ):
        raise ValueError("invalid rule types; expected a labor string and an array of goods")
    rules = Rules(labor=config["labor"], order=tuple(order), investment=config.get("investment", "off"),
                  policy31=config.get("policy31", "off"))
    if rules.version != version:
        raise ValueError("rules do not match model version")
    return rules


def verify_run(directory):
    """Audit stored ledgers, regenerate the map and every trace, return exact file SHA-256."""
    path = Path(directory)
    meta = _manifest(path)
    if meta.get("model_version") == "6.0A":
        from .diplomacy_storage import verify_diplomacy
        return verify_diplomacy(path, meta)
    if meta.get("model_version") == "5.0D":
        from .collective_storage import verify_collective
        return verify_collective(path, meta)
    if meta.get("model_version") == "5.0C":
        from .competition_storage import verify_competition
        return verify_competition(path, meta)
    if meta.get("model_version") == "5.0B":
        from .political_storage import verify_political
        return verify_political(path, meta)
    if meta.get("model_version") == "5.0A":
        from .fiscal_storage import verify_government
        return verify_government(path, meta)
    if meta.get("model_version") == "4.0":
        from .regional_storage import verify_regional
        return verify_regional(path, meta)
    rules = _replay_rules(meta)
    world = generate_world(meta["seed"], meta["width"], meta["height"], meta["nations"])
    initial = json.loads((path / "world.json").read_bytes())
    if canonical_line(initial) != canonical_line(asdict(world)):
        raise ValueError("year 0: initial world differs from seed")
    digest = hashlib.sha256()
    for row in _rows(path, meta["years"], digest):
        year = row["year"]
        try:
            audit(row)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"year {year}: {error}") from error
        if canonical_line(step(world, year, rules)) != canonical_line(row):
            raise ValueError(f"year {year}: recorded inputs or results differ from replay")
    return digest.hexdigest()

