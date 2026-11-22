"""Replay the development study's joint soil appropriation and tax settlement."""
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from civsim.collective import collective_snapshot, fork_action_year, start_collective, step_collective
from civsim.model import generate_world
from civsim.regions import regionalize
from experiments.phase5a import _sha
from experiments.publication import publish_file


def flows(record):
    gov = record["government"]
    reply = next(r for r in record["collective"]["responses"] if r["id"] == 0)
    taxpayer = next(r for r in gov["levies"] if r["region"] == 1)
    treasury = next(r for r in gov["accounts"] if r["id"] == 0)
    public = treasury["totals"]
    region = next(r for r in record["regions"] if r["id"] == 0)
    return {
        "annual_sha256": _sha(record), "response": reply,
        "country_projects": [p for p in gov["works"]["projects"] if p["owner"] == 0],
        "region1_farm_levy": taxpayer["civic_tax"]["by_group"]["farm"],
        "region0_food_output": region["production"]["produced"]["food"],
        "region0_unmet_food": region["consumption"]["food_unmet"],
        "country_relief_food": public["relief_food"], "country_public_labor": public["public_labor"],
        "country_public_close": treasury["public_close"], "country_private_close": treasury["private_close"],
    }


def replay():
    sim = start_collective(regionalize(generate_world(5)))
    for year in range(1, 58):
        step_collective(sim, year, True)
    opening = _sha(collective_snapshot(sim))
    actual, no_petition = fork_action_year(sim, 58, 0, "farm")
    actual_again, no_refusal = fork_action_year(sim, 58, 1, "farm")
    if opening != _sha(collective_snapshot(sim)):
        raise ValueError("diagnostic modified its source")
    if not _sha(actual) == _sha(actual_again) == _sha(step_collective(sim, 58, True)):
        raise ValueError("fork differs from normal annual execution")
    picture = flows(actual)
    if picture["response"]["kind"] != "compromise" or not any(
        p["action"] == "soil" and p["target"] == 0 and p["soil_gain"] > 0 for p in picture["country_projects"]
    ) or picture["region1_farm_levy"]["concession"]["food"] <= 0:
        raise ValueError("joint response lacks a completed soil project or realized tax concession")
    return {"seed": 5, "year": 58, "owner": 0, "opening_sha256": opening, "actual": picture,
            "without_region0_farm_petition": flows(no_petition), "without_region1_farm_refusal": flows(no_refusal)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    result = replay()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=args.out.parent) as folder:
        stage = Path(folder, "compromise.json")
        stage.write_text(json.dumps(result, indent=2, ensure_ascii=False)+"\n", encoding="utf8", newline="\n")
        publish_file(stage, args.out)
