"""Paired regional farm-tech study on the released annual game, with replayable evidence."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import csv
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from civsim.annual_game import create, load, play
from civsim.chronicle import Chronicle
from civsim.game_journal import new_journal, save_journal
from civsim.storage import canonical_line
from civsim.supply62 import snapshot62


ROOT = Path(__file__).resolve().parents[1]
CHECKPOINTS = (50, 100, 200)
ARMS = ("off", "research")
REASONS = ("already_learned","other_fiscal_choice","urgent_hunger","insufficient_expected_return",
           "paid_trial","project_unfunded")


def digest(value):
    return sha256(canonical_line(value)).hexdigest()


def write_json(path, data):
    path.write_bytes((json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def command_for(arm, year):
    if arm == "research" and year == 1:
        return {"move":None, "research":True}
    if year == 2:
        return {"move":None, "public_farm":True, "reserve_policy":"emergency"}
    return None


def support_counts(groups):
    return (sum(g["members"] * g["support"] for g in groups.values()),
            sum(g["members"] for g in groups.values()))


def choose_cases(rows):
    eligible = [r for r in rows if r["arm"] == "research" and r["year"] == 200 and r["seed"] >= 20]
    fast = min((r for r in eligible if r["first_adoption"]), key=lambda r: (r["first_adoption"], r["seed"], r["owner"]))
    stalled = [r for r in eligible if not r["first_adoption"]]
    if stalled:
        slow = min(stalled, key=lambda r: (-r["trials"], r["seed"], r["owner"]))
    else:
        slow = min(eligible, key=lambda r: (-r["first_adoption"], r["seed"], r["owner"]))
    return fast, slow


def accumulate(row, totals, first):
    regions = {r["id"]: r for r in row["regions"]}
    for r in regions.values():
        account = totals[r["owner"]]
        for good, quantity in r["production"]["produced"].items():
            account[good] += quantity
        account["need"] += r["consumption"]["food_need"]
        account["unmet"] += r["consumption"]["food_unmet"]
    for item in row.get("research", {}).get("regions", []):
        account = totals[item["owner"]]
        for key in ("trial_workers", "trial_ore", "trial_tools"):
            account[key] += item[key]
        account[item["reason"]] += 1
        account["trials"] += item["closing_trials"] - item["opening_trials"]
        if item["level_after"] > item["level_before"]:
            first.setdefault(item["owner"], row["year"])
        prod = regions[item["id"]]["production"]
        account["fixed_inputs_food_gain"] += prod["produced"]["food"] - prod["food_without_tech"]


def country_rows(seed, arm, row, totals, first):
    political = {c["id"]:c for c in row["competition"]["countries"]}
    voters = {c["id"]:[0, 0] for c in row["countries"]}
    for region in row["politics"]["regions"]:
        points, members = support_counts(region["closing"]["groups"])
        voters[region["owner"]][0] += points
        voters[region["owner"]][1] += members
    research = row.get("research", {}).get("regions", ())
    for n in row["countries"]:
        country = n["id"]
        parts = [r for r in row["regions"] if r["owner"] == country]
        cabinet = political[country]
        roll = totals[country]
        support, members = voters[country]
        yield {"seed":seed, "arm":arm, "year":row["year"], "owner":country, "name":n["closing"]["name"],
               "base_technology":n["closing"]["technology"], "regions":len(parts),
               "advanced_regions":sum(t["level_after"] for t in research if t["owner"] == country),
               "first_adoption":first.get(country, 0), "population":n["closing"]["population"],
               "annual_food":sum(r["production"]["produced"]["food"] for r in parts),
               "cabinet":cabinet["governing_faction"], "turnovers":cabinet["closing"]["turnovers"],
               "support_points":support, "represented_members":members,
               **{key:roll[key] for key in ("trials","trial_workers","trial_ore","trial_tools","food","ore","tools",
                                            "need","unmet","fixed_inputs_food_gain",*REASONS)}}


def run_seed(job):
    seed, scratch = job
    folder = scratch / f"seed-{seed}"
    folder.mkdir()
    rows, paths, examples, events = [], [], {}, []
    for arm in ARMS:
        game = create(seed)
        start_hash = digest(snapshot62(game.economy))
        totals = {n.id: Counter() for n in game.economy.world.nations}
        first = {}
        book = Chronicle(seed=seed)
        journal = new_journal(seed)
        for year in range(1, 201):
            command = command_for(arm, year)
            row = play(game, command)
            # play() already normalized this payload to JSON. Reuse one checksum for
            # the portable game journal and the archived baseline comparison.
            journal["turns"].append({"year":year, "command":command, "record_sha256":digest(row)})
            book.observe(row)
            accumulate(row, totals, first)
            if year in CHECKPOINTS:
                rows.extend(country_rows(seed, arm, row, totals, first))
        report = book.report()
        end_hash = digest(snapshot62(game.economy))
        run = {"seed":seed, "arm":arm, "opening_sha256":start_hash, "closing_sha256":end_hash,
               "journal_sha256":digest(journal), "chronicle_sha256":digest(report), "events":len(report["events"])}
        if arm == "off" and seed in (0,20):
            archived = ROOT / "studies/chronicle7/long" / f"seed-{seed}"
            if (json.loads((archived / "save.json").read_bytes())["journal"] != journal
                    or json.loads((archived / "chronicle.json").read_bytes()) != report):
                raise ValueError(f"PR #28 replay diverged on seed {seed}")
            run["archived_years_verified"] = len(journal["turns"])
        if arm == "research":
            save_journal(folder / "save.json", journal)
            if seed in (0, 20):
                repeat = Chronicle(seed=seed)
                _, replay = load(folder / "save.json", observer=repeat)
                if digest(snapshot62(replay.economy)) != end_hash or repeat.report() != report:
                    raise ValueError(f"independent replay differs on seed {seed}")
                run["independently_replayed_years"] = len(journal["turns"])
            for event in report["events"]:
                if event["kind"] == "farm_tech_adoption":
                    application = event.get("application")
                    events.append({"seed":seed, "owner":event["country"], "region":event["region"],
                                   "year":event["year"], "application_year":application["year"] if application else 0,
                                   "record_sha256":event["record_sha256"]})
            for c in totals:
                if sum(e["owner"] == c for e in events) != sum(t["level_after"] for t in row["research"]["regions"] if t["owner"]==c):
                    raise ValueError("chronicle/closing adoption count mismatch")
        for owner in totals:
            group = [e for e in report["events"] if e["country"] == owner]
            examples[f"{arm}-{owner}"] = {
                "events_by_kind":dict(Counter(e["kind"] for e in group)),
                "first_advance":next((e for e in group if e["kind"]=="farm_tech_adoption"),None),
                "first_other":next((e for e in group if e["kind"]!="farm_tech_adoption"),None)}
        paths.append(run)
    if paths[0]["opening_sha256"] != paths[1]["opening_sha256"]:
        raise ValueError("paired economies have different initial worlds")
    write_json(folder / "metrics.json", {"rows":rows, "paths":paths, "events":events, "examples":examples})
    return seed


def aggregate(out, scratch):
    bundles = [json.loads((scratch / f"seed-{seed}" / "metrics.json").read_bytes()) for seed in range(40)]
    rows = [r for b in bundles for r in b["rows"]]
    events = [r for b in bundles for r in b["events"]]
    write_csv(out / "countries.csv", rows)
    write_csv(out / "adoptions.csv", events)
    write_json(out / "trajectories.json", [r for b in bundles for r in b["paths"]])
    (out / "saves").mkdir()
    for seed in range(40):
        (scratch / f"seed-{seed}" / "save.json").rename(out / "saves" / f"seed-{seed}.json")
    cases = []
    for chosen in choose_cases(rows):
        seed, owner = chosen["seed"], chosen["owner"]
        cases.append({"seed":seed, "owner":owner,
            "checkpoints":[r for r in rows if r["seed"]==seed and r["owner"]==owner],
            "chronicles":{arm:bundles[seed]["examples"][f"{arm}-{owner}"] for arm in ARMS}})
    write_json(out / "cases.json", cases)
    means = []
    for start in (0, 20):
        for year in CHECKPOINTS:
            worlds = []
            for seed in range(start, start+20):
                groups = {arm:[r for r in rows if r["seed"]==seed and r["year"]==year and r["arm"]==arm] for arm in ARMS}
                def total(arm, key):
                    return sum(r[key] for r in groups[arm])
                delta = {k:total("research",k)-total("off",k) for k in ("food","population","unmet","need","turnovers")}
                rates = {arm:total(arm,"unmet")/total(arm,"need") for arm in ARMS}
                worlds.append({"seed":seed, **delta, "shortage_rate_delta":rates["research"]-rates["off"],
                               "advanced_regions":total("research","advanced_regions"),
                               "advanced_nations":sum(bool(r["first_adoption"]) for r in groups["research"]),
                               **{k:total("research",k) for k in ("trial_workers","trial_tools","trial_ore","fixed_inputs_food_gain")}})
            means.append({"sample":"development" if start==0 else "validation", "year":year,
                          "paired":worlds, "mean":{k:sum(w[k] for w in worlds)/len(worlds) for k in worlds[0] if k!="seed"},
                          "population_higher":sum(w["population"]>0 for w in worlds),
                          "population_lower":sum(w["population"]<0 for w in worlds),
                          "shortage_rate_higher":sum(w["shortage_rate_delta"]>0 for w in worlds)})
    write_json(out / "paired.json", means)


def study(out, workers):
    if out.exists() or workers < 1:
        raise ValueError("use a new output directory and a positive worker count")
    out.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=out.parent) as tmp:
        scratch = Path(tmp)
        start = perf_counter()
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for seed in pool.map(run_seed, [(i, scratch) for i in range(40)]):
                print(f"seed {seed} compared", flush=True)
        result = scratch / "result"
        result.mkdir()
        aggregate(result, scratch)
        write_json(result / "execution.json", {"worlds":40, "arms":list(ARMS), "years":200, "workers":workers,
                    "steps":16000, "independent_research_replay_steps":400, "seconds":round(perf_counter()-start,3)})
        result.rename(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("smoke","study"))
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)
    if args.action == "study":
        study(args.out, args.workers)
    else:
        from experiments.research71_fork import smoke
        if args.out.exists():
            raise FileExistsError(args.out)
        args.out.parent.mkdir(parents=True,exist_ok=True)
        write_json(args.out, smoke())


if __name__ == "__main__":
    main()
