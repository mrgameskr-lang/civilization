"""Verify the revised capacity tables against the original 5.0A publication."""
import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path


def _rows(file, keys):
    with file.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    indexed = {tuple(row[k] for k in keys): row for row in rows}
    if len(rows) != len(indexed):
        raise ValueError(f"duplicate keys in {file.name}")
    return indexed


def compare(reference, corrected):
    result = {}
    for sample in ("dev", "holdout"):
        before, after = reference / sample, corrected / sample
        summary = {"tables": {}, "changed_checkpoints": []}
        for name, keys in (("runs", ("seed","mode","year")), ("countries", ("seed","mode","year","owner")),
                           ("paired", ("seed","mode","year")), ("means", ("mode","year"))):
            a, b = (_rows(folder / f"{name}.csv", keys) for folder in (before, after))
            if a.keys() != b.keys():
                raise ValueError(f"rows differ in {sample}/{name}")
            revised = ("delta_" if name == "paired" else "") + "final_effective_capacity"
            current = ("delta_" if name == "paired" else "") + "year_effective_capacity"
            following = ("delta_" if name == "paired" else "") + "next_year_effective_capacity"
            changes = 0
            for key, old in a.items():
                new = b[key]
                if any(new[k] != val for k, val in old.items() if k != revised):
                    raise ValueError(f"unrelated field changed in {sample}/{name}/{key}")
                if new[current] != old[revised] or new[following] != new[revised]:
                    raise ValueError(f"capacity columns disagree in {sample}/{name}/{key}")
                if name in ("runs", "countries"):
                    base = int(new["year_base_capacity"])
                    if (int(new["base_capacity"]) != base*int(new["year"])
                            or int(new["effective_capacity"]) - int(new["next_capacity"]) != base-int(new[following])
                            or int(new["closing_road_units"]) != int(new["road_build_units"])-int(new["road_lost_units"])):
                        raise ValueError(f"cumulative capacity identity failed in {sample}/{name}/{key}")
                if new[revised] != old[revised]:
                    changes += 1
                    if name == "runs":
                        summary["changed_checkpoints"].append({"seed": int(new["seed"]), "mode": new["mode"],
                            "year": int(new["year"]), "available_during_year": int(new[current]),
                            "available_next_year": int(new[following])})
            summary["tables"][name] = {"matched_rows": len(a), "changed_endpoints": changes}
        summary["identical_files_sha256"] = {}
        for file in ("regions.csv", "cases.json"):
            data = (before / file).read_bytes()
            if data != (after / file).read_bytes():
                raise ValueError(f"{sample}/{file} differs")
            summary["identical_files_sha256"][file] = sha256(data).hexdigest()
        result[sample] = summary
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--corrected", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    receipt = json.dumps(compare(args.reference, args.corrected), indent=2) + "\n"
    if args.out:
        with args.out.open("x", encoding="utf-8", newline="\n") as f:
            f.write(receipt)
    else:
        print(receipt, end="")
