"""Publish two ledgers, their Korean chronicles and an independent citation audit."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from civsim.annual_game import create, load, play, save
from civsim.chronicle import Chronicle, render_highlights, render_markdown
from civsim.game_journal import append_turn, new_journal
from civsim.storage import canonical_line
from civsim.supply62 import snapshot62


SEEDS = (0, 20)


def digest(value):
    return sha256(canonical_line(value)).hexdigest()


class CitationCheck:
    """Look up published scalar values directly in independently replayed JSON rows."""

    def __init__(self, events):
        self.events_by_year = defaultdict(list)
        for event in events:
            self.events_by_year[event["year"]].append(event)
        self.events_checked = 0
        self.values_checked = 0

    def observe(self, row):
        events = self.events_by_year.get(row["year"], ())
        if not events:
            return
        checksum = digest(row)
        for event in events:
            if checksum != event["record_sha256"] or not event["evidence"]:
                raise ValueError(f"missing or incorrect source for year {row['year']}")
            for citation in event["evidence"].values():
                source = row
                pointer = citation["pointer"]
                if not pointer.startswith("/"):
                    raise ValueError(f"expected an absolute JSON Pointer: {pointer}")
                for token in pointer[1:].split("/"):
                    token = token.replace("~1", "/").replace("~0", "~")
                    source = source[int(token)] if isinstance(source, list) else source[token]
                if isinstance(source, (dict, list)) or canonical_line(source) != canonical_line(citation["value"]):
                    raise ValueError(f"citation differs at year {row['year']} {pointer}")
                self.values_checked += 1
            self.events_checked += 1


def write_report(path, report):
    """Keep the metadata and each individual event readable in a line-based diff."""
    def encode(value):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)

    fields = [f"  {encode(k)}: {encode(report[k])}" for k in sorted(report) if k != "events"]
    entries = ",\n".join("    " + encode(event) for event in report["events"])
    fields.append('  "events": [\n' + entries + '\n  ]')
    path.write_bytes(("{\n" + ",\n".join(fields) + "\n}\n").encode("utf-8"))


def run_world(folder, seed, years):
    folder.mkdir()
    # Control: generate the original annual-game save without running any chronicle code.
    game, journal = create(seed), new_journal(seed)
    for year in range(1, years + 1):
        command = {"move": None, "public_farm": True, "reserve_policy": "emergency"} if year == 2 else None
        row = play(game, command)
        journal = append_turn(journal, command, row)
    closing = digest(snapshot62(game.economy))
    slot = folder / "save.json"
    save(slot, journal, game.away, game.economy.game_upkeep,
         public_farm=game.economy.public_farm, reserve_policy=game.economy.reserve_policy)

    # load() starts a fresh world, replays the commands and checks every annual row against the control.
    first = Chronicle(seed=seed)
    _, replay = load(slot, observer=first)
    report = first.report()
    if digest(snapshot62(replay.economy)) != closing:
        raise ValueError("first observer replay diverged from the unobserved closing state")

    repeat = Chronicle(seed=seed)
    audit = CitationCheck(report["events"])
    _, replay = load(slot, observers=(audit, repeat))
    repeated = repeat.report()
    if digest(snapshot62(replay.economy)) != closing or canonical_line(report) != canonical_line(repeated):
        raise ValueError("independent repeat diverged")
    if audit.events_checked != len(report["events"]):
        raise ValueError("published event refers to a year outside the replayed game")
    write_report(folder / "chronicle.json", report)
    (folder / "chronicle.md").write_bytes(render_markdown(report).encode("utf-8"))
    (folder / "highlights.md").write_bytes(render_highlights(report).encode("utf-8"))
    # Remove the seed and full-row hashes from the cross-world comparison, retaining witnessed facts.
    facts = [{k: v for k, v in event.items() if k != "record_sha256"} for event in report["events"]]
    return {
        "seed": seed, "years": years, "annual_rows_verified_per_replay": len(journal["turns"]),
        "observer_replays": 2, "closing_state_sha256_all_three_runs": closing,
        "journal_sha256": digest(journal), "chronicle_sha256": digest(report),
        "repeat_chronicle_sha256": digest(repeated), "facts_without_record_hashes_sha256": digest(facts),
        "candidates": report["candidates"], "events_checked": audit.events_checked,
        "cited_values_checked": audit.values_checked,
        "selected_by_kind": dict(sorted(Counter(event["kind"] for event in report["events"]).items())),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True, help="fresh result directory")
    args = parser.parse_args(argv)
    if args.years < 1 or args.out.exists():
        parser.error("use a positive year count and a new output directory")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=args.out.parent) as scratch:
        staged = Path(scratch) / "results"
        staged.mkdir()
        worlds = []
        for seed in SEEDS:
            start = perf_counter()
            result = run_world(staged / f"seed-{seed}", seed, args.years)
            print(f"seed={seed} years={args.years} events={result['events_checked']} "
                  f"citations={result['cited_values_checked']} seconds={perf_counter() - start:.1f}", flush=True)
            worlds.append(result)
        different = worlds[0]["facts_without_record_hashes_sha256"] != worlds[1]["facts_without_record_hashes_sha256"]
        if not different or any(not w["events_checked"] for w in worlds):
            raise ValueError("these worlds did not produce two distinct nonempty chronicles")
        summary = {"worlds": worlds, "different_selected_facts": different,
                   "policy": "existing annual game; public harvest and emergency relief from year 2; no player moves"}
        (staged / "verification.json").write_bytes(
            (json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        )
        staged.rename(args.out)


if __name__ == "__main__":
    main()
