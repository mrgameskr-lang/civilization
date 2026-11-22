"""Verify public warehouse stocks and civilian fiscal receipts in compact archives."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import gzip
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from .publication import publish_file


GOODS = ("food", "ore", "tools")
ARMS = ("move_off", "move_on", "relief_first")
FAMILIES = ("depot_open", "depot_close", "next_depot_open", "levied", "levy_deposited", "works_used",
            "depot_transfer_sent", "depot_transfer_received")
FIELDS = ("region", "owner", "year", *(f"{prefix}_{g}" for prefix in FAMILIES for g in GOODS),
          "levy_handling_food", "relief_sent_food", "relief_received_food", "relief_freight_food",
          "works_freight_food", "aid_sent_food", "aid_received_food", "aid_freight_food", "aid_handling_food",
          "depot_spoiled_food", "depot_transfer_freight_food", "movement_food", "old_public_issue_food",
          "old_public_travel_food", "old_public_tools", "paid", "relief_open_food", "relief_close_food")
LINK = tuple("next_depot_open_"+g for g in GOODS)
NUMERIC = tuple(k for k in FIELDS if k not in LINK)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _integer(value):
    return type(value) is int and value >= 0


def _before_relief(row):
    """Public stocks before either relief or the separately posted purchase."""
    balance = {}
    for g in GOODS:
        handling = row["levy_handling_food"] if g == "food" else 0
        _require(row["levied_"+g] == row["levy_deposited_"+g] + handling, "gross levy differs from net credit")
        balance[g] = (row["depot_open_"+g] + row["levy_deposited_"+g] + row["depot_transfer_received_"+g]
                      - row["depot_transfer_sent_"+g] - row["works_used_"+g])
    # Gross international dispatch already contains the in-transit handling loss.
    balance["food"] += row["aid_received_food"] - row["aid_sent_food"] - row["aid_freight_food"]
    balance["food"] -= (row["works_freight_food"] + row["depot_transfer_freight_food"] + row["movement_food"]
                        + row["old_public_issue_food"] + row["old_public_travel_food"])
    balance["tools"] -= row["old_public_tools"]
    return balance


def _financial_row(row, arm):
    before = _before_relief(row)
    paid = row["paid"]
    _require(row["aid_handling_food"] <= row["aid_sent_food"]
             and (row["aid_sent_food"] or not row["aid_freight_food"]), "aid cost without a matching dispatch")
    _require(row["relief_sent_food"] or not row["relief_freight_food"], "unmatched relief freight")
    _require(any(row["depot_transfer_sent_"+g] for g in GOODS) or not row["depot_transfer_freight_food"],
             "inter-depot freight without a dispatch")
    _require(arm != "move_off" or paid == 0, "extra expense in disabled path")
    relief = row["relief_sent_food"] + row["relief_freight_food"]
    opening_relief = before["food"] if arm == "relief_first" else before["food"] - paid
    _require(row["relief_open_food"] == opening_relief
             and row["relief_close_food"] == opening_relief - relief, "relief boundary differs from actual postings")
    closing = {"food":before["food"] - paid - relief - row["depot_spoiled_food"],
               "tools":before["tools"] - paid, "ore":before["ore"]}
    for g in GOODS:
        _require(closing[g] == row["depot_close_"+g], f"unexplained {g} warehouse change")


def check_file(path, seed, arm, *, years=200, region_count=32, country_count=8):
    """Read just the named financial columns; unrelated fields have no role in these equations."""
    path = Path(path)
    regions = set(range(region_count))
    owners = {}
    previous = {}
    total_years = 0
    archive = path.read_bytes()
    with gzip.open(BytesIO(archive), "rt", encoding="utf-8") as stream:
        header = json.loads(stream.readline())
        _require(header.get("schema") == "regional-budget/1" and type(header.get("seed")) is int
                 and header["seed"] == seed and arm in ARMS and header.get("arm") == arm, "wrong ledger identity")
        columns = header.get("columns")
        _require(type(columns) is list and all(type(k) is str for k in columns)
                 and len(columns) == len(set(columns)) and set(FIELDS) <= set(columns), "missing or duplicate columns")
        select = [(k,columns.index(k)) for k in FIELDS]
        for year,line in enumerate(stream,1):
            _require(year <= years, "extra year at end of ledger")
            batch = json.loads(line)
            _require(type(batch) is list and len(batch) == region_count, f"wrong row count at year {year}")
            # Aggregate signed domestic transfers per country and net aid worldwide.
            transfers = [[0,0,0,0] for _ in range(country_count)]
            aid_difference = 0
            current = {}
            for raw in batch:
                _require(type(raw) is list and len(raw) == len(columns), "incomplete regional row")
                r = {k:raw[idx] for k,idx in select}
                _require(all(_integer(r[k]) for k in NUMERIC), "invalid financial amount or key")
                i,owner = r["region"],r["owner"]
                _require(i in regions and i not in current and owner < country_count and r["year"] == year,
                         "duplicate region, invalid region/owner, or wrong year")
                if year == 1:
                    owners[i] = owner
                else:
                    _require(owner == owners[i], "owner discontinuity")
                opening = tuple(r["depot_open_"+g] for g in GOODS)
                closing = tuple(r["depot_close_"+g] for g in GOODS)
                following = tuple(r[k] for k in LINK)
                if year < years:
                    _require(all(_integer(v) for v in following) and following == closing,
                             "following opening differs from closing")
                else:
                    _require(all(v is None for v in following), "unobserved terminal opening has a value")
                _require(year == 1 or previous[i] == opening, "current opening differs from preceding receipt")
                try:
                    _financial_row(r,arm)
                except ValueError as exc:
                    raise ValueError(f"{path.name}, year {year}, region {i}: {exc}") from exc
                current[i] = following
                for j,g in enumerate(GOODS):
                    transfers[owner][j] += r["depot_transfer_received_"+g] - r["depot_transfer_sent_"+g]
                transfers[owner][3] += r["relief_received_food"] - r["relief_sent_food"]
                aid_difference += r["aid_sent_food"] - r["aid_received_food"] - r["aid_handling_food"]
            _require(current.keys() == regions and set(owners.values()) == set(range(country_count)),
                     "incomplete coverage")
            _require(not any(any(balance) for balance in transfers), "domestic transfers or household delivery differ")
            _require(aid_difference == 0, "gross aid differs from net receipt plus handling loss")
            total_years = year
            previous = current
    _require(total_years == years, "truncated ledger")
    return {"seed":seed, "arm":arm, "file":path.name, "sha256":sha256(archive).hexdigest(),
            "region_years":years*region_count, "stock_balances":years*region_count*len(GOODS),
            "linked_region_openings":(years-1)*region_count, "terminal_unobserved_region_openings":region_count,
            "relief_boundary_balances":2*years*region_count, "domestic_net_balances":4*years*country_count,
            "international_aid_balances":years}


def _job(args):
    return check_file(*args)


def check_study(directory, *, workers=1):
    directory = Path(directory)
    clock = perf_counter()
    started = datetime.now(timezone.utc).isoformat()
    seeds = list(range(40))
    runs = [(directory/f"seed-{s:02}-{a}.jsonl.gz",s,a) for s in seeds for a in ARMS]
    execution = json.loads((directory/"execution.json").read_bytes())
    _require(execution["seeds"] == seeds and execution["arms"] == list(ARMS)
             and execution["checkpoints"] == [50,100,200] and execution["regional_rows"] == 768000,
             "unexpected official sample")
    _require({p for p,_,_ in runs} == set(directory.glob("*.jsonl.gz")), "missing or extra regional archive")
    _require(_integer(workers) and workers >= 1, "expected a positive worker count")
    if workers == 1:
        results = list(map(_job,runs))
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_job,runs))
    fields = ("region_years","stock_balances","linked_region_openings","terminal_unobserved_region_openings",
              "relief_boundary_balances","domestic_net_balances","international_aid_balances")
    return {"schema":"regional-fiscal-check/1", "started_utc":started, "elapsed_seconds":round(perf_counter()-clock,6),
            "workers":workers, "seeds":40, "arms":list(ARMS), "years_per_path":200, "regions":32,
            "totals":{k:sum(row[k] for row in results) for k in fields}, "max_absolute_residual":0,
            "fields_read":list(FIELDS), "files":results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, default=Path("examples/relief-priority-v1/study"))
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    result = check_study(args.study,workers=args.workers)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=args.out.parent) as tmp:
        staged = Path(tmp)/"receipt.json"
        staged.write_bytes((json.dumps(result,sort_keys=True,indent=2)+"\n").encode("utf-8"))
        publish_file(staged,args.out)
    print(json.dumps({"elapsed_seconds":result["elapsed_seconds"],**result["totals"]},sort_keys=True))


if __name__ == "__main__":
    main()
