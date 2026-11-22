"""Streaming world summaries and country-year CSV extracts from saved runs."""

import csv
import json
import os
from pathlib import Path
import shlex

from .model import GOODS
from .storage import _manifest, read_years


REGIONAL_VERSIONS = ("4.0", "5.0A", "5.0B", "5.0C", "5.0D", "6.0A")
REPLAY_MODULES = {"6.0A.1": "civsim.aid61", "6.0B1": "civsim.depot62_cli", "6.0B2": "civsim.peace62_cli"}


def _shell_path(path):
    """Quote guidance for the user's PowerShell or POSIX shell."""
    text = str(path)
    if os.name == "nt":
        return "'" + text.replace("'", "''") + "'"
    return shlex.quote(text)


def _file_guidance(path):
    message = "통계 분석에는 manifest.json이 들어 있는 실행 디렉터리를 지정하세요."
    if path.name in ("manifest.json", "world.json", "years.jsonl") and (path.parent / "manifest.json").is_file():
        return f"{message}\n원장을 검증하려면 python -m civsim verify {_shell_path(path.parent)}"

    # Journal archives have a short header on line one. Data rows can be megabytes.
    with path.open("rb") as stream:
        if path.suffix.lower() == ".jsonl":
            raw = stream.readline(4096)
        else:
            raw = stream.read(256 * 1024)
    try:
        value = json.loads(raw)
    except (ValueError, RecursionError):
        value = None
    schema = value.get("schema") if isinstance(value, dict) else None
    if schema in ("game-journal/1", "annual-game/1", "annual-game/2", "annual-game/3",
                  "annual-game/4", "annual-game/5", "annual-game/6"):
        reader = "civsim.annual_game show"
    elif schema == "unit-board/1":
        reader = "civsim.unit_game show"
    elif schema == "m1-register/1":
        reader = "civsim.posting_archive65 verify"
    else:
        return f"{message}\n기본 예제는 python -m civsim analyze examples/seed-42 로 분석할 수 있습니다."
    return f"{message}\n이 저장 파일을 확인하려면 python -m {reader} {_shell_path(path)}"


def _analysis_manifest(directory):
    directory = Path(directory)
    if directory.is_file():
        raise ValueError(_file_guidance(directory))
    meta = _manifest(directory)
    version = meta.get("model_version")
    if not isinstance(version, str):
        raise ValueError("manifest.json의 model_version에는 버전 문자열이 필요합니다.")
    if version in ("1", "1.0", "2.0", "3.0", "3.1", *REGIONAL_VERSIONS):
        return meta
    message = f"model_version {version!r} 형식의 통계 요약과 CSV 내보내기는 지원하지 않습니다."
    if version in REPLAY_MODULES:
        message += f"\n검증하려면 python -m {REPLAY_MODULES[version]} verify {_shell_path(directory)}"
    raise ValueError(message + f"\n연간 기록을 읽으려면 python -m json.tool --json-lines {_shell_path(directory / 'years.jsonl')}")


def summary(directory: Path) -> dict:
    meta = _analysis_manifest(directory)
    if meta["model_version"] in REGIONAL_VERSIONS:
        from .regional_storage import regional_summary
        result = regional_summary(directory)
        if meta["model_version"] == "5.0D":
            result.update(model_version="5.0D", collective_enabled=meta["enabled"])
        elif meta["model_version"] == "6.0A":
            result.update(model_version="6.0A", diplomatic_arm=meta["arm"], collective_enabled=True)
        return result
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
    if _analysis_manifest(directory)["model_version"] in REGIONAL_VERSIONS:
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
