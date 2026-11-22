"""Read the published consultation journals without invoking the diplomatic model."""
import argparse
from collections import Counter
import csv
import gzip
import hashlib
import json
from pathlib import Path

from experiments.civic_disputes63 import ECONOMIC, HORIZONS, MODES, write_json


def following_outcome(record):
    if not record["observed"]:
        return "unobserved"
    return {"ease": "eased", "continue": "continued"}[record["event"]]


def inspect_sample(directory):
    with (directory/"runs.csv").open(encoding="utf8", newline="") as stream:
        runs = {(int(r["seed"]), r["mode"], int(r["year"])): r for r in csv.DictReader(stream)}
    with (directory/"pairs.csv").open(encoding="utf8", newline="") as stream:
        pair_end = [r for r in csv.DictReader(stream) if r["mode"] == "consult" and r["year"] == "200"]
    counts, cases, verdicts, by_year = Counter(), {}, Counter(), {}
    previous = {}
    for year in HORIZONS:
        selected = [r for (seed, mode, y), r in runs.items() if y == year and mode == "consult"]
        keys = ("pair_years", "observed_years", "active_observed_years", "start", "continue", "ease",
                "accepted", "declined", "defer", "one_direction_years", "no_direction_years")
        summary = {k: sum(int(r[k]) for r in selected) for k in keys}
        summary.update({f"worlds_without_{k}": sum(int(r[k]) == 0 for r in selected)
                        for k in ("start", "accepted", "declined")})
        by_year[str(year)] = summary
        for r in selected:
            baseline = runs[int(r["seed"]), "observe", year]
            if any(r[k] != baseline[k] for k in (*ECONOMIC, "economic_years_sha256", "initial_sha256")):
                raise ValueError("economic projections differ across consultation paths")
    with gzip.open(directory/"annual.jsonl.gz", "rb") as data:
        while left := data.readline():
            right = data.readline()
            if not right:
                raise ValueError("missing paired policy observation")
            observe, consult = json.loads(left), json.loads(right)
            seed = consult["pairs"][0]["seed"]
            year = consult["year"]
            if (observe["mode"], consult["mode"]) != MODES or year != observe["year"]:
                raise ValueError("consultation policies or years are out of order")
            if year == 1:
                previous = {}
                digests = [hashlib.sha256(), hashlib.sha256()]
            digests[0].update(left)
            digests[1].update(right)
            if year in HORIZONS:
                for mode, digest in zip(MODES, digests, strict=True):
                    if runs[seed, mode, year]["civic_years_sha256"] != digest.hexdigest():
                        raise ValueError("published raw civic journal and horizon digest differ")
                    counts["verified_civic_digests"] += 1
            for baseline, r in zip(observe["pairs"], consult["pairs"], strict=True):
                pair = r["a"], r["b"]
                counts["paired_pair_years"] += 1
                for k in ("seed", "year", "a", "b", "evidence", "signal", "event", "observed"):
                    if baseline[k] != r[k]:
                        raise ValueError(f"journal paths differ for {k}")
                if (baseline["closing"]["active"] != r["closing"]["active"]
                        or baseline["closing"]["quiet_years"] != r["closing"]["quiet_years"]):
                    raise ValueError("pair dispute paths differ")
                prior = previous.get(pair)
                if prior and prior["decision"] in ("accepted", "declined"):
                    outcome = following_outcome(r)
                    verdicts[f"{prior['decision']}_{outcome}"] += 1
                    cases.setdefault(f"{prior['decision']}_{outcome}", dict(prior, next_year=year,
                                     next_event=r["event"], next_tension=r["signal"]["tension"] if r["observed"] else None))
                decision = r["proposal"]["decision"]
                responsive = r["proposal"]["responder"]
                pos = next((p for p in r["proposal"]["positions"] if p["country"] == responsive), {})
                previous[pair] = {"seed": seed, "year": year, "a": pair[0], "b": pair[1], "decision": decision,
                                  "requester": r["proposal"]["requester"], "responder": responsive,
                                  "evidence_year": r["evidence_year"], "event": r["event"],
                                  "tension": r["signal"]["tension"] if r["observed"] else None,
                                  "trust": r["signal"]["trust"] if r["observed"] else None,
                                  "consent_constraints": pos.get("consent_constraints", [])}
                if year == 200 and decision in ("accepted", "declined"):
                    verdicts[f"{decision}_right_censored"] += 1
    for group, region in (("adjacent","1"),("nonadjacent","0")):
        rows = [r for r in pair_end if r["adjacent"] == region]
        counts[f"{group}_dyads"] = len(rows)
        counts[f"{group}_dyads_without_observed_start"] = sum(r["start"] == "0" for r in rows)
    with (directory/"fork-checkpoints.csv").open(encoding="utf8", newline="") as stream:
        for r in csv.DictReader(stream):
            if r["year"] == "200":
                for k in ("fork_pair_years", "fork_active_differences", "fork_consulting_differences", "fork_observed"):
                    counts[k] += int(r[k])
    if counts["paired_pair_years"] != counts["fork_pair_years"]:
        raise ValueError("fork does not cover all pair years")
    for decision in ("accepted","declined"):
        total = sum(v for k,v in verdicts.items() if k.startswith(decision+"_"))
        if total != by_year["200"][decision]:
            raise ValueError("follow-up denominators do not close")
    return {"cumulative": by_year, "coverage": counts, "next_year_after_decision": verdicts, "cases": cases}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    write_json(args.out, {sample: inspect_sample(args.study/sample) for sample in ("dev", "holdout")})
