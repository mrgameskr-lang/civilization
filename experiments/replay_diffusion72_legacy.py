"""Replay archived 7.0 and 7.1 saves against their original, published digests."""
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from civsim.annual_game import load
from civsim.chronicle import Chronicle, render_highlights, render_markdown
from civsim.supply62 import snapshot62
from .chronicle7 import write_report
from .research71 import ROOT, digest


def replay(studies):
    trajectories = json.loads((studies / "research71/long/trajectories.json").read_bytes())
    results = []
    for seed in (0, 20):
        for arm in ("off", "research"):
            archived = next(item for item in trajectories if item["seed"] == seed and item["arm"] == arm)
            directory = studies / "chronicle7/long" / f"seed-{seed}"
            save = (directory / "save.json" if arm == "off" else
                    studies / "research71/long/saves" / f"seed-{seed}.json")
            book = Chronicle(seed=seed)
            journal, game = load(save, observer=book)
            report = book.report()
            if report["years"] != 200 or len(journal["turns"]) != 200:
                raise ValueError(f"incomplete archive: {save}")
            checked = {"seed": seed, "arm": arm, "journal_sha256": digest(journal),
                       "chronicle_sha256": digest(report), "closing_sha256": digest(snapshot62(game.economy)),
                       "events": len(report["events"])}
            if not all(archived[key] == value for key, value in checked.items()):
                raise ValueError(f"archived trajectory mismatch: {save}")
            checked["annual_hashes_verified"] = len(journal["turns"])
            if arm == "off":
                with TemporaryDirectory() as temporary:
                    regenerated = Path(temporary) / "report.json"
                    write_report(regenerated, report)
                    products = {"chronicle.json": regenerated.read_bytes(),
                                "chronicle.md": render_markdown(report).encode(),
                                "highlights.md": render_highlights(report).encode()}
                for name, payload in products.items():
                    if payload != (directory / name).read_bytes():
                        raise ValueError(f"archived chronicle differs: {directory / name}")
                checked["files_verified_byte_for_byte"] = list(products)
            results.append(checked)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="create a new verification file, or print to stdout")
    args = parser.parse_args()
    results = replay(ROOT / "studies")
    text = json.dumps(results, indent=2, sort_keys=True) + "\n"
    if args.out is None:
        print(text, end="")
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)


if __name__ == "__main__":
    main()
