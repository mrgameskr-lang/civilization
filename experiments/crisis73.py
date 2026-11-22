"""Paired 7.2 control and optional civilian border crisis, from identical opening worlds."""
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
from experiments.diffusion72 import command_for as legacy
from experiments.research71 import CHECKPOINTS, ROOT, digest, support_counts, write_csv, write_json


ARMS = ("diffusion", "crisis")
STAGES = ("start", "escalate", "ease", "resolve")
RESPONSES = ("inactive", "no_new_harm", "not_mutual", "hold", "staffed")
CRISIS = (*STAGES, "active_pair_years", "level1_pair_years", "level2_pair_years", *RESPONSES,
          "workers", "goods_released", "people_released")
FLOWS = ("quantity", "migrants", "trade_denied", "migration_denied_exit", "migration_denied_entry",
         "agreement_breach", "aid_received", "trade_value", "trade_freight", "pacts_started")
ECONOMY = ("food", "ore", "tools", "unmet", "need")
STOCKS = ("population", "advanced_regions", "turnovers", "public_food", "members", "support_points",
          "annual_food", "chronicle_events", "adjacent_tension_sum", "adjacent_trust_sum")
DIGEST_FIELDS = ("opening_sha256", "closing_sha256", "journal_sha256", "chronicle_sha256")


def command_for(arm, year):
    if arm not in ARMS:
        raise ValueError(f"unknown study arm {arm}")
    command = legacy("diffusion", year)
    if arm == "crisis" and year == 1:
        command["crisis"] = True
    return command


def one_year(row):
    """One pair once; two directed freight ledgers; food/persons/cash never summed together."""
    crisis = {(p["a"], p["b"]): p for p in row.get("crisis", {}).get("pairs", [])}
    counts = Counter()
    pairs = {}
    for p in row["diplomacy"]["pairs"]:
        key = p["a"], p["b"]
        pair = Counter()
        for flow in p["flows"]["directions"]:
            pair["quantity"] += sum(flow["goods"].values())
            for metric in FLOWS[1:-1]:
                pair[metric] += flow[metric]
        pair["pacts_started"] = int(p["policy"]["agreement_started"])
        response = crisis.get(key)
        if response is not None:
            transition = response["transition"]
            if transition in STAGES:
                pair[transition] += 1
            elif transition != "none":
                raise ValueError(f"unrecognized transition {transition}")
            level = response["closing_level"]
            if level not in (0, 1, 2) or response["response"] not in RESPONSES:
                raise ValueError("unknown crisis level or response")
            pair["active_pair_years"] = int(level > 0)
            pair["level1_pair_years"] = int(level == 1)
            pair["level2_pair_years"] = int(level == 2)
            pair[response["response"]] += 1
            for field in ("workers", "goods_released", "people_released"):
                pair[field] = int(response[field])
        pairs[key] = pair
        counts.update(pair)
    for region in row["regions"]:
        counts.update(region["production"]["produced"])
        counts["unmet"] += region["consumption"]["food_unmet"]
        counts["need"] += region["consumption"]["food_need"]
    return counts, pairs


COUNTRY = ("eligible_pair_years", "selected_pair_years", "staffed_years", "workers",
           "food", "need", "unmet", "exports", "emigrants")


def add_countries(row, totals):
    for region in row["regions"]:
        acc = totals[region["owner"]]
        acc["food"] += region["production"]["produced"]["food"]
        acc["need"] += region["consumption"]["food_need"]
        acc["unmet"] += region["consumption"]["food_unmet"]
    for pair in row["diplomacy"]["pairs"]:
        for flow in pair["flows"]["directions"]:
            totals[flow["source"]]["exports"] += sum(flow["goods"].values())
            totals[flow["source"]]["emigrants"] += flow["migrants"]
    for pair in row.get("crisis", {}).get("pairs", ()):
        for choice in pair["choices"]:
            acc = totals[choice["country"]]
            acc["eligible_pair_years"] += int(choice["eligible"])
            acc["selected_pair_years"] += int(choice["selected"])
            acc["staffed_years"] += int(pair["staffed"])
            acc["workers"] += int(pair["staffed"])  # one worker at this country's endpoint


def country_checkpoint(common, row, totals):
    support = defaultdict(Counter)
    for region in row["politics"]["regions"]:
        points, members = support_counts(region["closing"]["groups"])
        support[region["owner"]].update(support_points=points, members=members)
    cabinets = {c["id"]: c for c in row["competition"]["countries"]}
    for c in row["countries"]:
        owner = c["id"]
        yield {**common, "country": owner, "population": c["closing"]["population"],
               **{k: totals[owner][k] for k in COUNTRY}, **support[owner],
               "turnovers": cabinets[owner]["closing"]["turnovers"], "cabinet": cabinets[owner]["governing_faction"]}


def year_end(row):
    votes = [support_counts(region["closing"]["groups"]) for region in row["politics"]["regions"]]
    borders = [pair["closing"] for pair in row["diplomacy"]["pairs"] if pair["adjacent"]]
    return dict(population=sum(r["closing"]["population"] for r in row["countries"]),
                public_food=sum(r["closing"]["food"] for r in row["government"]["depots"]),
                advanced_regions=sum(r["level_after"] for r in row["research"]["regions"]),
                turnovers=sum(c["closing"]["turnovers"] for c in row["competition"]["countries"]),
                annual_food=sum(r["production"]["produced"]["food"] for r in row["regions"]),
                support_points=sum(p for p, _ in votes), members=sum(m for _, m in votes),
                adjacent_tension_sum=sum(p["tension"] for p in borders),
                adjacent_trust_sum=sum(p["trust"] for p in borders))


def paired_worlds(rows, metrics=(*ECONOMY, *FLOWS, *CRISIS, *STOCKS)):
    worlds = defaultdict(dict)
    for r in rows:
        both = worlds[r["seed"], r["year"]]
        if r["arm"] in both:
            raise ValueError("duplicate arm")
        both[r["arm"]] = r
    results = []
    for (seed, year), both in sorted(worlds.items()):
        if set(both) != set(ARMS):
            raise ValueError("unpaired world")
        a, b = (both[arm] for arm in ARMS)
        results.append({"seed": seed, "year": year, "cohort": "development" if seed < 20 else "validation",
                        **{name: b[name] - a[name] for name in metrics},
                        "shortage_rate_delta": b["unmet"]/b["need"] - a["unmet"]/a["need"],
                        "support_delta": b["support_points"]/b["members"] - a["support_points"]/a["members"]})
    return results


def run_seed(job):
    seed, folder, archived = job
    folder.mkdir()
    worlds, pairs, events, paths, countries = [], [], [], [], []
    for arm in ARMS:
        game = create(seed)
        opening = digest(snapshot62(game.economy))
        journal, book = new_journal(seed), Chronicle(seed)
        total, totals, national = Counter(), defaultdict(Counter), defaultdict(Counter)
        for year in range(1, 201):
            command = command_for(arm, year)
            row = play(game, command)
            record_hash = digest(row)
            journal["turns"].append({"year": year, "command": command, "record_sha256": record_hash})
            book.observe(row)
            year_total, year_pairs = one_year(row)
            add_countries(row, national)
            total.update(year_total)
            for key, facts in year_pairs.items():
                totals[key].update(facts)
            for idx, p in enumerate(row.get("crisis", {}).get("pairs", [])):
                if p["transition"] in STAGES:
                    events.append({"seed": seed, "year": year, "a": p["a"], "b": p["b"],
                                   "transition": p["transition"], "opening": p["opening_level"],
                                   "closing": p["closing_level"], "evidence_year": p["evidence_year"],
                                   "prior_trade_denied": p["trade_denied"], "prior_people_denied": p["people_denied"],
                                   "prior_breaches": p["breaches"], "workers": p["workers"],
                                   "record_sha256": record_hash, "pointer": f"/crisis/pairs/{idx}/transition"})
            if year in CHECKPOINTS:
                book_report = book.report()
                common = dict(seed=seed, arm=arm, year=year)
                countries.extend(country_checkpoint(common, row, national))
                worlds.append({**common, **{key: total[key] for key in (*ECONOMY, *FLOWS, *CRISIS)},
                               **year_end(row), "chronicle_events": len(book_report["events"])})
                for p in row["diplomacy"]["pairs"]:
                    key = p["a"], p["b"]
                    pairs.append({**common, "a": key[0], "b": key[1], "adjacent": int(p["adjacent"]),
                                  **{metric: totals[key][metric] for metric in (*FLOWS, *CRISIS)},
                                  **{metric: p["closing"][metric] for metric in ("tension", "trust", "relation")}})
        path = {"seed": seed, "arm": arm, "opening_sha256": opening, "journal_sha256": digest(journal),
                "closing_sha256": digest(snapshot62(game.economy)), "chronicle_sha256": digest(book_report),
                "events": len(book_report["events"])}
        if arm == "diffusion":
            previously = ROOT / "studies/diffusion72/long/saves" / f"seed-{seed}.json"
            if (any(path[k] != archived[k] for k in (*DIGEST_FIELDS, "events"))
                    or json.loads(previously.read_bytes()) != journal):
                raise ValueError(f"archived 7.2 outcome differs, seed {seed}")
            path["archived_years_verified"] = 200
        else:
            save = folder / "save.json"
            save_journal(save, journal)
            if seed in (0, 20):
                observer = Chronicle(seed)
                repeated, restored = load(save, observer=observer)
                if (repeated != journal or digest(snapshot62(restored.economy)) != path["closing_sha256"]
                        or digest(observer.report()) != path["chronicle_sha256"]):
                    raise ValueError(f"independent replay differs, seed {seed}")
                path["independently_replayed_years"] = 200
        paths.append(path)
    if paths[0]["opening_sha256"] != paths[1]["opening_sha256"]:
        raise ValueError(f"unmatched starting worlds, seed {seed}")
    write_json(folder / "metrics.json", {"worlds": worlds, "pairs": pairs, "countries": countries,
                                          "events": events, "paths": paths})
    return seed


def study(out, workers):
    if out.exists() or workers < 1:
        raise ValueError("use a fresh output directory and a positive worker count")
    start = perf_counter()
    archived = {p["seed"]: p for p in json.loads((ROOT / "studies/diffusion72/long/trajectories.json").read_bytes())
                if p["arm"] == "diffusion"}
    if set(archived) != set(range(40)):
        raise ValueError("missing PR #30 control trajectories")
    out.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=out.parent) as scratch_dir:
        scratch = Path(scratch_dir)
        jobs = [(seed, scratch / f"seed-{seed}", archived[seed]) for seed in range(40)]
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for seed in pool.map(run_seed, jobs):
                print(f"paired seed {seed} verified", flush=True)
        combined = defaultdict(list)
        result = scratch / "results"
        (result / "saves").mkdir(parents=True)
        for seed, folder, _ in jobs:
            for key, value in json.loads((folder / "metrics.json").read_bytes()).items():
                combined[key].extend(value)
            (folder / "save.json").rename(result / "saves" / f"seed-{seed}.json")
        for key in ("worlds", "pairs", "countries", "events"):
            write_csv(result / f"{key}.csv", combined[key])
        write_json(result / "trajectories.json", combined["paths"])
        write_json(result / "paired.json", paired_worlds(combined["worlds"]))
        write_json(result / "execution.json", {"primary_world_years": 16_000, "independent_world_years": 400,
                   "workers": workers, "seconds": round(perf_counter()-start, 3)})
        result.rename(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("smoke", "study"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    from .crisis73_fork import smoke
    if args.out.exists():
        raise FileExistsError(args.out)
    proof = smoke()
    if args.action == "smoke":
        args.out.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.out, proof)
    else:
        study(args.out, args.workers)


if __name__ == "__main__":
    main()
