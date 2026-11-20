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
    directory.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=directory.parent) as tmp:
        stage = Path(tmp, "run")
        stage.mkdir()
        (stage / "world.json").write_bytes(canonical_line(asdict(world)))
        (stage / "manifest.json").write_bytes(canonical_line(meta))
        with (stage / "years.jsonl").open("xb") as stream:
            for year in range(1, years + 1):
                stream.write(canonical_line(step_regional(world, year, policy)))
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
    if canonical_line(asdict(world)) != (directory / "world.json").read_bytes():
        raise ValueError("year 0: region partitions, roads or endowments differ")
    digest = hashlib.sha256()
    with (directory / "years.jsonl").open("rb") as source:
        for year in range(1, meta["years"] + 1):
            line = source.readline()
            if canonical_line(step_regional(world, year, rules)) != line:
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
            if not result["years"]:
                result["initial_population"] = sum(r["opening"]["population"] for r in row["regions"])
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
