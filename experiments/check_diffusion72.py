"""Cross-check the published 7.2 tables against game journals and the archived 7.1 arm."""
import argparse
import csv
from collections import Counter, defaultdict
from itertools import product
import json
from pathlib import Path

from civsim.annual_game import create
from civsim.supply62 import snapshot62
from .check_research71 import indexed, require
from .diffusion72 import METRICS
from .research71 import digest


def read_json(path):
    return json.loads(path.read_bytes())


def read_table(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def check_milestones(directory, journals, owners):
    events = {}
    for e in read_table(directory / "events.csv"):
        seed, arm, region = int(e["seed"]), e["arm"], int(e["region"])
        key = (seed, arm, region, e["kind"])
        require(key not in events and owners[seed, region] == int(e["owner"]), "duplicate or foreign milestone")
        events[key] = e
        turns = journals[seed, arm]["turns"]
        year = int(e["year"])
        require(1 <= year <= len(turns) and e["record_sha256"] == turns[year-1]["record_sha256"],
                "milestone year or digest differs from the annual journal")
        if e["contact_year"]:
            contact = int(e["contact_year"])
            require(1 <= contact <= year and e["contact_sha256"] == turns[contact-1]["record_sha256"]
                    and owners[seed, int(e["source"])] == int(e["owner"]) and int(e["source"]) != region
                    and int(e["people"]) > 0, "invalid contact evidence")
        if e["kind"] == "farm_knowledge_contact":
            require(int(e["contact_year"]) == year and not e["application_year"], "contact counted as first use")
        else:
            require(e["kind"] in ("farm_tech_adoption", "farm_tech_transfer"), "unexpected event type")
            require(bool(e["application_year"]) == (year < len(turns)), "missing or spurious first use")
            if e["application_year"]:
                require(int(e["application_year"]) == year+1 and e["application_sha256"] == turns[year]["record_sha256"]
                        and int(e["food"]) >= int(e["food_without_tech"]) >= 0, "unreconciled first harvest")
    for (seed, arm, region, kind), e in events.items():
        if kind == "farm_tech_transfer":
            first = events[seed, arm, region, "farm_knowledge_contact"]
            require(int(first["year"]) < int(e["year"]) and
                    all(first[k] == e[k] for k in ("source", "people", "receipt_pointer", "contact_sha256")),
                    "paid transfer lacks its observed first contact")
    return events


def check_regions(directory, countries, owners, events):
    regions = read_table(directory / "regions.csv")
    actual = indexed(regions, ("seed", "arm", "year", "region"),
                     ((str(s), a, str(y), str(r)) for s, r in owners
                      for a in ("research", "diffusion") for y in (50, 100, 200)))
    by_country = defaultdict(Counter)
    for (seed, arm, year, region), row in actual.items():
        owner = int(row["owner"])
        site = (int(seed), arm, int(region))
        require(owner == owners[int(seed), int(region)], "region belongs to a different country")
        total = by_country[seed, arm, year, str(owner)]
        stage = row["method"]
        mastery, contact = int(row["adoption_year"]), int(row["first_contact"])
        visits, qualified = int(row["domestic_receipts"]), int(row["qualified_receipts"])
        paid = int(row["paid_trials"])
        require(0 <= qualified <= visits <= int(row["domestic_arrivals"]), "invalid migration traffic")
        for kind, present, year_key in (("farm_knowledge_contact", bool(contact), contact),
                                        ("farm_tech_transfer", stage == "transfer", mastery),
                                        ("farm_tech_adoption", stage == "independent", mastery)):
            event = events.get((*site, kind))
            require(present == (event is not None and int(event["year"]) <= int(year)),
                    "regional ledger differs from chronology")
            if present:
                require(int(event["year"]) == year_key, "incorrect year of contact or adoption")
        require(int(row["level"]) == int(bool(mastery)) and stage in ("", "transfer", "independent"),
                "invalid regional technique")
        if stage == "transfer":
            require(0 < contact < mastery and paid == 1, "transfer lacks contact and local paid trial")
        elif stage == "independent":
            require(paid == 2, "independent mastery lacks two local trials")
        else:
            require(paid in (0, 1), "incorrect partial trial count")
        require(not contact or (arm == "diffusion" and qualified > 0
                and int(row["source"]) == int(events[(*site, "farm_knowledge_contact")]["source"])),
                "contact has no qualified migration")
        total.update(trials=paid, advanced_regions=int(bool(mastery)), transfers=int(stage == "transfer"),
                     independent=int(stage == "independent"), contacts=int(bool(contact)),
                     domestic_migrants=int(row["domestic_arrivals"]))
    for key, sums in by_country.items():
        require(all(int(countries[key][field]) == quantity for field, quantity in sums.items()),
                "country table differs from regional components")
    return len(actual)


def check_pairs(directory, countries):
    records = indexed(read_json(directory / "paired.json"), ("seed", "year"),
                      product(range(40), (50, 100, 200)))
    for (seed, year), row in records.items():
        require(row.keys() == {"seed", "year", "cohort", "shortage_rate_delta", "support_delta", *METRICS},
                "missing or unexpected paired indicator")
        require(row["cohort"] == ("development" if seed < 20 else "validation"), "incorrect sample label")
        sets = [[countries[str(seed), arm, str(year), str(owner)] for owner in range(8)]
                for arm in ("research", "diffusion")]
        for key in row.keys() - {"seed", "year", "cohort", "shortage_rate_delta", "support_delta"}:
            a, b = (sum(int(country[key]) for country in group) for group in sets)
            require(row[key] == b-a, f"incorrect paired {key} in seed {seed}, year {year}")
        for key, num, den in (("shortage_rate_delta", "unmet", "need"),
                              ("support_delta", "support_points", "represented_members")):
            a, b = (sum(int(r[num]) for r in group)/sum(int(r[den]) for r in group) for group in sets)
            require(row[key] == b-a, f"incorrect aggregate {key}")
    return len(records)


def verify(directory, prior):
    seeds, years = range(40), (50, 100, 200)
    trajectories = read_json(directory / "trajectories.json")
    legacy = {r["seed"]: r for r in read_json(prior / "trajectories.json") if r["arm"] == "research"}
    baseline, active = "research", "diffusion"
    arms = (baseline, active)
    paths = indexed(trajectories, ("seed", "arm"), product(seeds, arms))
    hashes = ("opening_sha256", "closing_sha256", "chronicle_sha256", "journal_sha256")
    totals = Counter()
    journals, owners = {}, {}
    for seed in seeds:
        game = create(seed)
        owners.update({(seed, r.id): r.owner for r in game.economy.world.regions})
        opening = digest(snapshot62(game.economy))
        for arm in arms:
            path = paths[seed, arm]
            require(path["opening_sha256"] == opening, "opening world differs from its seed")
            folder = prior if arm == baseline else directory
            journal = read_json(folder / "saves" / f"seed-{seed}.json")
            journals[seed, arm] = journal
            require(journal["seed"] == seed and len(journal["turns"]) == 200
                    and digest(journal) == path["journal_sha256"], "journal differs from trajectory")
            for year, turn in enumerate(journal["turns"], 1):
                expected = None
                if year == 1:
                    expected = {"move": None, "research": True}
                    if arm == active:
                        expected["diffusion"] = True
                elif year == 2:
                    expected = {"move": None, "public_farm": True, "reserve_policy": "emergency"}
                require(turn["year"] == year and turn["command"] == expected,
                        "published command differs from the matched treatment")
            totals["annual_digest_entries"] += len(journal["turns"])
        require(all(paths[seed, baseline][k] == legacy[seed][k] for k in hashes),
                "a 7.1 baseline hash differs")
    country_rows = read_table(directory / "countries.csv")
    countries = indexed(country_rows, ("seed", "arm", "year", "owner"),
                        product(map(str, seeds), arms, map(str, years), map(str, range(8))))
    for row in countries.values():
        trials = int(row["trials"])
        require([int(row[k]) for k in ("trial_workers", "trial_ore", "trial_tools")]
                == [2 * trials, trials, trials], "country trial cost mismatch")
        require(0 <= int(row["unmet"]) <= int(row["need"]), "country food account mismatch")
        require(0 <= int(row["fixed_inputs_food_gain"]) <= int(row["food"]),
                "country fixed-input gain exceeds food production")
    events = check_milestones(directory, journals, owners)
    regions = check_regions(directory, countries, owners, events)
    pairs = check_pairs(directory, countries)
    return {**totals, "opening_worlds": len(seeds), "trajectories": len(paths),
            "regional_checkpoints": regions, "farm_milestones": len(events),
            "paired_world_checkpoints": pairs, "archived_research_controls": len(legacy),
            "country_checkpoints": len(countries),
            "scope": "Independent published-file check. Starting worlds regenerated; no annual replay by this command."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--prior", type=Path, default=Path("studies/research71/long"))
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = json.dumps(verify(args.directory, args.prior), indent=2) + "\n"
    if args.out is None:
        print(report, end="")
    else:
        with args.out.open("x", encoding="utf-8", newline="\n") as out:
            out.write(report)


if __name__ == "__main__":
    main()
