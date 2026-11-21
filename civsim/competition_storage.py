"""Versioned 5.0C snapshots and full annual economic and political journals."""
import os
from pathlib import Path

from .competition import _options, competition_snapshot, start_competition, step_competition
from .model import generate_world
from .regional_storage import _publish, _verify_stream
from .regions import regionalize


def _run(meta):
    _options(meta["arm"], meta["tax_policy"])
    if type(meta["years"]) is not int or meta["years"] < 1:
        raise ValueError("years must be a positive integer")
    initial = generate_world(meta["seed"], meta["width"], meta["height"], meta["nations"])
    return start_competition(regionalize(initial, meta["per_nation"]))


def write_competition_run(directory, *, seed=42, years=50, arm="C", tax_policy="fixed",
                          per_nation=4, width=48, height=32, nations=8):
    directory = Path(directory)
    if os.path.lexists(directory):
        raise FileExistsError(directory)
    meta = {"schema": 1, "model_version": "5.0C", "seed": seed, "years": years, "width": width,
            "height": height, "nations": nations, "per_nation": per_nation, "arm": arm, "tax_policy": tax_policy}
    sim = _run(meta)
    _publish(directory, meta, competition_snapshot(sim), lambda year: step_competition(sim, year, arm, tax_policy))


def verify_competition(directory, meta):
    fields = {"schema", "model_version", "seed", "years", "width", "height", "nations", "per_nation",
              "arm", "tax_policy"}
    if set(meta) != fields or meta["schema"] != 1 or meta["model_version"] != "5.0C":
        raise ValueError("invalid 5.0C archive")
    sim = _run(meta)
    return _verify_stream(directory, meta, competition_snapshot(sim),
                          lambda year: step_competition(sim, year, meta["arm"], meta["tax_policy"]))
