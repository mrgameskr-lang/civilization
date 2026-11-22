"""Re-execute published 200-year archives with the 7.3 crisis switch absent."""
import argparse
import json
from pathlib import Path

from civsim.annual_game import load
from civsim.chronicle import Chronicle
from civsim.supply62 import snapshot62
from .replay_diffusion72_legacy import replay as replay_old
from .research71 import ROOT, digest


def replay(studies):
    old = replay_old(studies)
    folder = studies / "diffusion72/long"
    archives = json.loads((folder / "trajectories.json").read_bytes())
    for seed in (0, 20):
        expected = next(t for t in archives if t["seed"] == seed and t["arm"] == "diffusion")
        history = Chronicle(seed)
        journal, world = load(folder / "saves" / f"seed-{seed}.json", observer=history)
        report = history.report()
        actual = {"seed": seed, "arm": "diffusion", "journal_sha256": digest(journal),
                  "chronicle_sha256": digest(report), "closing_sha256": digest(snapshot62(world.economy)),
                  "events": len(report["events"])}
        if report["years"] != 200 or len(journal["turns"]) != 200 or any(
            actual[k] != expected[k] for k in actual
        ):
            raise ValueError(f"PR #30 archived trajectory differs for seed {seed}")
        actual["annual_hashes_verified"] = len(journal["turns"])
        old.append(actual)
    return old


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    value = json.dumps(replay(ROOT / "studies"), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("x", encoding="utf-8", newline="\n") as f:
            f.write(value)
    else:
        print(value, end="")


if __name__ == "__main__":
    main()
