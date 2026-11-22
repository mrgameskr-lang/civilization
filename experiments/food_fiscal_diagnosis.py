"""Explain changes in public food stocks and the baseline regional tax receipts."""
import argparse
from collections import Counter
import gzip
from hashlib import sha256
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .publication import publish_file


BANDS = ((1, 50), (51, 100), (101, 150), (151, 200))
FREIGHT = ("works_freight_food", "depot_transfer_freight_food", "relief_freight_food", "aid_freight_food")
DRAINS = ("levy_handling_food", "relief_sent_food", "household_public_issue_food", "works_used_food",
          "public_freight_food", "public_travel_food", "public_movement_expense_food",
          "other_public_expense_food", "depot_spoiled_food", "aid_handling_food")
FLOW_KEYS = ("public_open", "public_close", "harvest_public", "levied_food", "levy_deposited_food",
             "relief_received_food", "depot_transfer_sent_food", "depot_transfer_received_food",
             "aid_sent_food", "aid_received_food", *FREIGHT, *DRAINS)
TAX_AMOUNTS = ("taxable_surplus_food", "tax_assessed_food", "tax_concession_food", "tax_refused_food",
               "levied_food", "levy_handling_food", "levy_deposited_food")
TAX_KEYS = ("population", "tax_private_before", "tax_protected_food", "tax_warehouse_space", *TAX_AMOUNTS)
TAX_REASONS = ("at_or_below_protected_floor", "no_warehouse_space", "standing_integer_ceiling_zero",
               "other_zero_assessment", "fully_conceded", "fully_refused", "conceded_and_refused",
               "entire_collection_spent_on_handling", "positive_net_deposit")
TAX_CLASSES = ("zero_harvest", "positive_harvest_no_taxable_surplus",
               "positive_harvest_surplus_no_gross_collection", "positive_harvest_surplus_positive_gross_collection")


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _check_values(row, keys):
    for k in keys:
        if type(row.get(k)) is not int or row[k] < 0:
            raise ValueError(f"expected nonnegative integer for {k}")


def fiscal_flows(row):
    """Count a tax collection gross; cancel movements between public warehouses worldwide."""
    _check_values(row, FLOW_KEYS)
    _require(row["levied_food"] == row["levy_deposited_food"] + row["levy_handling_food"], "tax handling imbalance")
    _require(row["relief_sent_food"] == row["relief_received_food"], "relief did not reach private stocks")
    _require(row["depot_transfer_sent_food"] == row["depot_transfer_received_food"], "inter-depot imbalance")
    _require(row["aid_sent_food"] == row["aid_received_food"] + row["aid_handling_food"], "aid handling imbalance")
    _require(row["public_freight_food"] == sum(row[k] for k in FREIGHT), "public freight imbalance")
    gross = row["harvest_public"] + row["levied_food"]
    drains = sum(row[k] for k in DRAINS)
    change = gross - drains
    _require(change == row["public_close"] - row["public_open"], "world public food stock-flow imbalance")
    result = {k: row[k] for k in FLOW_KEYS if k not in ("public_open", "public_close")}
    result.update(gross_inflow=gross, total_outflow=drains, net_stock_change=change,
                  deposited_inflow=gross - row["levy_handling_food"],
                  after_deposit_outflow=drains - row["levy_handling_food"])
    return result


def tax_reason(row):
    """Classify each actual local tax outcome once; supplementary assessments need separate authorization."""
    _check_values(row, TAX_KEYS)
    surplus, room = row["taxable_surplus_food"], row["tax_warehouse_space"]
    assessed, cut, refused = row["tax_assessed_food"], row["tax_concession_food"], row["tax_refused_food"]
    gross, deposit = row["levied_food"], row["levy_deposited_food"]
    _require(surplus == max(0, row["tax_private_before"] - row["tax_protected_food"]), "tax protection imbalance")
    _require(assessed <= min(surplus, room) and assessed == gross + cut + refused
             and gross == deposit + row["levy_handling_food"], "assessment or receipt imbalance")
    if deposit:
        return "positive_net_deposit"
    if gross:
        return "entire_collection_spent_on_handling"
    if cut and refused:
        return "conceded_and_refused"
    if cut:
        return "fully_conceded"
    if refused:
        return "fully_refused"
    if not surplus:
        return "at_or_below_protected_floor"
    if not room:
        return "no_warehouse_space"
    if min(surplus // 16, row["population"] // 64) == 0:
        return "standing_integer_ceiling_zero"
    return "other_zero_assessment"


def summarize_band(paths, first, last):
    """Aggregate annual flows over independent worlds; stocks are measured at the two boundaries."""
    _require(bool(paths) and first <= last, "empty fiscal interval")
    flows = Counter()
    opening = closing = 0
    for values, start, end in paths:
        _require(len(values) == last - first + 1, "missing years in fiscal interval")
        _require(sum(v["net_stock_change"] for v in values) == end - start, "discontinuous interval stocks")
        for v in values:
            flows.update(v)
        opening += start
        closing += end
    _require(flows["net_stock_change"] == closing - opening, "pooled stock-flow imbalance")
    n = len(paths)
    years = n * (last - first + 1)
    return {"first_year": first, "last_year": last, "worlds": n, "world_years": years,
            "totals": dict(flows), "per_world_year": {k: v / years for k, v in flows.items()},
            "boundary_stocks": {"opening_sum": opening, "closing_sum": closing,
                                "opening_per_world": opening / n, "closing_per_world": closing / n}}


def _read(path, fingerprints):
    raw = path.read_bytes()
    fingerprints[path.name] = sha256(raw).hexdigest()
    return gzip.GzipFile(fileobj=io.BytesIO(raw))


def _worlds(path, fingerprints):
    result = []
    with _read(path, fingerprints) as src:
        for year, line in enumerate(src, 1):
            data = json.loads(line)
            world = data["world"]
            _require(data["year"] == year and year <= 200 and world["region_count"] == 32, "world coverage")
            countries = data["countries"]
            _require(len(countries) == 8 and {n["owner"] for n in countries} == set(range(8)), "country coverage")
            for k in FLOW_KEYS:
                _require(sum(n[k] for n in countries) == world[k], "national sums disagree: " + k)
            if result:
                _require(result[-1][0]["public_close"] == world["public_open"], "world stocks failed to carry")
            result.append((world, fiscal_flows(world)))
    _require(len(result) == 200, "incomplete world history")
    return result


def _empty_tax():
    return {"region_years": 0, "classes": dict.fromkeys(TAX_CLASSES, 0),
            "reasons_by_harvest": {h: dict.fromkeys(TAX_REASONS, 0) for h in ("no_harvest", "positive_harvest")},
            "amounts": dict.fromkeys(TAX_AMOUNTS, 0)}


def _baseline_tax(path, fingerprints, seed, baseline, pooled):
    fields = ("year", "region", "owner", "harvest_total", *TAX_KEYS)
    with _read(path, fingerprints) as src:
        header = json.loads(next(src))
        cols = header["columns"]
        _require(header["schema"] == "food-flow/1" and header["seed"] == seed and header["arm"] == "A"
                 and len(set(cols)) == len(cols), "incorrect regional schema or identity")
        indices = [cols.index(k) for k in fields]
        owners = {}
        for year, (world, _) in enumerate(baseline, 1):
            raw = src.readline()
            _require(bool(raw), "missing regional year")
            rows = json.loads(raw)
            seen = set()
            sums = Counter()
            group = pooled[(year - 1) // 50]
            for row in rows:
                _require(len(row) == len(cols), "incorrect regional row length")
                r = {k: row[i] for k, i in zip(fields, indices)}
                _check_values(r, fields[:4])
                i = r["region"]
                _require(r["year"] == year and i < 32 and i not in seen and r["owner"] < 8
                         and r["owner"] == owners.setdefault(i, r["owner"]), "incorrect regional identity")
                seen.add(i)
                why = tax_reason(r)
                harvested = bool(r["harvest_total"])
                if not harvested:
                    category = TAX_CLASSES[0]
                elif not r["taxable_surplus_food"]:
                    category = TAX_CLASSES[1]
                elif not r["levied_food"]:
                    category = TAX_CLASSES[2]
                else:
                    category = TAX_CLASSES[3]
                group["classes"][category] += 1
                group["reasons_by_harvest"]["positive_harvest" if harvested else "no_harvest"][why] += 1
                group["region_years"] += 1
                for k in TAX_AMOUNTS:
                    group["amounts"][k] += r[k]
                    sums[k] += r[k]
                sums["harvest_total"] += r["harvest_total"]
            _require(len(seen) == 32 and set(owners.values()) == set(range(8)), "regional coverage")
            _require(all(world[k] == quantity for k, quantity in sums.items()), "regional/world tax discrepancy")
        _require(not src.readline(), "unexpected additional regional year")


def summarize_cohort(directory, seeds, fingerprints):
    """Read the three arm-level fiscal tables and one baseline regional table for each seed."""
    seeds = tuple(seeds)
    _require(len(set(seeds)) == len(seeds) and bool(seeds), "invalid seed list")
    by_arm = {arm: [[] for _ in BANDS] for arm in "ABC"}
    tax = [_empty_tax() for _ in BANDS]
    for seed in seeds:
        for arm in "ABC":
            filename = f"seed-{seed:02}-{arm}"
            history = _worlds(directory / (filename + "-totals.jsonl.gz"), fingerprints)
            for index, (first, last) in enumerate(BANDS):
                rows = history[first - 1:last]
                by_arm[arm][index].append(([flows for _, flows in rows], rows[0][0]["public_open"],
                                           rows[-1][0]["public_close"]))
            if arm == "A":
                _baseline_tax(directory / (filename + "-regions.jsonl.gz"), fingerprints, seed, history, tax)
    for (first, last), t in zip(BANDS, tax):
        t.update(first_year=first, last_year=last, worlds=len(seeds))
        counts = sum(sum(x.values()) for x in t["reasons_by_harvest"].values())
        _require(len(seeds) * (last - first + 1) * 32 == t["region_years"] == sum(t["classes"].values()) == counts,
                 "baseline census incomplete")
    return {"seeds": list(seeds), "public_accounts_by_arm": {
        arm: [summarize_band(paths, *band) for paths, band in zip(by_arm[arm], BANDS)] for arm in "ABC"},
        "baseline_tax": tax}


def diagnose(directory):
    fingerprints = {}
    cohorts = {name: summarize_cohort(directory, seeds, fingerprints) for name, seeds in (
        ("development", range(20)), ("validation", range(20, 40)))}
    manifest = json.dumps(fingerprints, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"schema": "food-fiscal-diagnosis/1", "input_files": len(fingerprints),
            "input_manifest_sha256": sha256(manifest).hexdigest(),
            "definitions": {
                "units": "All amounts in simulated food units. Flows are period sums or per simulated world-year. Stocks are measured once per world at each interval boundary.",
                "gross_inflow": ["harvest_public", "levied_food"], "total_outflow": list(DRAINS),
                "freight_breakdown": list(FREIGHT),
                "internal_transfers": "Inter-depot and foreign aid dispatch/receipt stay in world public custody. Only aid loss and actual freight leave it. Domestic relief and household issues enter private custody.",
                "extra_views": "Deposited inflow and after-deposit outflow both exclude levy handling. Memo fields for freight components, net tax, aid, and shipment receipts overlap the parent totals.",
                "tax_coverage": "A only, 32 regions each year. Gross collection is positive even if entirely spent on handling. Net deposit is after handling. Zero harvest can coexist with taxable previously held or traded food.",
                "assessment": "Use private food at collection after border trade. Taxable surplus is stock above the protected floor. Classify zero assessment by floor first, then full warehouse, then zero normal integer cap (min(surplus//16,population//64)); this last condition does not preclude an authorized supplemental levy. Remaining zero assessments have no assigned cause.",
                "concessions": "Count concessions and refusal only from postings against an actual assessment. Positive net collections can still have partial concessions and refusals, included in amounts."},
            "cohorts": cohorts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    result = diagnose(args.study)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=args.out.parent) as directory:
        staged = Path(directory) / "report.json"
        staged.write_bytes((json.dumps(result, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        publish_file(staged, args.out)
    print(f"Reconciled 24,000 world-years and 256,000 baseline region-years from {result['input_files']} files.")


if __name__ == "__main__":
    main()
