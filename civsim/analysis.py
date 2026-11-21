"""Streaming world summaries and country-year CSV extracts from saved runs."""

import csv
from pathlib import Path

from .model import GOODS
from .storage import _manifest, read_years


def summary(directory: Path) -> dict:
    if _manifest(Path(directory)).get("model_version") in ("4.0", "5.0A", "5.0B", "5.0C"):
        from .regional_storage import regional_summary
        return regional_summary(directory)
    result = dict.fromkeys((
        "years", "initial_population", "final_population", "total_births", "total_deaths",
        "total_migrants", "total_food_traded", "shortage_country_years",
        "total_food_need", "total_food_eaten", "total_food_spoiled",
    ), 0)
    for year in read_years(directory):
        countries = year["countries"]
        if result["years"] == 0:
            result["initial_population"] = sum(row["opening"]["population"] for row in countries)
        result["years"] += 1
        result["final_population"] = sum(row["closing"]["population"] for row in countries)
        result["total_migrants"] += sum(move["people"] for move in year["moves"])
        result["total_food_traded"] += sum(deal["quantity"] for deal in year["market"]["trades"]
                                           if deal["good"] == "food")
        for row in countries:
            vital, meal = row["demography"], row["consumption"]
            result["total_births"] += vital["births"]
            result["total_deaths"] += vital["deaths"]
            result["total_food_need"] += meal["food_need"]
            result["total_food_eaten"] += meal["food_eaten"]
            result["total_food_spoiled"] += meal["food_spoiled"]
            result["shortage_country_years"] += int(meal["food_eaten"] < meal["food_need"])
    return result


def _panel_rows(year: dict):
    countries = year["countries"]
    flow_fields = [f"{good}_{flow}" for good in GOODS for flow in ("imports", "exports")]
    trade = {row["id"]: dict.fromkeys([*flow_fields, "import_value", "export_value"], 0)
             for row in countries}
    for deal in year["market"]["trades"]:
        quantity = deal["quantity"]
        value = quantity * deal["unit_price"]
        good = deal["good"]
        buyer, seller = trade[deal["buyer"]], trade[deal["seller"]]
        buyer[f"{good}_imports"] += quantity
        seller[f"{good}_exports"] += quantity
        buyer["import_value"] += value
        seller["export_value"] += value
    for row in countries:
        nation_id = row["id"]
        opening, closing = row["opening"], row["closing"]
        meal, vital = row["consumption"], row["demography"]
        yield {
            "year": year["year"], "nation_id": nation_id, "name": closing["name"],
            "population_open": opening["population"], "population_close": closing["population"],
            "births": vital["births"], "deaths": vital["deaths"],
            "immigrants": vital["immigrants"], "emigrants": vital["emigrants"],
            **{f"{g}_produced": row["production"]["produced"][g] for g in GOODS},
            "food_need": meal["food_need"], "food_eaten": meal["food_eaten"],
            "food_shortfall": meal["food_need"] - meal["food_eaten"], "food_spoiled": meal["food_spoiled"],
            **{f"{g}_stock": closing["stock"][g] for g in GOODS},
            "soil": closing["soil"], "deposit": closing["deposit"], "cash": closing["cash"],
            "food_price": year["market"]["prices"][str(nation_id)]["food"], **trade[nation_id],
        }


def write_panel(directory: Path, output: Path) -> None:
    """Export one row per nation/year, refusing to overwrite any existing path."""
    if _manifest(Path(directory)).get("model_version") in ("4.0", "5.0A", "5.0B", "5.0C"):
        from .regional_storage import regional_summary
        regional_summary(directory, output)
        return
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    stream = output.open("x", encoding="utf-8-sig", newline="")
    try:
        with stream:
            writer = None
            for year in read_years(directory):
                for row in _panel_rows(year):
                    if writer is None:
                        writer = csv.DictWriter(stream, fieldnames=tuple(row))
                        writer.writeheader()
                    writer.writerow(row)
    except BaseException:
        output.unlink(missing_ok=True)
        raise
