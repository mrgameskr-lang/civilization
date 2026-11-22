"""Summarize matched paths and retain the examples picked by explicit extrema."""
import argparse
import csv
from collections import defaultdict
import json
from pathlib import Path
from statistics import mean

from .crisis73 import ARMS, CHECKPOINTS, CRISIS, ECONOMY, FLOWS, STOCKS
from .research71 import write_json


def table(path, labels):
    with path.open(encoding="utf-8", newline="") as source:
        return [{k: (v if k in labels else int(v)) for k, v in row.items()} for row in csv.DictReader(source)]


def summarize(folder):
    world = table(folder / "worlds.csv", {"arm"})
    pairs = table(folder / "pairs.csv", {"arm"})
    paired = json.loads((folder / "paired.json").read_bytes())
    events = table(folder / "events.csv", {"transition", "record_sha256", "pointer"})
    blocks = []
    for start in (0, 20):
        for year in CHECKPOINTS:
            def selected(rows):
                return [r for r in rows if r["year"] == year and start <= r["seed"] < start+20]
            delta = selected(paired)
            sample = selected(world)
            bilateral = [p for p in selected(pairs) if p["arm"] == "crisis" and p["adjacent"]]
            by_arm = {arm: {k: sum(r[k] for r in sample if r["arm"] == arm) for k in
                            (*CRISIS, *ECONOMY, *FLOWS, *STOCKS)} for arm in ARMS}
            active = [r for r in sample if r["arm"] == "crisis"]
            episodes = defaultdict(list)
            for event in events:
                if start <= event["seed"] < start+20 and event["year"] <= year:
                    episodes[event["seed"], event["a"], event["b"]].append(event)
            completed, censored = [], []
            for series in episodes.values():
                onset = None
                for event in series:
                    if event["transition"] == "start":
                        if onset is not None:
                            raise ValueError("overlapping crisis episodes")
                        onset = event["year"]
                    if event["transition"] == "resolve":
                        if onset is None:
                            raise ValueError("crisis resolved without an onset")
                        completed.append(event["year"] - onset)
                        onset = None
                if onset is not None:
                    censored.append(year-onset+1)
            if sum(completed)+sum(censored) != by_arm["crisis"]["active_pair_years"]:
                raise ValueError("episode durations disagree with observed active border years")
            counts = {k: dict(higher=sum(d[k] > 0 for d in delta), lower=sum(d[k] < 0 for d in delta),
                              equal=sum(d[k] == 0 for d in delta)) for k in
                      ("population", "food", "shortage_rate_delta", "quantity", "migrants", "turnovers", "support_delta")}
            blocks.append({"cohort": "development" if start == 0 else "validation", "year": year,
                           "arm_totals": by_arm, "paired_mean": {k: mean(d[k] for d in delta)
                           for k in delta[0] if k not in ("seed", "cohort", "year")}, "world_directions": counts,
                           "adjacent_pairs": len(bilateral), "pairs_never_active": sum(not p["start"] for p in bilateral),
                           "pairs_active_without_staff": sum(p["start"] > 0 and p["staffed"] == 0 for p in bilateral),
                           "pairs_staffed_without_grants": sum(p["staffed"] > 0 and not p["goods_released"] and
                                                               not p["people_released"] for p in bilateral),
                           "worlds_without_crisis": [r["seed"] for r in active if not r["start"]],
                           "worlds_without_desk": [r["seed"] for r in active if not r["staffed"]],
                           "completed_episodes": len(completed), "ongoing_episodes": len(censored),
                           "mean_completed_duration": mean(completed) if completed else None,
                           "longest_completed": max(completed, default=0),
                           "largest_population_loss": min(delta, key=lambda d: (d["population"], d["seed"])),
                           "largest_population_gain": max(delta, key=lambda d: (d["population"], -d["seed"]))})
    return blocks


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    options = parser.parse_args()
    if options.out.exists():
        raise FileExistsError(options.out)
    write_json(options.out, summarize(options.folder))
