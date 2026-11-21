"""5.0D replayable civic archives. The disabled series retains exact 5.0C annual bytes."""
from pathlib import Path
import os

from .collective import collective_snapshot, start_collective, step_collective
from .competition import competition_snapshot
from .model import generate_world
from .regional_storage import _publish, _verify_stream
from .regions import regionalize


def _inputs(meta):
    if (type(meta["enabled"]) is not bool or type(meta["years"]) is not int or meta["years"] < 1):
        raise ValueError("invalid collective run settings")
    world = generate_world(meta["seed"], meta["width"], meta["height"], meta["nations"])
    sim = start_collective(regionalize(world, meta["per_nation"]))
    initial = collective_snapshot(sim) if meta["enabled"] else competition_snapshot(sim.competition)
    return initial, lambda year: step_collective(sim, year, meta["enabled"])


def write_collective_run(directory, *, seed=42, years=50, enabled=True, per_nation=4,
                         width=48, height=32, nations=8):
    directory = Path(directory)
    if os.path.lexists(directory):
        raise FileExistsError(directory)
    meta = {"schema": 1, "model_version": "5.0D", "seed": seed, "years": years, "width": width,
            "height": height, "nations": nations, "per_nation": per_nation, "enabled": enabled}
    _publish(directory, meta, *_inputs(meta))


def verify_collective(directory, meta):
    if (set(meta) != {"schema", "model_version", "seed", "years", "width", "height", "nations",
                      "per_nation", "enabled"} or meta["schema"] != 1 or meta["model_version"] != "5.0D"):
        raise ValueError("invalid 5.0D archive")
    return _verify_stream(directory, meta, *_inputs(meta))
