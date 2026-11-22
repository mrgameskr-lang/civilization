"""Replay civil consultations using exclusively the settled 6.0B2-D economic paths."""
import argparse
from collections import Counter
from contextlib import ExitStack
import csv
import gzip
import hashlib
from itertools import combinations, groupby
import json
from pathlib import Path
import platform
from tempfile import TemporaryDirectory
import time

from civsim.model import generate_world
from civsim.peace62 import snapshot62, start62
from civsim.regions import regionalize
from civsim.storage import canonical_line
from experiments.phase5a import _sha
from experiments.phase6a import compressed, digest_file, emit


ARCHIVE = Path(__file__).resolve().parents[1] / "examples/phase6b2/study"
HORIZONS = (50, 100, 200)
MODES = ("observe", "consult")
ECONOMIC = ("food_need", "food_eaten", "food_deficit", "closing_population", "closing_cash")
NATIONAL_POSTINGS = (
    ("trade_value", "source", "exports_value"), ("trade_value", "target", "imports_value"),
    ("trade_denied", "source", "trade_denied_out"), ("exit_denied", "source", "exit_denied_out"),
    ("entry_denied", "target", "entry_denied_in"), ("sent", "source", "aid_sent"),
    ("received", "target", "aid_received"), ("cost_food", "source", "aid_freight_food"),
    ("handling_food", "source", "aid_handling_food"), ("migrants", "source", "foreign_out"),
    ("migrants", "target", "foreign_in"),
    *((f"trade_{good}", side, f"foreign_{flow}_{good}")
      for good in ("food", "ore", "tools") for side, flow in (("source", "out"), ("target", "in"))),
)


def check_direction_year(rows, adjacent, nations=8):
    directions = [(int(r["source"]), int(r["target"])) for r in rows]
    if (len(set(directions)) != len(directions)
            or any(not (0 <= a < nations and 0 <= b < nations) or a == b for a, b in directions)):
        raise ValueError("invalid or repeated archived border direction")
    frequency = Counter(tuple(sorted(pair)) for pair in directions)
    if any(frequency[pair] != 2 for pair in adjacent):
        raise ValueError("a physical national border is missing an archived direction")
    return frequency


def audit_national_year(rows, countries):
    """Independently post signed border flows to exporter/importer or donor/recipient."""
    postings = {owner: Counter() for owner in countries}
    for row in rows:
        for field, side, national_key in NATIONAL_POSTINGS:
            postings[int(row[side])][national_key] += int(row[field])
    for owner, national in countries.items():
        for _, _, key in NATIONAL_POSTINGS:
            if int(national[key]) != postings[owner][key]:
                raise ValueError(f"national posting differs from border ledger for {owner}/{key}")


def verify_tables(original, repeat, names):
    block_size = 1024 * 1024
    for name in names:
        with (original/name).open("rb") as first, (repeat/name).open("rb") as second:
            while True:
                block = first.read(block_size)
                if block != second.read(block_size):
                    raise ValueError(f"independent repeat differs in {name}")
                if not block:
                    break


def selected_years(filename):
    with gzip.open(filename, "rt", newline="", encoding="utf8") as stream:
        selected = (r for r in csv.DictReader(stream) if r["arm"] == "D")
        for key, group in groupby(selected, key=lambda r: (int(r["seed"]), int(r["year"]))):
            yield key, list(group)


def archive_grid(root, sample, seeds):
    source = root/sample
    primary = json.loads((source/"execution.json").read_bytes())
    replay = json.loads((root/f"replay-{sample}.json").read_bytes())
    if (primary["sample"] != sample or primary["arms"] != ["C", "D"]
            or primary["horizons"] != list(HORIZONS) or primary["seeds"] != len(seeds)
            or primary["first_seed"] != seeds.start or primary["table_sha256"] != replay["table_sha256"]
            or replay["replayed_checkpoints"] != len(seeds)*2*len(HORIZONS)):
        raise ValueError("6.0B2 original and independent repeat manifest disagree")
    for name, expected in primary["table_sha256"].items():
        if digest_file(source/name) != expected:
            raise ValueError(f"archived bytes changed in {source/name}")
    with (source/"runs.csv").open(encoding="utf8", newline="") as stream:
        historical = [r for r in csv.DictReader(stream) if r["arm"] == "D"]
    grid = {(int(r["seed"]), int(r["year"])): r for r in historical}
    if len(grid) != len(historical) or set(grid) != {(s, y) for s in seeds for y in HORIZONS}:
        raise ValueError("incomplete archived D grid")
    return grid, primary["table_sha256"]


def write_json(path, data):
    with path.open("x", encoding="utf8", newline="\n") as f:
        json.dump(data, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")


def write_table(path, rows):
    with path.open("x", encoding="utf8", newline="") as f:
        writer = emit(f, rows[0], header=True)
        writer.writerows(rows)


COUNTS = ("pair_years", "observed_years", "no_direction_years", "one_direction_years", "two_direction_years",
          "none", "start", "continue", "ease", "unobserved", "active_observed_years", "consulting_years",
          "accepted", "declined", "defer", "no_proposal", "accepted_without_easing")


class StudyPath:
    def __init__(self, seed, mode):
        from civsim.civic_diplomacy63 import CivicDiplomacy
        self.engine = CivicDiplomacy(seed, nations=8, consult=(mode == "consult"))
        self.mode = mode
        self.digest = hashlib.sha256()
        self.previous = {}
        self.totals = {pair: Counter(dict.fromkeys(COUNTS, 0)) for pair in combinations(range(8), 2)}

    def advance(self, year, evidence, stream):
        from civsim.civic_diplomacy63 import audit_civic_pair
        rows = self.engine.advance(year, previous_rows=evidence)
        if set(rows) != set(self.totals):
            raise ValueError("not all 28 pairs were retained")
        record = canonical_line({"mode": self.mode, "year": year, "pairs": [rows[p] for p in sorted(rows)]})
        stream.write(record.decode())
        self.digest.update(record)
        for pair, r in rows.items():
            audit_civic_pair(r, previous_row=self.previous.get(pair))
            t = self.totals[pair]
            n = len(r["evidence"])
            if bool(r["observed"]) != (n == 2):
                raise ValueError("direction count and joint observability differ")
            t[("no_direction_years", "one_direction_years", "two_direction_years")[n]] += 1
            t["pair_years"] += 1
            t["observed_years"] += int(r["observed"])
            t[r["event"]] += 1
            t["active_observed_years"] += int(r["observed"] and r["closing"]["active"])
            t["consulting_years"] += int(r["closing"]["consulting"])
            decision = r["proposal"]["decision"]
            t["no_proposal" if decision == "none" else decision] += 1
            t["accepted_without_easing"] += int(decision == "accepted" and r["event"] != "ease")
        self.previous = rows
        return rows

    def world_totals(self):
        return {key: sum(t[key] for t in self.totals.values()) for key in COUNTS}


FORK_FIELDS = ("seed", "year", "a", "b", "evidence_year", "decision", "held_decision",
               "actual_event", "held_event", "actual_active", "held_active", "actual_consulting", "held_consulting")


def record_forks(consult, held, writer, cases, seed, year, totals):
    for pair in sorted(consult):
        r, alternative = consult[pair], held[pair]
        if any(r[k] != alternative[k] for k in ("opening", "evidence_year", "observed", "evidence")):
            raise ValueError("same-opening intervention changed its input")
        decision = r["proposal"]["decision"]
        same_dispute = r["closing"]["active"] == alternative["closing"]["active"]
        totals["fork_pair_years"] += 1
        totals["fork_active_differences"] += int(not same_dispute)
        totals["fork_consulting_differences"] += int(r["closing"]["consulting"] != alternative["closing"]["consulting"])
        totals["fork_observed"] += int(r["observed"])
        if decision not in ("accepted", "declined") and r["closing"] == alternative["closing"]:
            continue
        entry = {"seed": seed, "year": year, "a": pair[0], "b": pair[1], "evidence_year": r["evidence_year"],
                 "decision": decision, "held_decision": alternative["proposal"]["decision"],
                 "actual_event": r["event"], "held_event": alternative["event"],
                 "actual_active": int(r["closing"]["active"]), "held_active": int(alternative["closing"]["active"]),
                 "actual_consulting": int(r["closing"]["consulting"]), "held_consulting": int(alternative["closing"]["consulting"])}
        writer.writerow(entry)
        cases.setdefault(decision, {"seed": seed, "year": year, "a": pair[0], "b": pair[1],
                                    "consult": r, "hold": alternative})


def seed_result(seed, grid, foreign, national, streams, tables, archive_coverage):
    world = regionalize(generate_world(seed))
    owners = {r.id: r.owner for r in world.regions}
    borders = {tuple(sorted((owners[edge.a], owners[edge.b]))) for edge in world.borders}
    initial_hash = _sha(snapshot62(start62(world)))
    if any(grid[seed, y]["initial_sha256"] != initial_hash for y in HORIZONS):
        raise ValueError(f"archived geography and starting state differ at {seed}")
    paths = {mode: StudyPath(seed, mode) for mode in MODES}
    preceding = []
    economics = Counter()
    forks = Counter(fork_pair_years=0, fork_active_differences=0, fork_consulting_differences=0, fork_observed=0)
    cases = {}
    for year in range(1, 201):
        border_key, rows = next(foreign)
        national_key, nationals = next(national)
        if border_key != (seed, year) or national_key != (seed, year):
            raise ValueError("archived economic panels skipped or duplicated a year")
        countries = {int(r["owner"]): r for r in nationals}
        if len(nationals) != 8 or set(countries) != set(range(8)):
            raise ValueError("archived economics lacks a unique row for every country")
        frequency = check_direction_year(rows, borders)
        for pair in combinations(range(8), 2):
            location = "adjacent" if pair in borders else "nonadjacent"
            archive_coverage[f"{location}_{frequency.get(pair, 0)}_directions"] += 1
        audit_national_year(rows, countries)
        for k in ECONOMIC:
            amount = sum(int(r[k]) for r in nationals)
            if k.startswith("closing_"):
                economics[k] = amount
            else:
                economics[k] += amount
        # The extra fork begins at the actual consultation path's current opening each year.
        same_opening_hold = paths["consult"].engine.fork(consult=False)
        for mode in MODES:
            paths[mode].advance(year, preceding, streams["annual"])
        alternative = same_opening_hold.advance(year, previous_rows=preceding)
        record_forks(paths["consult"].previous, alternative, streams["forks"], cases, seed, year, forks)
        for pair in paths["observe"].previous:
            a, b = (paths[mode].previous[pair] for mode in MODES)
            if (a["evidence"] != b["evidence"] or a["observed"] != b["observed"]):
                raise ValueError("two policy paths used different economic signals")
        preceding = rows
        if year in HORIZONS:
            archived = grid[seed, year]
            if any(int(archived[k]) != economics[k] for k in ECONOMIC):
                raise ValueError(f"archived national and world economics differ at {seed}/{year}")
            for mode, path in paths.items():
                base = {"seed": seed, "mode": mode, "year": year}
                tables["runs"].append({**base, "initial_sha256": initial_hash, "economic_years_sha256": archived["years_sha256"],
                                       "civic_years_sha256": path.digest.hexdigest(), **economics, **path.world_totals()})
                for (a, b), t in path.totals.items():
                    tables["pairs"].append({**base, "a": a, "b": b, "adjacent": int((a,b) in borders), **t,
                                            "closing_active": int(path.previous[a,b]["closing"]["active"]),
                                            "closing_consulting": int(path.previous[a,b]["closing"]["consulting"])})
            tables["fork-checkpoints"].append({"seed": seed, "year": year, **forks})
    tables["cases"].extend(cases.values())


def run_study(output, sample, *, archive=ARCHIVE, verify=None):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    started = time.perf_counter()
    seeds = {"dev": range(20), "holdout": range(20,40)}[sample]
    grid, source_hashes = archive_grid(archive, sample, seeds)
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".civil-consult-", dir=output.parent) as work:
        stage = Path(work, "publication")
        stage.mkdir()
        tables = {k: [] for k in ("runs", "pairs", "fork-checkpoints", "cases")}
        coverage = Counter({f"{geo}_{n}_directions": 0 for geo in ("adjacent","nonadjacent") for n in range(3)})
        with ExitStack() as stack:
            raw = stack.enter_context(compressed(stage/"annual.jsonl.gz"))
            fork = stack.enter_context(compressed(stage/"same-opening.csv.gz"))
            streams = {"annual": raw, "forks": emit(fork, FORK_FIELDS, header=True)}
            src = archive/sample
            foreign = selected_years(src/"foreign-years.csv.gz")
            national = selected_years(src/"country-years.csv.gz")
            stack.callback(foreign.close)
            stack.callback(national.close)
            for seed in seeds:
                seed_result(seed, grid, foreign, national, streams, tables, coverage)
            if next(foreign, None) is not None or next(national, None) is not None:
                raise ValueError("unexpected archived seed or year")
        write_json(stage/"fork-cases.json", tables.pop("cases"))
        for name, rows in tables.items():
            write_table(stage/(name+".csv"), rows)
        write_json(stage/"source.json", {"archive": "phase6b2/D", "sample": sample, "seeds": list(seeds),
                                         "archive_sha256": source_hashes, "source_pair_years": coverage,
                                         "checked_economic_checkpoints": len(grid)})
        hashes = {p.name: digest_file(p) for p in sorted(stage.iterdir())}
        if verify is not None:
            verify_tables(Path(verify), stage, hashes)
        meta = {"sample": sample, "seeds": len(seeds), "horizons": HORIZONS, "economic_world_years": len(seeds)*200,
                "civic_world_years": len(seeds)*200*len(MODES), "fork_pair_years": len(seeds)*200*28,
                "table_sha256": hashes, "verified_files": len(hashes) if verify is not None else 0,
                "replayed_civic_checkpoints": len(tables["runs"]) if verify is not None else 0,
                "python": platform.python_version(), "wall_seconds": time.perf_counter()-started}
        write_json(stage/"execution.json", meta)
        if output.exists():
            raise FileExistsError(output)
        stage.rename(output)
    return meta


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", required=True, choices=("dev","holdout"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verify-against", type=Path)
    args = parser.parse_args()
    print(json.dumps(run_study(args.out, args.sample, verify=args.verify_against)))
