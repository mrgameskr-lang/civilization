"""Versioned, replayable 5.0A fiscal runs with the same spatial archive format as 4.0."""
import os
from pathlib import Path

from .fiscal_policy import MODES
from .government import fiscal_snapshot, start_government, step_government
from .model import generate_world
from .regional_storage import _publish, _verify_stream
from .regions import regionalize


def _simulation(meta):
    if meta["policy"] not in MODES or type(meta["years"]) is not int or meta["years"] < 1:
        raise ValueError("invalid public policy or year count")
    return start_government(regionalize(generate_world(meta["seed"], meta["width"], meta["height"],
                                                       meta["nations"]), meta["per_nation"]))


def write_government_run(directory, *, seed=42, years=50, width=48, height=32, nations=8, per_nation=4,
                         policy="integrated"):
    directory = Path(directory)
    if os.path.lexists(directory):
        raise FileExistsError(directory)
    meta = {"schema": 1, "model_version": "5.0A", "seed": seed, "years": years, "width": width,
            "height": height, "nations": nations, "per_nation": per_nation, "policy": policy}
    sim = _simulation(meta)
    _publish(directory, meta, fiscal_snapshot(sim), lambda year: step_government(sim, year, policy))


def verify_government(directory, meta):
    keys = {"schema", "model_version", "seed", "years", "width", "height", "nations", "per_nation", "policy"}
    if set(meta) != keys or meta["schema"] != 1 or meta["model_version"] != "5.0A":
        raise ValueError("invalid fiscal manifest")
    sim = _simulation(meta)
    return _verify_stream(directory, meta, fiscal_snapshot(sim),
                          lambda year: step_government(sim, year, meta["policy"]))
