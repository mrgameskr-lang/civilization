"""Archive 5.0B runs, including shadow-only observation of 5.0A."""
import os
from pathlib import Path

from .model import generate_world
from .politics import political_snapshot, start_political, step_political
from .regional_storage import _publish, _verify_stream
from .regions import regionalize


def _simulation(meta):
    if type(meta["feedback"]) is not bool or type(meta["years"]) is not int or meta["years"] < 1:
        raise ValueError("invalid political feedback or year count")
    initial = generate_world(meta["seed"], meta["width"], meta["height"], meta["nations"])
    return start_political(regionalize(initial, meta["per_nation"]))


def write_political_run(directory, *, seed=42, years=50, feedback=True, per_nation=4,
                        width=48, height=32, nations=8):
    directory = Path(directory)
    if os.path.lexists(directory):
        raise FileExistsError(directory)
    meta = {"schema": 1, "model_version": "5.0B", "seed": seed, "years": years, "width": width,
            "height": height, "nations": nations, "per_nation": per_nation, "feedback": feedback}
    sim = _simulation(meta)
    _publish(directory, meta, political_snapshot(sim), lambda y: step_political(sim, y, feedback))


def verify_political(directory, meta):
    fields = {"schema", "model_version", "seed", "years", "width", "height", "nations", "per_nation", "feedback"}
    if set(meta) != fields or meta["schema"] != 1 or meta["model_version"] != "5.0B":
        raise ValueError("invalid 5.0B archive")
    sim = _simulation(meta)
    return _verify_stream(directory, meta, political_snapshot(sim), lambda y: step_political(sim, y, meta["feedback"]))
