"""Direct household relief benefits for political observation, in integer food units.

For each destination, ordinary_received and emergency_received are food credited
to households. relief_received is their sum. legacy_relief_food is the original
political evidence field, which credits ordinary relief. food_eaten and food_unmet
are the later, independently observed meal outcomes. Each total is additive
across regions; adding receipts to meals would count some food twice.

relief_benefits(record) works on a completed live turn or a replayed turn. The
observation is detached from political preferences, elections and the hashed
annual record. The CLI's step option returns the current year, and show
reconstructs every year in the saved journal.
"""
from collections import Counter
from copy import deepcopy


VERSION = "political-relief-benefits/1"
AMOUNTS = ("ordinary_received", "emergency_received", "relief_received",
           "legacy_relief_food", "food_eaten", "food_unmet")


def _require(ok, message):
    if not ok:
        raise ValueError("relief benefits: " + message)


def _amount(q):
    _require(type(q) is int and q >= 0, "expected a nonnegative integer")
    return q


def _index(rows, key):
    result = {_amount(r[key]): r for r in rows}
    _require(len(result) == len(rows), "duplicate region")
    return result


def _stages(record):
    extra = "emergency_relief" in record
    _require(extra == (record["public_policy"].get("reserve_policy") == "emergency"), "emergency authorization mismatch")
    yield "ordinary_received", record["government"]["relief"], "relief"
    if extra:
        yield "emergency_received", record["emergency_relief"], "emergency_relief"


def _receipt_projection(record):
    areas = _index(record["regions"], "id")
    politics = _index(record["politics"]["regions"], "id")
    _require(areas.keys() == politics.keys(), "political region coverage")
    observed = {k: Counter() for k in ("ordinary_received", "emergency_received")}
    for field, stage, _ in _stages(record):
        for trip in stage["shipments"]:
            observed[field][_amount(trip["target"])] += _amount(trip["quantity"])
    rows = []
    for i, area in sorted(areas.items()):
        standard, extra = observed["ordinary_received"][i], observed["emergency_received"][i]
        rows.append({"region": i, "owner": area["owner"], "ordinary_received": standard, "emergency_received": extra,
                     "relief_received": standard + extra, "legacy_relief_food": politics[i]["closing"]["evidence"]["relief_food"],
                     "food_eaten": area["consumption"]["food_eaten"], "food_unmet": area["consumption"]["food_unmet"]})
    return {"version": VERSION, "year": record["year"], "emergency_active": "emergency_relief" in record,
            "regions": rows, "totals": {key: sum(r[key] for r in rows) for key in AMOUNTS}}


def _audit(record, report):
    areas = _index(record["regions"], "id")
    regions = _index(report["regions"], "region")
    political = _index(record["politics"]["regions"], "id")
    levies = _index(record["government"]["levies"], "region")
    trade = _index(record["domestic"]["nodes"], "id")
    _require(bool(areas) and areas.keys() == regions.keys() == political.keys() == levies.keys() == trade.keys(),
             "missing region or inconsistent custody")
    _require(list(regions) == sorted(areas) and report["version"] == VERSION
             and _amount(report["year"]) == _amount(record["year"]) > 0
             and report["emergency_active"] is ("emergency_relief" in record), "version, timeline or region order")
    private = {i: _amount(r["private_close"]["food"]) for i, r in levies.items()}
    for field, stage, purpose in _stages(record):
        nodes = _index(stage["nodes"], "id")
        _require(nodes.keys() == areas.keys(), "incomplete relief custody")
        credited, debited = Counter(), Counter()
        freight = 0
        for shipment in stage["shipments"]:
            a, b = _amount(shipment["source"]), _amount(shipment["target"])
            quantity, fee = _amount(shipment["quantity"]), _amount(shipment["cost_food"])
            _require(quantity > 0 and a in areas and b in areas and _amount(shipment["owner"]) == areas[a]["owner"] == areas[b]["owner"]
                     and shipment["good"] == "food" and shipment["purpose"] == purpose, "invalid source or counterparty")
            credited[b] += quantity
            debited[a] += quantity + fee
            freight += fee
        _require(sum(credited.values()) == _amount(stage["delivered"]) and freight == _amount(stage["cost_food"]),
                 "stage delivery or freight total")
        for i, node in nodes.items():
            before, after = _amount(node["private_food_open"]), _amount(node["private_food_close"])
            _require(node["owner"] == areas[i]["owner"] and before == private[i]
                     and after - before == credited[i] == _amount(regions[i][field]), "food not received at the reported destination")
            _require(_amount(node["depot_open"]["food"]) - _amount(node["depot_close"]["food"]) == debited[i],
                     "source warehouse debit differs from shipped food and freight")
            private[i] = after
        if purpose == "emergency_relief":
            applications = _index(stage["applications"], "region")
            _require(applications.keys() == areas.keys(), "incomplete emergency delivery acknowledgements")
            for i, application in applications.items():
                _require(_amount(application["received"]) == credited[i] == _amount(application["dispatched"]),
                         "emergency receipt differs from destination credit")
    for i, area in areas.items():
        row, meal, evidence = regions[i], area["consumption"], political[i]["closing"]["evidence"]
        _require(_amount(row["owner"]) == _amount(area["owner"]) == _amount(political[i]["owner"])
                 and private[i] == _amount(trade[i]["opening"]["food"]), "private balances before trade")
        ordinary, emergency = _amount(row["ordinary_received"]), _amount(row["emergency_received"])
        _require((report["emergency_active"] or emergency == 0) and ordinary + emergency == _amount(row["relief_received"])
                 and _amount(row["legacy_relief_food"]) == _amount(evidence["relief_food"]) == ordinary,
                 "direct household benefit or historical political credit")
        need, food = _amount(meal["food_need"]), _amount(meal["opening_food"])
        _require(_amount(row["food_eaten"]) == _amount(meal["food_eaten"]) == _amount(evidence["food_eaten"]) == min(need,food)
                 and _amount(row["food_unmet"]) == _amount(meal["food_unmet"]) == _amount(evidence["food_unmet"])
                 == need - min(need,food), "meal outcomes differ from actual consumption")
    _require(set(report["totals"]) == set(AMOUNTS) and all(
        _amount(report["totals"][k]) == sum(r[k] for r in regions.values()) for k in AMOUNTS), "world totals")


def audit_relief_benefits(record, report):
    """Check arrivals from stock changes, warehouse debits, stage totals and meal receipts."""
    try:
        _audit(record, report)
    except (KeyError, TypeError) as exc:
        raise ValueError("relief benefits: incomplete receipt or report") from exc


def relief_benefits(record):
    """Build the official direct-benefit observation without posting goods or political feedback."""
    try:
        report = _receipt_projection(record)
    except (KeyError, TypeError) as exc:
        raise ValueError("relief benefits: incomplete annual receipt") from exc
    audit_relief_benefits(record, report)
    return report


class ReliefBenefitsObserver:
    """Collect detached political benefit observations while replay verifies the journal."""
    def __init__(self):
        self._years = []

    def observe(self, record):
        _require(record["year"] == len(self._years) + 1, "expected next journal year")
        self._years.append(relief_benefits(record))

    def report(self):
        return {"version": VERSION, "years": deepcopy(self._years)}
