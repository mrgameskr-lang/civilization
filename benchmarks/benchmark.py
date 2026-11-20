"""Print JSON timings and a cProfile summary. Run as python -m benchmarks.benchmark."""

import argparse
import cProfile
import json
import platform
import pstats
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter_ns

from civsim.engine import step
from civsim.model import generate_world
from civsim.storage import write_run


SEED = 42
SCENARIOS = ((48, 32, 8), (96, 64, 8), (48, 32, 32), (96, 64, 32))


def _measure(width, height, nations, years, repeats):
    init_ns = []
    core_ns = []
    end_to_end_ns = []
    sizes = []
    for _ in range(repeats):
        start = perf_counter_ns()
        world = generate_world(SEED, width, height, nations)
        init_ns.append(perf_counter_ns() - start)
        start = perf_counter_ns()
        for year in range(1, years + 1):
            step(world, year)
        core_ns.append(perf_counter_ns() - start)
        del world

        with TemporaryDirectory() as temp:
            output = Path(temp) / "run"
            start = perf_counter_ns()
            write_run(output, seed=SEED, width=width, height=height, nations=nations, years=years)
            end_to_end_ns.append(perf_counter_ns() - start)
            sizes.append(sum(path.stat().st_size for path in output.rglob("*") if path.is_file()))
    return {
        "width": width, "height": height, "nations": nations,
        "init_ms": round(median(init_ns) / 1_000_000, 3),
        "core_ms": round(median(core_ns) / 1_000_000, 3),
        "end_to_end_ms": round(median(end_to_end_ns) / 1_000_000, 3),
        "bytes_persisted": int(median(sizes)),
    }


def _profile(years):
    profiler = cProfile.Profile()
    with TemporaryDirectory() as temp:
        profiler.runcall(write_run, Path(temp) / "run", seed=SEED, width=48,
                         height=32, nations=8, years=years)
    functions = []
    for (filename, line, name), (_, calls, own, cumulative, _) in pstats.Stats(profiler).stats.items():
        # pstats ordinarily includes absolute runtime and workspace paths.
        functions.append({
            "function": f"{Path(filename).name}:{line} {name}", "calls": calls,
            "self_ms": round(own * 1000, 3), "cumulative_ms": round(cumulative * 1000, 3),
        })
    return {
        "width": 48, "height": 32, "nations": 8,
        "by_self_time": sorted(functions, key=lambda row: -row["self_ms"])[:10],
        "by_cumulative_time": sorted(functions, key=lambda row: -row["cumulative_ms"])[:10],
    }


def build_report(repeats=5, years=50):
    if repeats < 1 or years < 1:
        raise ValueError("repeats and years must be positive")
    return {
        "python": platform.python_version(),
        "seed": SEED, "years": years, "repeats": repeats,
        "statistic": "median wall-clock milliseconds; file bytes are logical, uncompressed bytes",
        "scenarios": [_measure(*scenario, years, repeats) for scenario in SCENARIOS],
        "profile": _profile(years),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--years", type=int, default=50)
    args = parser.parse_args()
    if args.repeats < 1 or args.years < 1:
        parser.error("--repeats and --years must be positive")
    print(json.dumps(build_report(args.repeats, args.years), indent=2))


if __name__ == "__main__":
    main()
