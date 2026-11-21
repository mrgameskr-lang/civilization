"""Independently reconcile national public inventories in archived economic years."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
from hashlib import sha256
import json
from pathlib import Path
import platform
from tempfile import TemporaryDirectory
from time import perf_counter

from .publication import publish_file


GOODS = ("food", "ore", "tools")
CASE_NAMES = {"empty", "hold_on", "move_off", "move_on", "one"}
FOOD_EXPENSES = (
    "collection_cost_food", "public_spoil_food", "relief_food", "public_freight_food",
    "duty_rations", "duty_travel_food", "unit_move_food",
)
COMPARABLE = ("schema", "files", "national_rows", "matched_balances", "max_absolute_residual")


def _amount(value):
    if type(value) is not int or value < 0:
        raise ValueError("expected a nonnegative integer in a national account")
    return value


def _index(rows, key):
    indexed = {_amount(r[key]):r for r in rows}
    if len(indexed) != len(rows):
        raise ValueError(f"duplicate {key} in source accounts")
    return indexed


def _national_year(record):
    countries = _index(record["countries"], "id")
    regions = _index(record["regions"], "id")
    government = record["government"]
    accounts = _index(government["accounts"], "id")
    depots = _index(government["depots"], "region")
    if (accounts.keys() != countries.keys() or depots.keys() != regions.keys()
            or any(_amount(r["owner"]) != _amount(depots[i]["owner"])
                   or r["owner"] not in countries for i,r in regions.items())):
        raise ValueError("national or regional account coverage differs")

    aid = Counter()
    for shipment in record["diplomacy"]["physical"]["aid"]["shipments"]:
        source, target = shipment["donor"], shipment["recipient"]
        if source not in countries or target not in countries or source == target:
            raise ValueError("invalid aid account")
        aid[source] -= _amount(shipment["quantity"]) + _amount(shipment["cost_food"])
        aid[target] += _amount(shipment["received"])

    extra = {"food":0, "tools":0}
    for owner, a in accounts.items():
        totals = a["totals"]
        food_expense = _amount(totals.get("unit_upkeep_food", 0))
        tool_expense = _amount(totals.get("unit_upkeep_tools", 0))
        extra["food"] += food_expense
        extra["tools"] += tool_expense
        credits = {g:_amount(totals["levied_" + g]) for g in GOODS}
        credits["food"] += aid[owner]
        debits = {
            "food":sum(_amount(totals[k]) for k in FOOD_EXPENSES) + food_expense,
            "ore":_amount(totals["works_ore"]),
            "tools":_amount(totals["works_tools"]) + _amount(totals["duty_tools"]) + tool_expense,
        }
        for g in GOODS:
            for epoch,side in (("open","opening"), ("close","closing")):
                public = sum(_amount(d[side][g]) for d in depots.values() if d["owner"] == owner)
                private = sum(_amount(r[side]["stock"][g]) for r in regions.values() if r["owner"] == owner)
                if not (public == _amount(a["public_"+epoch][g])
                        and private == _amount(a["private_"+epoch][g]) == _amount(countries[owner][side]["stock"][g])
                        and private + public == _amount(a["combined_"+epoch][g])):
                    raise ValueError(f"national {g} custody differs at year {record['year']}, account {owner}")
            residual = a["public_open"][g] + credits[g] - debits[g] - a["public_close"][g]
            if residual:
                raise ValueError(f"unexplained {g} amount {residual} at year {record['year']}, account {owner}")
    return len(accounts), extra


def check_cases(directory):
    started = datetime.now(timezone.utc).isoformat()
    start = perf_counter()
    directory = Path(directory)
    files = sorted(directory.glob("*.jsonl.gz"))
    if {f.name for f in files} != {name + ".jsonl.gz" for name in CASE_NAMES}:
        raise ValueError("expected all five published case files")
    results = {}
    for file in files:
        rows = country_years = 0
        extra = {"food":0, "tools":0}
        with gzip.open(file, "rt", encoding="utf-8") as stream:
            for line in stream:
                record = json.loads(line)
                rows += 1
                if type(record["year"]) is not int or record["year"] != rows:
                    raise ValueError(f"missing or out-of-order year in {file.name}")
                count, amounts = _national_year(record)
                country_years += count
                for g in extra:
                    extra[g] += amounts[g]
        if rows != 3:
            raise ValueError(f"expected three annual records in {file.name}")
        results[file.name] = {"input_sha256":sha256(file.read_bytes()).hexdigest(), "record_rows":rows,
                              "national_rows":country_years, "stock_balances":country_years*len(GOODS),
                              "additional_expense":extra}
    return {"schema":"national-public-accounts/1", "inputs":directory.as_posix(), "started_utc":started,
            "elapsed_seconds":round(perf_counter()-start,6), "python":platform.python_version(), "files":results,
            "national_rows":sum(x["national_rows"] for x in results.values()),
            "matched_balances":sum(x["stock_balances"] for x in results.values()), "max_absolute_residual":0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, default=Path("examples/token-upkeep-v1/case"))
    parser.add_argument("--verify", type=Path, help="compare hashes, observations and financial balances to a receipt")
    parser.add_argument("--out", type=Path, help="publish the fresh results at a new path")
    args = parser.parse_args()
    result = check_cases(args.case)
    if args.verify is not None:
        expected = json.loads(args.verify.read_bytes())
        if any(expected.get(k) != result[k] for k in COMPARABLE):
            raise ValueError("published account checks or source-file hashes differ")
    data = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if args.out is None:
        print(data, end="")
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=args.out.parent) as scratch:
            staged = Path(scratch) / "accounts.json"
            staged.write_bytes(data.encode("utf-8"))
            publish_file(staged, args.out)


if __name__ == "__main__":
    main()
