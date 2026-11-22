"""Reconcile the published border-crisis histories, pair tables, and PR #30 controls."""
import argparse
from collections import Counter, defaultdict
from itertools import combinations, product
import json
from pathlib import Path

from civsim.annual_game import create
from civsim.supply62 import snapshot62
from experiments.check_diffusion72 import read_json, read_table
from experiments.check_research71 import indexed, require
from experiments.crisis73 import ARMS, CRISIS, ECONOMY, FLOWS, STOCKS
from experiments.research71 import CHECKPOINTS, ROOT, digest


TRANSITIONS = {"start": (0, 1), "escalate": (1, 2), "ease": (2, 1), "resolve": (1, 0)}


def indexed_table(path, keys, combinations):
    rows = read_table(path)
    for r in rows:
        for k in keys:
            if k != "arm":
                r[k] = int(r[k])
    return indexed(rows, keys, combinations)


def verify(directory, reference):
    seeds = range(40)
    trajectories = indexed(read_json(directory/"trajectories.json"), ("seed", "arm"), product(seeds, ARMS))
    archived = {r["seed"]: r for r in read_json(reference/"trajectories.json") if r["arm"] == "diffusion"}
    journals, borders = {}, {}
    for seed in seeds:
        start = create(seed).economy
        owners = {r.id:r.owner for r in start.world.regions}
        borders[seed] = {tuple(sorted((owners[e.a], owners[e.b]))) for e in start.world.borders if e.capacity > 0}
        opening = digest(snapshot62(start))
        for arm in ARMS:
            trajectory = trajectories[seed, arm]
            require(trajectory["opening_sha256"] == opening, "mismatched opening world")
            folder = directory if arm == "crisis" else reference
            journal = read_json(folder/"saves"/f"seed-{seed}.json")
            require(journal["seed"] == seed and len(journal["turns"]) == 200 and
                    digest(journal) == trajectory["journal_sha256"], "journal identity or digest mismatch")
            for year, turn in enumerate(journal["turns"], 1):
                expected = None
                if year == 1:
                    expected = {"move": None, "research": True, "diffusion": True}
                    if arm == "crisis":
                        expected["crisis"] = True
                elif year == 2:
                    expected = {"move": None, "public_farm": True, "reserve_policy": "emergency"}
                require(turn["year"] == year and turn["command"] == expected, "unpaired policies")
            if arm == "crisis":
                journals[seed] = journal["turns"]
            else:
                require(all(trajectory[k] == archived[seed][k] for k in
                        ("opening_sha256", "closing_sha256", "journal_sha256", "chronicle_sha256", "events")),
                        "PR #30 control differs")

    events = read_table(directory/"events.csv")
    states, changes, last_year = defaultdict(int), defaultdict(Counter), defaultdict(int)
    for e in sorted(events, key=lambda e: (int(e["seed"]), int(e["year"]))):
        seed, year, a, b = (int(e[k]) for k in ("seed", "year", "a", "b"))
        key = seed, a, b
        change = e["transition"]
        old, new = int(e["opening"]), int(e["closing"])
        require((a, b) in borders[seed] and last_year[key] < year <= 200 and int(e["evidence_year"]) == year-1
                and e["record_sha256"] == journals[seed][year-1]["record_sha256"], "unverifiable crisis event")
        position = sorted(borders[seed]).index((a,b))
        require(e["pointer"] == f"/crisis/pairs/{position}/transition", "transition points to another pair")
        require(states[key] == old and TRANSITIONS.get(change) == (old, new), "invalid crisis transition history")
        refusals = int(e["prior_trade_denied"]) + int(e["prior_people_denied"])
        require((refusals > 0) == (new > old), "observed refusals do not support transition")
        states[key], last_year[key] = new, year
        for cutoff in CHECKPOINTS:
            if year <= cutoff:
                tally = changes[seed, cutoff, a, b]
                tally[change] += 1
                for level in (1, 2):
                    tally[f"level{level}_pair_years"] += (int(new == level)-int(old == level))*(cutoff-year+1)

    checkpoints = list(product(seeds, ARMS, CHECKPOINTS))
    worlds = indexed_table(directory/"worlds.csv", ("seed", "arm", "year"), checkpoints)
    pairs = indexed_table(directory/"pairs.csv", ("seed", "arm", "year", "a", "b"),
                          ((*k, *pair) for k in checkpoints for pair in combinations(range(8), 2)))
    countries = indexed_table(directory/"countries.csv", ("seed", "arm", "year", "country"),
                              ((*k, c) for k in checkpoints for c in range(8)))
    for k, w in worlds.items():
        seed, arm, year = k
        total = Counter()
        for a,b in combinations(range(8), 2):
            pair = pairs[*k, a, b]
            require(bool(int(pair["adjacent"])) == ((a,b) in borders[seed]), "adjacency differs from seeded map")
            counters = changes[seed, year, a, b] if arm == "crisis" else Counter()
            require(all(int(pair[field]) == counters[field] for field in (*TRANSITIONS, "level1_pair_years", "level2_pair_years")),
                    "transition register differs from pair counts")
            require(int(pair["active_pair_years"]) == counters["level1_pair_years"] + counters["level2_pair_years"],
                    "crisis duration differs from transition years")
            require(int(pair["workers"]) == 2*int(pair["staffed"]), "staffing charge mismatch")
            require(int(pair["goods_released"]) + int(pair["people_released"]) <= 4*int(pair["staffed"]),
                    "approvals exceed funded case slots")
            total.update({field: int(pair[field]) for field in (*FLOWS, *CRISIS)})
        require(all(int(w[field]) == val for field, val in total.items()), "world differs from sum of country pairs")
        country_fields = {"exports": "quantity", "emigrants": "migrants",
                          **{f:f for f in ("population", "workers", "food", "need", "unmet",
                                          "members", "support_points", "turnovers")}}
        for national, global_field in country_fields.items():
            require(sum(int(countries[*k, c][national]) for c in range(8)) == int(w[global_field]),
                    f"country {national} accounts differ from world {global_field}")

    deltas = indexed(read_json(directory/"paired.json"), ("seed", "year"), product(seeds, CHECKPOINTS))
    for (seed, year), delta in deltas.items():
        a,b = (worlds[seed, arm, year] for arm in ARMS)
        require(delta["cohort"] == ("validation" if seed >= 20 else "development"), "split sample mismatch")
        require(all(delta[k] == int(b[k])-int(a[k]) for k in (*FLOWS, *ECONOMY, *CRISIS, *STOCKS)),
                "paired delta differs from world checkpoints")
        for k, num, den in (("support_delta", "support_points", "members"), ("shortage_rate_delta", "unmet", "need")):
            require(delta[k] == int(b[num])/int(b[den]) - int(a[num])/int(a[den]), "world ratio differs")
    return dict(worlds=len(seeds), trajectories=len(trajectories), journal_years=200*len(trajectories),
                country_checkpoints=len(countries), country_pair_checkpoints=len(pairs),
                world_checkpoints=len(worlds), paired_checkpoints=len(deltas),
                verified_transition_events=len(events), scope="Checks published ledgers and seed geography; no economic replay.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = verify(args.directory, ROOT/"studies/diffusion72/long")
    if args.out:
        with args.out.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(result, output, indent=2)
            output.write("\n")
    else:
        print(json.dumps(result, indent=2))
