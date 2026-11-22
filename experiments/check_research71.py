"""Independently reconcile published 7.1 ledgers, country tables and paired summaries."""
import argparse
from collections import Counter, defaultdict
import csv
from hashlib import sha256
from itertools import product
import json
from pathlib import Path
import re

from civsim.annual_game import create
from civsim.storage import canonical_line
from civsim.supply62 import snapshot62


SEEDS = range(40)
ARMS = ("off", "research")
YEARS = (50, 100, 200)
REASONS = ("paid_trial", "already_learned", "other_fiscal_choice", "urgent_hunger",
           "project_unfunded", "insufficient_expected_return")
COSTS = ("trial_workers", "trial_ore", "trial_tools")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_bytes())


def csv_rows(path, labels):
    with path.open(encoding="utf-8", newline="") as stream:
        return [{key: value if key in labels else int(value) for key, value in row.items()}
                for row in csv.DictReader(stream)]


def indexed(rows, fields, expected):
    result = {tuple(r[f] for f in fields): r for r in rows}
    require(len(rows) == len(result) and set(result) == set(expected), f"unexpected or duplicate {fields}")
    return result


def check_adoption(event, turns, owners):
    y = event["year"]
    require(0 < y <= len(turns) and owners.get(event["region"]) == event["owner"],
            "adoption outside recorded years or region ownership")
    require(event["record_sha256"] == turns[y-1]["record_sha256"], "adoption source hash differs")
    require(event["application_year"] == (y+1 if y < len(turns) else 0), "invalid first application year")


def check_country(row, adoption_years):
    recorded = [y for y in adoption_years if y <= row["year"]] if row["arm"] == "research" else []
    learned = len(recorded)
    require(row["first_adoption"] == min(recorded, default=0) and row["advanced_regions"] == learned,
            "milestone register disagrees with country levels")
    require(row["already_learned"] == sum(row["year"] - y for y in recorded),
            "post-adoption region-years differ from the policy reason ledger")
    trials = row["trials"]
    partial = trials - 2 * learned
    require(0 <= partial <= row["regions"] - learned, "incomplete trial stock is inconsistent")
    require([row[k] for k in COSTS] == [2*trials, trials, trials] and row["paid_trial"] == trials,
            "paid trial costs differ from cumulative worker-years/materials")
    count = row["year"] * row["regions"] if row["arm"] == "research" else 0
    require(sum(row[k] for k in REASONS) == count and min(row[k] for k in REASONS) >= 0,
            "research reasons do not partition the observed region-years")
    require(0 <= row["unmet"] <= row["need"] and 0 <= row["annual_food"] <= row["food"]
            and 0 <= row["fixed_inputs_food_gain"] <= row["food"]
            and 0 <= row["support_points"] <= 1000*row["represented_members"],
            "invalid food or representative support totals")
    if not learned:
        require(row["fixed_inputs_food_gain"] == 0, "food gain without an acquired technique")


def check_comparisons(directory, countries):
    comparisons = read(directory / "paired.json")
    blocks = indexed(comparisons, ("sample", "year"), product(("development","validation"), YEARS))
    for (sample, year), block in blocks.items():
        seeds = range(20) if sample == "development" else range(20,40)
        pairs = indexed(block["paired"], ("seed",), ((s,) for s in seeds))
        for seed in seeds:
            sums = {}
            for arm in ARMS:
                rows = [countries[seed, arm, year, c] for c in range(8)]
                sums[arm] = Counter()
                for r in rows:
                    sums[arm].update({k: r[k] for k in
                                      ("food","population","unmet","need","turnovers","advanced_regions",
                                       "fixed_inputs_food_gain",*COSTS)})
                    sums[arm]["advanced_nations"] += int(r["advanced_regions"] > 0)
            off, on = sums["off"], sums["research"]
            actual = pairs[seed,]
            for k in ("population","food","need","unmet","turnovers"):
                require(actual[k] == on[k]-off[k], f"incorrect paired {k} in {seed}, {year}")
            for k in ("advanced_regions","advanced_nations","fixed_inputs_food_gain",*COSTS):
                require(actual[k] == on[k], f"incorrect policy total {k} in {seed}, {year}")
            rate = on["unmet"]/on["need"] - off["unmet"]/off["need"]
            require(actual["shortage_rate_delta"] == rate, "incorrect paired shortage rate")
        require(block["mean"].keys() == pairs[seeds[0],].keys() - {"seed"}, "sample means omit paired indicators")
        for key, mean in block["mean"].items():
            require(sum(pairs[s,][key] for s in seeds)/len(seeds) == mean, f"incorrect sample mean for {key}")
        for field, key, direction in (("population_higher","population",1), ("population_lower","population",-1),
                                      ("shortage_rate_higher","shortage_rate_delta",1)):
            require(block[field] == sum(direction*p[key] > 0 for p in pairs.values()), f"incorrect {field}")
    return len(comparisons)


def check_cases(directory, countries, adopters, journals):
    eligible = [countries[s, "research", 200, c] for s, c in product(range(20,40), range(8))]
    advanced = [r for r in eligible if r["advanced_regions"]]
    stalled = [r for r in eligible if not r["advanced_regions"]]
    first = min(advanced, key=lambda r: (r["first_adoption"], r["seed"], r["owner"]))
    last = min(stalled or eligible, key=lambda r: (-(r["trials"] if stalled else r["first_adoption"]),
                                                   r["seed"], r["owner"]))
    cases = read(directory / "cases.json")
    expect = [(r["seed"],r["owner"]) for r in (first,last)]
    indexed(cases, ("seed","owner"), expect)
    for case in cases:
        seed, owner = case["seed"], case["owner"]
        sample = indexed(case["checkpoints"], ("arm","year"), product(ARMS, YEARS))
        for (arm, year), row in sample.items():
            require(row == countries[seed, arm, year, owner], "selected case differs from country raw data")
        for arm in ARMS:
            book = case["chronicles"][arm]
            actual = adopters[seed, owner] if arm == "research" else []
            require(book["events_by_kind"].get("farm_tech_adoption", 0) == len(actual), "case milestone count differs")
            event = book["first_advance"]
            require((event is not None) == bool(actual), "case has missing or spurious first advancement")
            if event:
                y = min(r["year"] for r in actual)
                require(event["country"] == owner and event["kind"] == "farm_tech_adoption" and event["year"] == y
                        and event["record_sha256"] == journals[seed][y-1]["record_sha256"]
                        and any(r["region"] == event["region"] and r["year"] == y for r in actual),
                        "case first advancement evidence differs from the journal")
                applied = event["application"]
                require((applied is None) == (y == 200), "case first production evidence is missing or spurious")
                if applied:
                    require(applied["year"] == y+1 and applied["record_sha256"] == journals[seed][y]["record_sha256"],
                            "case first production evidence refers to a different year")
    return [{"seed":s, "owner":c} for s,c in expect]


def check(directory):
    trajectories = indexed(read(directory/"trajectories.json"), ("seed","arm"), product(SEEDS, ARMS))
    reference = Path(__file__).resolve().parents[1] / "studies/chronicle7/long/verification.json"
    controls = read(reference)["worlds"]
    for expected in controls:
        control = trajectories[expected["seed"], "off"]
        require(control["journal_sha256"] == expected["journal_sha256"] and
                control["closing_sha256"] == expected["closing_state_sha256_all_three_runs"] and
                control["chronicle_sha256"] == expected["chronicle_sha256"], "PR #28 control hash mismatch")
    rows = csv_rows(directory/"countries.csv", {"name","arm","cabinet"})
    countries = indexed(rows, ("seed","arm","year","owner"), product(SEEDS, ARMS, YEARS, range(8)))
    events = csv_rows(directory/"adoptions.csv", {"record_sha256"})
    adopters = defaultdict(list)
    unique_regions = set()
    owners = {}
    endowments = {}
    journals = {}
    for seed in SEEDS:
        game = create(seed)
        initial = sha256(canonical_line(snapshot62(game.economy))).hexdigest()
        owners[seed] = {r.id:r.owner for r in game.economy.world.regions}
        endowments[seed] = {c.id:(c.name,c.technology) for c in game.economy.world.nations}
        for arm in ARMS:
            path = trajectories[seed, arm]
            require(path["opening_sha256"] == initial, "initial world does not match its seed")
            require(all(re.fullmatch("[0-9a-f]{64}", path[k]) for k in
                        ("closing_sha256", "journal_sha256", "chronicle_sha256")), "invalid trajectory digest")
        journal = read(directory / "saves" / f"seed-{seed}.json")
        require(journal["seed"] == seed and journal["schema"] == "game-journal/1" and len(journal["turns"]) == 200
                and sha256(canonical_line(journal)).hexdigest() == trajectories[seed,"research"]["journal_sha256"],
                "published research journal differs from trajectory")
        journals[seed] = journal["turns"]
        for year, turn in enumerate(journals[seed], 1):
            command = {1: {"research":True,"move":None},
                       2: {"public_farm":True,"reserve_policy":"emergency","move":None}}.get(year)
            require(turn["year"] == year and turn["command"] == command
                    and re.fullmatch("[0-9a-f]{64}", turn["record_sha256"]), "bad year, command or ledger digest")
    for e in events:
        seed, owner, region = e["seed"], e["owner"], e["region"]
        require(seed in journals and (seed,region) not in unique_regions, "duplicate or unknown regional advancement")
        check_adoption(e, journals[seed], owners[seed])
        unique_regions.add((seed,region))
        adopters[seed,owner].append(e)
    for (seed, arm, year, owner), row in countries.items():
        require(row["regions"] == sum(c == owner for c in owners[seed].values()), "unexpected regional count")
        require((row["name"],row["base_technology"]) == endowments[seed][owner], "fixed general technology differs")
        check_country(row, [e["year"] for e in adopters[seed,owner]])
    blocks = check_comparisons(directory, countries)
    cases = check_cases(directory, countries, adopters, journals)
    return {"trajectories":len(trajectories), "regenerated_opening_worlds":len(owners),
            "research_journals":len(journals), "annual_digest_entries":sum(map(len,journals.values())),
            "controls_with_published_pr28_hashes":[r["seed"] for r in controls],
            "country_checkpoints":len(rows), "unique_regional_adoptions":len(events),
            "sample_blocks":blocks, "paired_world_checkpoints":len(SEEDS)*len(YEARS),
            "selected_cases":cases, "case_country_rows":len(cases)*len(ARMS)*len(YEARS),
            "scope":"Published-file and accounting cross-check; this command performs no annual economic replay."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = json.dumps(check(args.directory), ensure_ascii=False, indent=2) + "\n"
    if args.out is None:
        print(result, end="")
    else:
        with args.out.open("x", encoding="utf-8", newline="\n") as out:
            out.write(result)


if __name__ == "__main__":
    main()
