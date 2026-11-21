"""Versioned, overwrite-protected regional runs, replay and region-year exports."""
import csv
import hashlib
import os
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from .model import GOODS, generate_world
from .regional_engine import RegionalPolicy, step_regional
from .regions import regionalize
from .storage import canonical_line, read_years


def write_regional_run(directory, *, seed=42, years=50, width=48, height=32, nations=8, per_nation=4,
                       policy=RegionalPolicy()):
    directory = Path(directory)
    if os.path.lexists(directory):
        raise FileExistsError(directory)
    if type(years) is not int or years < 1:
        raise ValueError("years must be positive")
    world = regionalize(generate_world(seed, width, height, nations), per_nation)
    meta = {"schema": 1, "model_version": "4.0", "seed": seed, "years": years, "width": width,
            "height": height, "nations": nations, "per_nation": per_nation, "policy": asdict(policy)}
    _publish(directory, meta, asdict(world), lambda year: step_regional(world, year, policy))


def _publish(directory, meta, initial, annual):
    directory.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=directory.parent) as tmp:
        stage = Path(tmp, "run")
        stage.mkdir()
        (stage / "world.json").write_bytes(canonical_line(initial))
        (stage / "manifest.json").write_bytes(canonical_line(meta))
        with (stage / "years.jsonl").open("xb") as stream:
            for year in range(1, meta["years"] + 1):
                stream.write(canonical_line(annual(year)))
        if os.path.lexists(directory):
            raise FileExistsError(directory)
        stage.rename(directory)


def verify_regional(directory, meta):
    expected = {"schema", "model_version", "seed", "years", "width", "height", "nations", "per_nation", "policy"}
    if set(meta) != expected or meta["schema"] != 1 or meta["model_version"] != "4.0":
        raise ValueError("invalid 4.0 manifest")
    policy = meta["policy"]
    if not isinstance(policy, dict) or set(policy) != {"logistics", "investment_scope", "soil_care", "closed_roads"}:
        raise ValueError("invalid 4.0 policy keys")
    rules = RegionalPolicy(**{**policy, "closed_roads": tuple(tuple(x) for x in policy["closed_roads"])})
    world = regionalize(generate_world(meta["seed"], meta["width"], meta["height"], meta["nations"]),
                        meta["per_nation"])
    return _verify_stream(directory, meta, asdict(world), lambda year: step_regional(world, year, rules))


def _verify_stream(directory, meta, initial, annual):
    if canonical_line(initial) != (directory / "world.json").read_bytes():
        raise ValueError("year 0: region partitions, roads or endowments differ")
    digest = hashlib.sha256()
    with (directory / "years.jsonl").open("rb") as source:
        for year in range(1, meta["years"] + 1):
            line = source.readline()
            if canonical_line(annual(year)) != line:
                raise ValueError(f"year {year}: regional ledger differs from replay")
            digest.update(line)
        if source.read(1):
            raise ValueError("unexpected additional annual data")
    return digest.hexdigest()


def regional_summary(directory, export=None):
    result = dict.fromkeys(("initial_population", "final_population", "total_births", "total_deaths",
                            "total_migrants", "total_food_need", "total_food_eaten", "total_food_unmet",
                            "total_food_spoiled", "shortage_region_years", "freight_food", "years"), 0)
    result["model_version"] = "4.0"
    if export is not None:
        export = Path(export)
        export.parent.mkdir(parents=True, exist_ok=True)
    def reduce_rows(writer):
        for row in read_years(directory):
            if "government" in row:
                gov = row["government"]
                result["model_version"] = "5.0A"
                result["policy"] = gov["mode"]
                for field in ("relief_food", "public_freight_food", "public_labor", "collection_cost_food",
                              "public_spoil_food", "road_build_units", "soil_packages"):
                    result[field] = result.get(field, 0) + sum(a["totals"][field] for a in gov["accounts"])
                result["public_reserve"] = {g: sum(a["public_close"][g] for a in gov["accounts"]) for g in GOODS}
                result["freight_food"] += sum(a["totals"]["public_freight_food"] for a in gov["accounts"])
            if not result["years"]:
                result["initial_population"] = sum(r["opening"]["population"] for r in row["regions"])
            if "politics" in row:
                p = row["politics"]
                result["model_version"] = "5.0B"
                result["feedback"] = p["feedback"]
                changed = sum(bool(d["recommendation"]["changed"]) for d in p["countries"])
                result["different_recommendations"] = result.get("different_recommendations", 0) + changed
                result["political_switches"] = result.get("political_switches", 0) + (changed if p["feedback"] else 0)
                opinions = []
                for region in p["regions"]:
                    groups = region["closing"]["groups"].values()
                    members = sum(g["members"] for g in groups)
                    indices = {k: sum(g["members"]*g[k] for g in groups)/members if members else None
                               for k in ("support", "discontent")}
                    opinions.append({"region": region["id"], "owner": region["owner"],
                                     "observed_members": members, **indices})
                result["latest_regional_opinion_permille"] = opinions
            if "competition" in row:
                race = row["competition"]
                result.update(model_version="5.0C", arm=race["arm"], tax_policy=race["tax_policy"])
                result["governments"] = {c["id"]: c["governing_faction"] for c in race["countries"]}
                for key in ("election", "installation", "turnover"):
                    count = sum(bool(c["election"] and c["election"][key]) for c in race["countries"])
                    result["total_" + key] = result.get("total_" + key, 0) + count
            if "collective" in row:
                groups = [g for r in row["collective"]["regions"] for g in r["groups"].values()]
                for key in ("participants", "withheld_workers"):
                    result[key] = result.get(key, 0) + sum(g[key] for g in groups)
                refused = result.setdefault("refused", dict.fromkeys(GOODS, 0))
                for levy in row["government"]["levies"]:
                    for good in GOODS:
                        refused[good] += levy["refused"][good]
            result["years"] += 1
            result["final_population"] = sum(r["closing"]["population"] for r in row["regions"])
            result["total_migrants"] += sum(m["people"] for m in row["moves"])
            result["freight_food"] += row["domestic"]["cost_food"] + sum(
                t["cost_food"] for t in row["border_market"]["trades"])
            freight = {node["id"]: node for node in row["domestic"]["nodes"]}
            for r in row["regions"]:
                meal = r["consumption"]
                for field in ("food_need", "food_eaten", "food_unmet", "food_spoiled"):
                    result["total_"+field] += meal[field]
                result["shortage_region_years"] += int(meal["food_unmet"] > 0)
                for field in ("births", "deaths"):
                    result["total_"+field] += r["demography"][field]
                if writer:
                    writer.writerow([row["year"], r["owner"], r["id"], r["closing"]["population"],
                                     meal["food_need"], meal["food_unmet"], r["closing"]["soil"],
                                     r["closing"]["deposit"], *(r["closing"]["stock"][g] for g in GOODS),
                                     *(r["production"]["produced"][g] for g in GOODS),
                                     r["demography"]["births"], r["demography"]["deaths"],
                                     r["demography"]["immigrants"] - r["demography"]["emigrants"],
                                     freight[r["id"]]["imports"]["food"], freight[r["id"]]["exports"]["food"],
                                     freight[r["id"]]["cost_food"]])
    if export is None:
        reduce_rows(None)
    else:
        # Exclusive create, and clean up only a file this call successfully acquired.
        stream = export.open("x", encoding="utf-8-sig", newline="")
        try:
            with stream:
                writer = csv.writer(stream)
                writer.writerow(["year", "owner", "region", "population", "food_need", "food_unmet",
                                 "soil", "deposit", *GOODS, *(g+"_produced" for g in GOODS),
                                 "births", "deaths", "net_migration", "domestic_food_in", "domestic_food_out",
                                 "freight_food"])
                reduce_rows(writer)
        except BaseException:
            export.unlink(missing_ok=True)
            raise
    return result
