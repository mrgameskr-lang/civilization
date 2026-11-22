"""One-year public food relief interventions and their following-year carryover."""
import argparse
from collections import Counter
from copy import deepcopy
import gzip
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from civsim.annual_game import create
from civsim.emergency_relief import execute_emergency_relief
from civsim.peace62 import snapshot62
from civsim.storage import canonical_line
from civsim.unit_economy import audit_game, step_game
from experiments.food_reserve_study import advance, digest
from experiments.publication import publish_file


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _economic_state(game):
    return digest(snapshot62(game.economy))


def _food_receipts(record, opening, closing):
    """Keep public food receipts, civilian trade invoices and both closing balances."""
    ordinary = record["government"]["relief"]
    extra = record.get("emergency_relief")
    private = record["domestic"]
    trades = record["border_market"]["trades"]
    stores = {r["region"]: r for r in record["government"]["depots"]}
    meal_issues = {r["id"]: r["ration_food"] for r in record.get("service", {}).get("regions", [])}
    crop = {r["id"]: r["food_public"] for r in record["public_harvest"]["regions"]}
    receipts = {}
    for kind, stage in (("regular", ordinary), ("emergency", extra)):
        totals = Counter()
        for s in (stage or {}).get("shipments", []):
            totals[s["target"]] += s["quantity"]
        receipts[kind] = totals
    regions = []
    for r in sorted(record["regions"], key=lambda n: n["id"]):
        i = r["id"]
        before, after, meal, prod = r["opening"], r["closing"], r["consumption"], r["production"]
        regions.append({"region": i, "owner": r["owner"], "population_open": before["population"],
                        "population_close": after["population"], "private_open": before["stock"]["food"],
                        "private_close": after["stock"]["food"], "public_open": stores[i]["opening"]["food"],
                        "public_close": stores[i]["closing"]["food"], "crop": prod["produced"]["food"],
                        "crop_public": crop[i], "farmers": prod["active_farmers"], "soil_open": before["soil"],
                        "soil_close": after["soil"], "regular_received": receipts["regular"][i],
                        "emergency_received": receipts["emergency"][i], "prior_paid_household_food": meal_issues.get(i, 0),
                        "food_eaten": meal["food_eaten"], "food_unmet": meal["food_unmet"],
                        "private_spoil": meal["food_spoiled"], "public_spoil": stores[i]["spoil_food"]})
    world = {k: sum(r[k] for r in regions) for k in regions[0] if k not in ("region", "owner", "soil_open", "soil_close")}
    world.update(regular_freight=ordinary["cost_food"], emergency_freight=(extra or {}).get("cost_food", 0),
                 private_domestic_qty=sum(s["quantity"] for s in private["shipments"]),
                 private_domestic_freight=sum(s["cost_food"] for s in private["shipments"]),
                 private_border_qty=sum(s["quantity"] for s in trades),
                 private_border_freight=sum(s["cost_food"] for s in trades))
    roads = [{k:e.get(k, 0) for k in ("a", "b", "owner", "capacity", "relief_use", "emergency_use",
                                       "private_use", "unused")} for e in record["government"]["roads"]]
    world["private_domestic_edge_load"] = sum(e["private_use"] for e in roads)
    world["emergency_edge_load"] = sum(e["emergency_use"] for e in roads)
    return {"annual_sha256": digest(record), "opening_sha256": opening, "closing_sha256": closing,
            "world": world, "regions": regions, "roads": roads, "regular": ordinary, "emergency": extra,
            "private_domestic": private["shipments"], "private_border": trades}


def make_case(seed, year):
    """Branch a normally replayed C opening. Both paths use E in the following year."""
    _require(type(seed) is int and 0 <= seed < 20 and type(year) is int and 3 <= year < 200, "invalid development case")
    base = create(seed)
    for t in range(1, year):
        previous = advance(base, t, "C")
    opening = _economic_state(base)
    games = {key: deepcopy(base) for key in ("held", "early")}
    previous_rows = dict.fromkeys(games, previous)
    years = []
    for t in (year, year + 1):
        pair = {"year": t}
        for key, game in games.items():
            before = _economic_state(game)
            record = step_game(game, reserve_policy="emergency" if key == "early" or t > year else None)
            audit_game(record, game.economy.world, previous_rows[key])
            previous_rows[key] = record
            pair[key] = _food_receipts(record, before, _economic_state(game))
        early, held = pair["early"], pair["held"]
        if t == year:
            _require(early["opening_sha256"] == held["opening_sha256"] == opening, "initial states differ")
            _require(early["regular"] == held["regular"] and held["emergency"] is None
                     and early["private_border"] == held["private_border"], "intervention preceded ordinary relief")
            for a, b in zip(early["regions"], held["regions"], strict=True):
                _require(all(a[k] == b[k] for k in ("region", "owner", "population_open", "public_open",
                             "private_open", "crop", "crop_public", "prior_paid_household_food")),
                         "intervention changed pre-dispatch state")
        else:
            for k in games:
                _require(pair[k]["emergency"] is not None and pair[k]["opening_sha256"] == years[0][k]["closing_sha256"],
                         "policy or carry discontinuity")
        pair["delta_early_minus_held"] = {k: v - held["world"][k] for k, v in early["world"].items()}
        years.append(pair)
    _require(_economic_state(base) == opening, "fork mutated the source world")
    return {"seed": seed, "first_year": year, "prior_path": "PR25 C through year " + str(year - 1),
            "comparison": {"early": ["E", "E"], "held": ["C", "E"]}, "years": years}


def transport_control(case):
    """Controlled physical stage test on recorded private stocks, one real donor and existing geometry."""
    sample = case["years"][0]["early"]
    stage = sample["emergency"]
    world = create(case["seed"]).economy.world
    geo = {r.id: r for r in world.regions}
    stage_nodes = {r["id"]: r for r in stage["nodes"]}
    rates = {a["region"]: a["household_rations"] for a in stage["applications"]}
    regions = deepcopy(world.regions)
    for r in regions:
        local = next(x for x in sample["regions"] if x["region"] == r.id)
        r.population = local["population_open"]
        r.stock["food"] = stage_nodes[r.id]["private_food_open"]
    pair = None
    for app in stage["applications"]:
        target, owner = app["region"], app["owner"]
        if app["approved"] == 0:
            continue
        # Restrict to the first applicant in its country, before another applicant could spend the test stock.
        if next(a for a in stage["applications"] if a["owner"] == owner)["region"] != target:
            continue
        for e in world.roads:
            if target not in (e.a, e.b):
                continue
            donor = e.b if e.a == target else e.a
            if stage_nodes[donor]["depot_open"]["food"] >= 2 and any(
                    (x["a"], x["b"]) == (e.a, e.b) and x["capacity"] > 0 for x in stage["roads"]):
                pair = (target, donor, owner)
                break
        if pair:
            break
    _require(pair is not None, "no realized application with a funded neighboring depot")
    target, donor, owner = pair
    result = {"synthetic_stage_inputs": True, "seed": case["seed"], "year": case["first_year"],
              "target": target, "donor": donor, "owner": owner, "observed_stage_sha256": digest(stage),
              "changes": "For this country only, exhaust all depots except the actual adjacent donor. Open uses that donor's recorded food. Blocked leaves the same warehouse stocks but prescribes zero remaining capacity on all roads touching the target. No-freight leaves roads open but the donor has exactly one food. Other countries are unchanged. Test adjustments are external stage inputs, not naturally observed expenses or a second annual economy.",
              "actual_owner_depot_food": {str(i): r["depot_open"]["food"] for i, r in stage_nodes.items() if geo[i].owner == owner},
              "variants": {}}
    for kind in ("open", "blocked", "no_freight"):
        depots = {i: row["depot_open"].copy() for i, row in stage_nodes.items()}
        for i in depots:
            if geo[i].owner == owner and i != donor:
                depots[i]["food"] = 0
        if kind == "no_freight":
            depots[donor]["food"] = 1
        prior = deepcopy(sample["regular"])
        if kind == "blocked":
            for road in prior["roads"]:
                if target in (road["a"], road["b"]):
                    # Preserve every dispatch already posted by regular relief.
                    road["capacity"] -= road["remaining"]
                    road["remaining"] = 0
        capacities = {(e["a"],e["b"]): e["remaining"] for e in prior["roads"]}
        trace, remaining = execute_emergency_relief(deepcopy(regions), world.roads, depots, capacities, prior,
                                                    rates, width=world.width)
        result["variants"][kind] = {
            "application": next(a for a in trace["applications"] if a["region"] == target),
            "target_shipments": [s for s in trace["shipments"] if s["target"] == target],
            "depot_food_open": {str(r["id"]): r["depot_open"]["food"] for r in trace["nodes"] if r["owner"] == owner},
            "roads": [[a, b, capacities[a,b], remaining[a,b]] for a,b in sorted(remaining) if geo[a].owner == owner]}
    variants = result["variants"]
    _require(variants["open"]["application"]["received"] > 0
             and variants["blocked"]["application"]["unfilled"]["road"] > 0
             and variants["no_freight"]["application"]["unfilled"]["freight"] > 0, "controls failed to separate constraints")
    return result


def publish(output, cases=((0, 3), (0, 11))):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    summary = {"schema": "household-relief-forks/1", "delta": "early E minus held C; next year both policies E",
               "source": "Each compressed file contains two consecutive years for both branches. The preserved documents are civilian economic excerpts; annual_sha256 covers the complete engine record.",
               "cases": []}
    with TemporaryDirectory(dir=output.parent) as temp:
        folder = Path(temp) / "completed"
        folder.mkdir()
        for seed, year in cases:
            case = make_case(seed, year)
            name = f"seed-{seed:02}-year-{year:03}.json.gz"
            with (folder / name).open("xb") as raw:
                with gzip.GzipFile(fileobj=raw, filename="", mode="wb", mtime=0) as out:
                    out.write(canonical_line(case))
            summary["cases"].append({"seed": seed, "year": year, "file": name,
                                     "file_sha256": sha256((folder / name).read_bytes()).hexdigest(),
                                     "results": [dict(year=y["year"], delta=y["delta_early_minus_held"],
                                                      held=y["held"]["world"], early=y["early"]["world"]) for y in case["years"]]})
            if seed == 0 and year == 3:
                control = folder / "transport-control.json"
                control.write_bytes(canonical_line(transport_control(case)))
                summary["synthetic_control_sha256"] = sha256(control.read_bytes()).hexdigest()
        (folder / "summary.json").write_bytes(canonical_line(summary))
        folder.rename(output)
    return summary


def _count_obstructions(world_rows):
    """Count only realized terminal road/freight quantities, once per world-year."""
    amounts = {"road": 0, "freight": 0}
    first = None
    occurrences = 0
    years = 0
    for years, row in enumerate(world_rows, 1):
        _require(row["year"] == years and years <= 200, "world-year coverage")
        found = False
        for key in amounts:
            q = row["world"]["emergency_unfilled_" + key]
            _require(type(q) is int and q >= 0, "invalid unfilled quantity")
            amounts[key] += q
            found |= q > 0
        if found:
            occurrences += 1
            if first is None:
                first = years
    _require(years == 200, "truncated E annual table")
    return amounts, occurrences, first


def _natural_case(seed, year):
    """Replay published E and compare a one-year held appropriation from the same accounts."""
    from experiments.reserve_relief_study import advance as advance_reserve

    base = create(seed)
    for t in range(1, year):
        previous = advance_reserve(base, t, "E")
    before = _economic_state(base)
    early_game, held_game = deepcopy(base), deepcopy(base)
    annual = advance_reserve(early_game, year, "E")
    audit_game(annual, early_game.economy.world, previous)
    if year == 2:
        held = advance_reserve(held_game, year, "C")
    else:
        # A recorded economic history stays immutable. Only the research copy's
        # automatic renewal of this appropriation is put on hold for one year.
        original = snapshot62(held_game.economy)
        held_game.economy.reserve_policy = None
        without = snapshot62(held_game.economy)
        _require({k:v for k,v in original.items() if k != "reserve_policy"} == without
                 and original["reserve_policy"] == "emergency", "hold changed the economic opening")
        held = step_game(held_game)
    audit_game(held, held_game.economy.world)
    _require(annual["government"]["relief"] == held["government"]["relief"] and
             annual["public_harvest"] == held["public_harvest"] and annual["border_market"] == held["border_market"],
             "earlier postings differ in one-year hold")
    stage = annual["emergency_relief"]
    balances = {r["id"]: r["depot_open"]["food"] for r in stage["nodes"]}
    owners = {r["id"]: r["owner"] for r in stage["nodes"]}
    remaining = {(r["a"],r["b"]):r["capacity"] for r in stage["roads"]}
    at_stage_open = remaining.copy()
    annual_roads = {(r["a"],r["b"]):r for r in annual["government"]["roads"]}
    examples = []
    for a in stage["applications"]:
        trips = [s for s in stage["shipments"] if s["target"] == a["region"]]
        for s in trips:
            balances[s["source"]] -= s["quantity"] + s["cost_food"]
            for leg in s["legs"]:
                key = tuple(sorted((leg["a"],leg["b"])))
                remaining[key] -= s["quantity"]
        if a["unfilled"]["road"] or a["unfilled"]["freight"]:
            stocks = {str(i): q for i, q in balances.items() if owners[i] == a["owner"]}
            _require(sum(stocks.values()) > 0, "reported transport obstruction without national public food")
            examples.append({"application":a, "target_shipments":trips, "national_depot_food_at_stop":stocks,
                             "national_roads_at_stop":[{"a":i, "b":j, "annual_capacity":annual_roads[i,j]["capacity"],
                                                        "used_by_regular":annual_roads[i,j]["relief_use"],
                                                        "used_before_extra":annual_roads[i,j]["capacity"]-at_stage_open[i,j],
                                                        "extra_open":at_stage_open[i,j], "remaining_at_stop":q}
                                                       for (i,j),q in remaining.items() if owners[i]==a["owner"]]})
    _require(examples and _economic_state(base) == before, "no natural constraints or mutated source")
    observed = _food_receipts(annual,before,_economic_state(early_game))
    withheld = _food_receipts(held,before,_economic_state(held_game))
    return {"seed":seed, "year":year, "previous_path":"ordinary E from year 2",
            "held":"Research-only one-year hold of the emergency appropriation. Earlier receipts, cash and opening warehouse and resident stocks are shared. Ordinary policy renewal applies on the observed branch; the hold explicitly breaks the renewal rule.",
            "failed_applications":examples, "observed":observed, "counterfactual":withheld,
            "delta_observed_minus_held":{k:v-withheld["world"][k] for k,v in observed["world"].items()}}


def scan_study(study, output):
    """Report every official E year; replay first (seed, year) with observed obstruction."""
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    report = {"schema":"household-relief-obstructions/1",
              "definition":"Years have at least one application with residual approved rations coded road or freight. Quantities are the unserved balance at the terminal obstacle, not an estimate of food obtainable by removing that obstacle.",
              "selection":"first seed, then first year; development checked before validation", "samples":{}}
    first_case = None
    for name, seeds in (("development",range(20)),("validation",range(20,40))):
        amounts = {"road":0,"freight":0}
        cases = 0
        for seed in seeds:
            _require((study / f"seed-{seed:02}.json").is_file(), "seed-level publication incomplete")
            with gzip.open(study / f"seed-{seed:02}-E-totals.jsonl.gz", "rb") as stream:
                totals, number, first = _count_obstructions(json.loads(line) for line in stream)
            for k,q in totals.items():
                amounts[k] += q
            cases += number
            if first_case is None and first is not None:
                first_case = (seed,first)
        report["samples"][name] = {"seeds":list(seeds),"world_years":len(seeds)*200,
                                   "world_years_with_obstruction":cases,"unfilled_at_stop":amounts}
    report["first_observed_case"] = None
    if first_case is not None:
        seed, year = first_case
        case = _natural_case(seed, year)
        path = study / f"seed-{seed:02}-E-totals.jsonl.gz"
        with gzip.open(path,"rb") as lines:
            pub = next(json.loads(line)["world"] for y,line in enumerate(lines,1) if y == year)
        replay = case["observed"]
        checked = {k:replay["world"][v] for k,v in (
            ("population","population_open"), ("closing_population","population_close"),
            ("harvest_total","crop"), ("harvest_public","crop_public"),
            ("public_open","public_open"), ("public_close","public_close"),
            ("private_open","private_open"), ("private_close","private_close"),
            ("food_eaten","food_eaten"), ("food_unmet","food_unmet"),
            ("ordinary_received_food","regular_received"), ("emergency_received_food","emergency_received"),
            ("emergency_freight_food","emergency_freight"))}
        for reason in ("stock","road","freight","handling","admin"):
            checked["emergency_unfilled_"+reason] = sum(a["unfilled"][reason] for a in replay["emergency"]["applications"])
        _require(all(pub[k] == q for k,q in checked.items()), "natural fork differs from published economic outcomes")
        case["published_replay_check"] = {"file":path.name,"sha256":sha256(path.read_bytes()).hexdigest(),
                                          "year":year,"verified_totals":checked}
        report["first_observed_case"] = case
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as directory:
        path = Path(directory) / "result.json"
        path.write_bytes(canonical_line(report))
        publish_file(path,output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--natural-study", type=Path, help="examine all 40 published E trajectories and write a single JSON report")
    args = parser.parse_args()
    if args.natural_study is not None:
        print(scan_study(args.natural_study, args.out)["samples"])
        return
    for entry in publish(args.out)["cases"]:
        print(entry["file"], entry["file_sha256"])


if __name__ == "__main__":
    main()
