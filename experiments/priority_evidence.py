"""Observed civilian fiscal receipts from one annual record, grouped by region.

Rows are not estimates of spending displaced by another decision. Relief
received credits households. Works materials are attributed to the paying
depot. Aid handling losses are included in dispatched food, not a second fee.
"""

GOODS = ("food", "ore", "tools")

# Each template gives the actual ledger path and the region receiving the
# attribution. Column order is also the public row format.
_SOURCES = (
    ("region", "regions[].id"),
    ("owner", "regions[].owner"),
    ("year", "record.year"),
    ("depot_open_{}", "government.depots[region].opening.{}"),
    ("depot_close_{}", "government.depots[region].closing.{}"),
    ("next_depot_open_{}", "following record: government.depots[region].opening.{}"),
    ("levied_{}", "government.levies[region].levied.{} (gross household debit)"),
    ("levy_deposited_{}", "government.levies[region].deposited.{} (net public credit)"),
    ("levy_handling_food", "government.levies[region].handling_used.food"),
    ("relief_sent_food", "sum government.relief.shipments[source=region].quantity"),
    ("relief_received_food", "sum government.relief.shipments[target=region].quantity (households)"),
    ("relief_freight_food", "sum government.relief.shipments[source=region].cost_food"),
    ("works_used_{}", "sum government.works.projects[source=region].used.{}"),
    ("works_freight_food", "sum government.works.shipments[source=region].cost_food"),
    ("aid_sent_food", "sum diplomacy.physical.aid.shipments[source=region].quantity (gross)"),
    ("aid_received_food", "sum diplomacy.physical.aid.shipments[target=region].received (net)"),
    ("aid_freight_food", "sum diplomacy.physical.aid.shipments[source=region].cost_food"),
    ("aid_handling_food", "sum diplomacy.physical.aid.shipments[source=region].handling_food (in transit)"),
    ("depot_spoiled_food", "government.depots[region].spoil_food"),
    ("depot_transfer_sent_{}", "sum supply.shipments[source=region,good={}].quantity"),
    ("depot_transfer_received_{}", "sum supply.shipments[target=region,good={}].quantity"),
    ("depot_transfer_freight_food", "sum supply.shipments[source=region].cost_food"),
)
PROVENANCE = {}
for template, source in _SOURCES:
    for good in GOODS if "{}" in template else ("",):
        PROVENANCE[template.format(good)] = source.format(good)
COLUMNS = tuple(PROVENANCE)
_AID = tuple(key for key in COLUMNS if key.startswith("aid_"))
_TRANSFER = tuple(key for key in COLUMNS if key.startswith("depot_transfer_"))


def _amount(value):
    if type(value) is not int or value < 0:
        raise ValueError("expected a nonnegative integer on the fiscal receipt")
    return value


def _indexed(records, key):
    index = {_amount(row[key]): row for row in records}
    if len(index) != len(records):
        raise ValueError(f"duplicate {key} in fiscal data")
    return index


def _depots(record):
    regions = _indexed(record["regions"], "id")
    depots = _indexed(record["government"]["depots"], "region")
    if (regions.keys() != depots.keys() or
            any(_amount(r["owner"]) != _amount(depots[i]["owner"]) for i,r in regions.items())):
        raise ValueError("warehouse and region ownership differ")
    return depots


def _year(record):
    value = _amount(record["year"])
    if not value:
        raise ValueError("expected an annual record")
    return value


def _domestic(posting, rows):
    source, target = rows[_amount(posting["source"])], rows[_amount(posting["target"])]
    if source["owner"] != _amount(posting["owner"]) or target["owner"] != source["owner"]:
        raise ValueError("domestic receipt refers to a different owner")
    return source, target


def _extract(record, following):
    year = _year(record)
    gov = record["government"]
    depots = _depots(record)
    levy = _indexed(gov["levies"], "region")
    if depots.keys() != levy.keys():
        raise ValueError("missing or unknown levy region")
    next_depots = None
    if following is not None:
        next_depots = _depots(following)
        if _year(following) != year+1 or depots.keys() != next_depots.keys():
            raise ValueError("the following year must cover the same regions")
    rows = {}
    for i,depot in depots.items():
        r = rows[i] = dict.fromkeys(COLUMNS,0)
        r.update(region=i, owner=depot["owner"], year=year, depot_spoiled_food=_amount(depot["spoil_food"]))
        tax = levy[i]
        if _amount(tax["owner"]) != r["owner"] or (next_depots is not None and next_depots[i]["owner"] != r["owner"]):
            raise ValueError("region ownership differs at a fiscal boundary")
        r["levy_handling_food"] = _amount(tax["handling_used"]["food"])
        for g in GOODS:
            r["depot_open_"+g] = _amount(depot["opening"][g])
            r["depot_close_"+g] = _amount(depot["closing"][g])
            observed = _amount(next_depots[i]["opening"][g]) if next_depots is not None else None
            if observed is not None and observed != r["depot_close_"+g]:
                raise ValueError(f"discontinuous {g} warehouse balance for region {i}")
            r["next_depot_open_"+g] = observed
            gross, net, fee = (_amount(tax[key][g]) for key in ("levied","deposited","handling_used"))
            if gross != net + fee or _amount(tax["depot_close"][g]) != _amount(tax["depot_open"][g]) + net:
                raise ValueError("levy, handling, and net warehouse credit differ")
            r["levied_"+g], r["levy_deposited_"+g] = gross, net
    for project in gov["works"]["projects"]:
        source, _ = _domestic(project,rows)
        for g in GOODS:
            source["works_used_"+g] += _amount(project["used"][g])
    for shipment in gov["works"]["shipments"]:
        source, _ = _domestic(shipment,rows)
        source["works_freight_food"] += _amount(shipment["cost_food"])
    for shipment in gov["relief"]["shipments"]:
        source, target = _domestic(shipment,rows)
        quantity = _amount(shipment["quantity"])
        source["relief_sent_food"] += quantity
        target["relief_received_food"] += quantity
        source["relief_freight_food"] += _amount(shipment["cost_food"])
    if "supply" in record:
        for shipment in record["supply"]["shipments"]:
            source, target = _domestic(shipment,rows)
            g, quantity = shipment["good"], _amount(shipment["quantity"])
            if g not in GOODS:
                raise ValueError("unknown good on inter-depot receipt")
            source["depot_transfer_sent_"+g] += quantity
            target["depot_transfer_received_"+g] += quantity
            source["depot_transfer_freight_food"] += _amount(shipment["cost_food"])
    else:
        for row in rows.values():
            row.update(dict.fromkeys(_TRANSFER))
    if "diplomacy" in record:
        for shipment in record["diplomacy"]["physical"]["aid"]["shipments"]:
            source = rows[_amount(shipment["source"])]
            target = rows[_amount(shipment["target"])]
            sent, received, loss = (_amount(shipment[k]) for k in ("quantity","received","handling_food"))
            if (source["owner"] != _amount(shipment["donor"]) or target["owner"] != _amount(shipment["recipient"])
                    or source["owner"] == target["owner"] or sent != received + loss):
                raise ValueError("foreign aid attribution or in-transit balance differs")
            source["aid_sent_food"] += sent
            source["aid_handling_food"] += loss
            source["aid_freight_food"] += _amount(shipment["cost_food"])
            target["aid_received_food"] += received
    else:
        for row in rows.values():
            row.update(dict.fromkeys(_AID))
    return [[rows[i][column] for column in COLUMNS] for i in sorted(rows)]


def region_rows(record, *, next_record=None):
    """Return independent region rows, using None for unobserved optional sources.

    An observed empty list of receipts contributes zero. A subsequent opening
    is populated solely from the next annual record, after checking continuity.
    """
    try:
        return _extract(record, next_record)
    except (KeyError, TypeError) as exc:
        raise ValueError(f"malformed civilian fiscal evidence: {exc}") from exc
