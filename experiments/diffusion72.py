"""Paired domestic-migration knowledge study, preserving all 7.1 baseline hashes."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from civsim.annual_game import create, load, play
from civsim.chronicle import Chronicle
from civsim.game_journal import new_journal, save_journal
from civsim.supply62 import snapshot62
from experiments import research71
from experiments.research71 import CHECKPOINTS, ROOT, digest, write_csv, write_json


ARMS = ("research", "diffusion")
EXTRA = ("domestic_shipments", "border_exports", "domestic_migrants", "contacts",
         "transfers", "independent", "transfer_fixed_inputs_food_gain")
METRICS = ("population", "annual_food", "food", "unmet", "need", "turnovers", "advanced_regions",
           "trials", "trial_workers", "trial_tools", "trial_ore", "fixed_inputs_food_gain",
           "chronicle_events", *EXTRA)
KINDS = ("farm_knowledge_contact", "farm_tech_transfer", "farm_tech_adoption")


def command_for(arm, year):
    command = research71.command_for("research", year)
    if arm == "diffusion" and year == 1:
        command["diffusion"] = True
    return command


def record_economy(row, totals, regional):
    research = {r["id"]: r for r in row["research"]["regions"]}
    tech = {r["id"]: r for r in row.get("diffusion", {}).get("regions", [])}
    for shipment in row["domestic"]["shipments"]:
        totals[research[shipment["source"]]["owner"]]["domestic_shipments"] += shipment["quantity"]
    for sale in row["border_market"]["trades"]:
        totals[research[sale["seller"]]["owner"]]["border_exports"] += sale["quantity"]
    for move in row["moves"]:
        source, target = research[move["source"]], research[move["target"]]
        if source["owner"] == target["owner"]:
            totals[target["owner"]]["domestic_migrants"] += move["people"]
            account = regional[target["id"]]
            account["domestic_arrivals"] += move["people"]
            account["domestic_receipts"] += 1
            if source["level_before"] and not target["level_after"]:
                account["qualified_receipts"] += 1
    for region in row["regions"]:
        i = region["id"]
        account, local = totals[region["owner"]], regional[i]
        trial, memory = research[i], tech.get(i, {})
        if memory.get("new_contact"):
            account["contacts"] += 1
        if trial["level_before"] != trial["level_after"]:
            key = "transfers" if memory.get("closing_method") == "transfer" else "independent"
            account[key] += 1
        if memory.get("opening_method") == "transfer":
            production = region["production"]
            account["transfer_fixed_inputs_food_gain"] += production["produced"]["food"] - production["food_without_tech"]
        local["paid_trials"] += trial["closing_trials"] - trial["opening_trials"]


def region_rows(seed, arm, row, regional):
    knowledge = {r["id"]: r for r in row.get("diffusion", {}).get("regions", ())}
    for trial in row["research"]["regions"]:
        i = trial["id"]
        memory = knowledge.get(i, {})
        contact = memory.get("closing_contact") or {}
        count = regional[i]
        yield {"seed": seed, "arm": arm, "year": row["year"], "owner": trial["owner"], "region": i,
               **{k: count[k] for k in ("domestic_arrivals", "domestic_receipts", "qualified_receipts", "paid_trials")},
               "first_contact": contact.get("year", 0), "source": contact.get("source", ""),
               "method": memory.get("closing_method") or ("independent" if trial["level_after"] else ""),
               "adoption_year": trial["adoption_year"] or 0, "level": trial["level_after"]}


def event_row(seed, arm, event):
    contact = event if event["kind"] == "farm_knowledge_contact" else event.get("contact") or {}
    facts = contact.get("evidence", {})
    application = event.get("application") or {}
    production = application.get("evidence", {})
    return {"seed": seed, "arm": arm, "year": event["year"], "owner": event["country"],
            "region": event["region"], "kind": event["kind"], "record_sha256": event["record_sha256"],
            "contact_year": contact.get("year", ""), "contact_sha256": contact.get("record_sha256", ""),
            "source": facts.get("source", {}).get("value", ""), "people": facts.get("people", {}).get("value", ""),
            "receipt_pointer": facts.get("people", {}).get("pointer", ""),
            "application_year": application.get("year", ""), "application_sha256": application.get("record_sha256", ""),
            "food": production.get("food_produced", {}).get("value", ""),
            "food_without_tech": production.get("food_without_tech", {}).get("value", "")}


def run_seed(job):
    seed, folder, archived = job
    folder.mkdir()
    countries, regions, events, paths = [], [], [], []
    for arm in ARMS:
        game = create(seed)
        opening = digest(snapshot62(game.economy))
        journal, book = new_journal(seed), Chronicle(seed=seed)
        totals, regional, first = defaultdict(Counter), defaultdict(Counter), {}
        for year in range(1, CHECKPOINTS[-1] + 1):
            command = command_for(arm, year)
            row = play(game, command)
            journal["turns"].append({"year": year, "command": command, "record_sha256": digest(row)})
            book.observe(row)
            research71.accumulate(row, totals, first)
            record_economy(row, totals, regional)
            if year in CHECKPOINTS:
                report = book.report()
                headlines = Counter(e["country"] for e in report["events"])
                for item in research71.country_rows(seed, arm, row, totals, first):
                    owner = item["owner"]
                    countries.append({**item, **{k: totals[owner][k] for k in EXTRA},
                                      "chronicle_events": headlines[owner]})
                regions.extend(region_rows(seed, arm, row, regional))
        events.extend(event_row(seed, arm, e) for e in report["events"] if e["kind"] in KINDS)
        path = {"seed": seed, "arm": arm, "opening_sha256": opening,
                "closing_sha256": digest(snapshot62(game.economy)), "journal_sha256": digest(journal),
                "chronicle_sha256": digest(report), "events": len(report["events"])}
        if arm == "research":
            for key, expected in archived.items():
                if key in path and expected != path[key]:
                    raise ValueError(f"PR #29 {key} differs at seed {seed}")
            path["archived_years_verified"] = len(journal["turns"])
        else:
            save = folder / "save.json"
            save_journal(save, journal)
            if seed in (0, 20):
                repeat = Chronicle(seed=seed)
                second, restored = load(save, observer=repeat)
                if (second != journal or digest(snapshot62(restored.economy)) != path["closing_sha256"]
                        or digest(repeat.report()) != path["chronicle_sha256"]):
                    raise ValueError(f"independent replay differs at seed {seed}")
                path["independently_replayed_years"] = len(second["turns"])
        paths.append(path)
    if paths[0]["opening_sha256"] != paths[1]["opening_sha256"]:
        raise ValueError(f"unequal initial worlds at seed {seed}")
    write_json(folder / "metrics.json", dict(countries=countries, regions=regions, events=events, paths=paths))
    return seed


def worlds_paired(countries, metrics=METRICS):
    sums = defaultdict(lambda: defaultdict(Counter))
    for r in countries:
        counts = sums[r["seed"], r["year"]][r["arm"]]
        for k in (*metrics, "support_points", "represented_members"):
            counts[k] += r[k]
    rows = []
    for (seed, year), arms in sorted(sums.items()):
        base, enabled = (arms[a] for a in ARMS)
        if not base or not enabled:
            raise ValueError("missing paired arm")
        row = {"seed": seed, "year": year, "cohort": "development" if seed < 20 else "validation",
               **{k: enabled[k] - base[k] for k in metrics}}
        for key, numerator, denominator in (("shortage_rate_delta", "unmet", "need"),
                                             ("support_delta", "support_points", "represented_members")):
            row[key] = enabled[numerator] / enabled[denominator] - base[numerator] / base[denominator]
        rows.append(row)
    return rows


def study(out, workers):
    if out.exists() or workers < 1:
        raise ValueError("use a fresh output directory and at least one worker")
    start = perf_counter()
    archived_rows = json.loads((ROOT / "studies/research71/long/trajectories.json").read_bytes())
    archived = {r["seed"]: r for r in archived_rows if r["arm"] == "research"}
    if set(archived) != set(range(40)):
        raise ValueError("missing archived PR #29 baselines")
    out.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=out.parent) as tmp:
        scratch = Path(tmp)
        jobs = [(seed, scratch / f"seed-{seed}", archived[seed]) for seed in range(40)]
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for seed in pool.map(run_seed, jobs):
                print(f"seed {seed} verified", flush=True)
        combined = defaultdict(list)
        result = scratch / "result"
        (result / "saves").mkdir(parents=True)
        for seed, folder, _ in jobs:
            for key, values in json.loads((folder / "metrics.json").read_bytes()).items():
                combined[key].extend(values)
            (folder / "save.json").rename(result / "saves" / f"seed-{seed}.json")
        for name in ("countries", "regions", "events"):
            write_csv(result / f"{name}.csv", combined[name])
        write_json(result / "trajectories.json", combined["paths"])
        write_json(result / "paired.json", worlds_paired(combined["countries"]))
        write_json(result / "execution.json", {"workers": workers, "seconds": round(perf_counter() - start, 3),
                   "primary_world_years": 40 * 2 * 200, "independent_world_years": 2 * 200})
        result.rename(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    quick = actions.add_parser("smoke")
    quick.add_argument("--out", type=Path, required=True)
    runner = actions.add_parser("study")
    runner.add_argument("--out", type=Path, required=True)
    runner.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    from experiments.diffusion72_fork import smoke
    # Each invocation proves a real migration and paid adoption before longer experiments.
    if args.action == "smoke":
        result = smoke()
        args.out.parent.mkdir(parents=True, exist_ok=True)
        if args.out.exists():
            raise FileExistsError(args.out)
        write_json(args.out, result)
    else:
        smoke()
        study(args.out, args.workers)


if __name__ == "__main__":
    main()
