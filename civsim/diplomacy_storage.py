"""6.0A archives with deterministic replay and a byte-compatible 5.0D control."""
from pathlib import Path
import os

from .collective import collective_snapshot
from .diplomacy import ARMS, diplomacy_snapshot, start_diplomacy, step_diplomacy
from .model import generate_world
from .regional_storage import _publish, _verify_stream
from .regions import regionalize


def _inputs(meta):
    arm, years = meta["arm"], meta["years"]
    if arm not in ARMS or type(years) is not int or years < 1:
        raise ValueError("invalid diplomatic run settings")
    world = generate_world(meta["seed"], meta["width"], meta["height"], meta["nations"])
    sim = start_diplomacy(regionalize(world, meta["per_nation"]))
    initial = collective_snapshot(sim.collective) if arm == "A" else diplomacy_snapshot(sim)
    return initial, lambda year: step_diplomacy(sim, year, arm)


def write_diplomacy_run(directory, *, seed=42, years=50, arm="D", per_nation=4, width=48, height=32, nations=8):
    directory = Path(directory)
    if os.path.lexists(directory):
        raise FileExistsError(directory)
    meta = {"schema": 1, "model_version": "6.0A", "seed": seed, "years": years, "width": width,
            "height": height, "nations": nations, "per_nation": per_nation, "arm": arm}
    _publish(directory, meta, *_inputs(meta))


def verify_diplomacy(directory, meta):
    if (set(meta) != {"schema", "model_version", "seed", "years", "width", "height", "nations",
                      "per_nation", "arm"} or meta["schema"] != 1 or meta["model_version"] != "6.0A"):
        raise ValueError("invalid 6.0A archive")
    return _verify_stream(directory, meta, *_inputs(meta))
