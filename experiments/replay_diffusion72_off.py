"""Recompute the 40 archived research-off, diffusion-off histories from seed."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path

from civsim.annual_game import create, play
from civsim.chronicle import Chronicle
from civsim.game_journal import append_turn, new_journal
from civsim.supply62 import snapshot62
from .research71 import CHECKPOINTS, ROOT, command_for, digest


def replay(prior):
    seed = prior["seed"]
    game = create(seed)
    history = Chronicle(seed=seed)
    journal = new_journal(seed)
    opening = digest(snapshot62(game.economy))
    for year in range(1, CHECKPOINTS[-1] + 1):
        command = command_for("off", year)
        row = play(game, command)
        if row["year"] != year or "research" in row or "diffusion" in row:
            raise ValueError(f"unexpected year or active research policy on seed {seed}, year {year}")
        journal = append_turn(journal, command, row)
        history.observe(row)
    report = history.report()
    actual = {"opening_sha256": opening, "closing_sha256": digest(snapshot62(game.economy)),
              "journal_sha256": digest(journal), "chronicle_sha256": digest(report),
              "events": len(report["events"])}
    for key, value in actual.items():
        if value != prior[key]:
            raise ValueError(f"seed {seed} differs from archived research-off {key}")
    return {"seed": seed, "years": len(journal["turns"]), **actual}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=5)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    prior_path = ROOT / "studies/research71/long/trajectories.json"
    records = sorted((r for r in json.loads(prior_path.read_bytes()) if r["arm"] == "off"),
                     key=lambda row: row["seed"])
    if [r["seed"] for r in records] != list(range(40)):
        raise ValueError("expected exactly one research-off reference for every seed from 0 to 39")
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        worlds = []
        for result in pool.map(replay, records):
            worlds.append(result)
            print(f"seed {result['seed']}: 200 years match", flush=True)
    output = {"reference": prior_path.relative_to(ROOT).as_posix(), "arm": "off",
              "world_years": sum(r["years"] for r in worlds), "worlds": worlds}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(output, stream, sort_keys=True, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
