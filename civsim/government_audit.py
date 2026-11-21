"""Reconstruct regional private, regional depot and consolidated country flows independently."""
from collections import Counter

from .appropriation_audit import audit_appropriations
from .audit import BalanceError
from .model import GOODS
from .public_works import ROAD_BONUS
from .regional_engine import audit_national_year


def _check(condition, message):
    if not condition:
        raise BalanceError(message)


def _by(rows, key):
    result = {row[key]: row for row in rows}
    _check(len(result) == len(rows), f"duplicate {key} in ledger")
    return result


def _valid(stock):
    return set(stock) == set(GOODS) and all(type(v) is int and v >= 0 for v in stock.values())


def country_accounts(record, decisions):
    gov = record["government"]
    accounts = {}
    counters = ("relief_food", "public_freight_food", "road_build_units", "road_maintained_units",
                "road_lost_units", "works_ore", "works_tools", "public_labor", "soil_packages",
                "public_spoil_food", "collection_cost_food", "base_capacity", "effective_capacity",
                "next_capacity", "public_cargo", "action_executed", "extra_food")
    for country in record["countries"]:
        owner = country["id"]
        accounts[owner] = {"id": owner, "mode": gov["mode"], "decision": decisions[owner],
                           "totals": dict.fromkeys((*counters, *("levied_" + g for g in GOODS)), 0)}
        for label, endpoint in (("open", "opening"), ("close", "closing")):
            private = country[endpoint]["stock"].copy()
            public = {g: sum(d[endpoint][g] for d in gov["depots"] if d["owner"] == owner) for g in GOODS}
            accounts[owner].update({"private_" + label: private, "public_" + label: public,
                                    "combined_" + label: {g: private[g] + public[g] for g in GOODS}})
    for levy in gov["levies"]:
        t = accounts[levy["owner"]]["totals"]
        for g in GOODS:
            t["levied_" + g] += levy["levied"][g]
        t["collection_cost_food"] += levy["handling_used"]["food"]
        t["extra_food"] += levy["extra_levy"]["food"]
    for d in gov["depots"]:
        accounts[d["owner"]]["totals"]["public_spoil_food"] += d["spoil_food"]
    for s in gov["relief"]["shipments"]:
        accounts[s["owner"]]["totals"]["relief_food"] += s["quantity"]
    for stage in ("works", "relief"):
        for s in gov[stage]["shipments"]:
            accounts[s["owner"]]["totals"]["public_freight_food"] += s["cost_food"]
    for p in gov["works"]["projects"]:
        t = accounts[p["owner"]]["totals"]
        t["works_ore"] += p["used"]["ore"]
        t["works_tools"] += p["used"]["tools"]
        t["public_labor"] += p["workers"]
        t[{"build": "road_build_units", "service": "road_maintained_units", "soil": "soil_packages"}[p["action"]]] += 1
    for e in gov["roads"]:
        t = accounts[e["owner"]]["totals"]
        t["base_capacity"] += e["base"]
        t["effective_capacity"] += e["capacity"]
        t["next_capacity"] += e["next_capacity"]
        t["public_cargo"] += e["works_use"] + e["relief_use"]
        t["road_lost_units"] += e["opening_units"] - e["closing_units"]
    for a in accounts.values():
        t = a["totals"]
        t["road_lost_units"] += t["road_build_units"]
        action = a["decision"]["action"]
        field = {"relief": "relief_food", "road": "road_build_units", "soil": "soil_packages", "reserve": "extra_food"}
        t["action_executed"] = int(action in field and t[field[action]] > 0)
    return list(accounts.values())


def _road_audit(record):
    gov = record["government"]
    edges = {(e["a"], e["b"]): e for e in gov["roads"]}
    _check(len(edges) == len(gov["roads"]), "duplicate annual road")
    civil = {(e["a"], e["b"]): e for e in record["domestic"]["roads"]}
    _check(edges.keys() == civil.keys(), "public and private road sets differ")
    loads, projects = Counter(), Counter()
    for name, stage in (("works_use", gov["works"]), ("relief_use", gov["relief"]), ("private_use", record["domestic"])):
        for cargo in stage["shipments"]:
            for leg in cargo["legs"]:
                edge = tuple(sorted((leg["a"], leg["b"])))
                _check(edge in edges, "freight outside national road network")
                loads[edge, name] += cargo["quantity"]
    for p in gov["works"]["projects"]:
        if p["edge"] is not None:
            projects[tuple(p["edge"]), p["action"]] += 1
    for key, e in edges.items():
        for kind in ("works_use", "relief_use", "private_use"):
            _check(e[kind] == loads[key, kind], "shared cargo differs from physical loads")
        _check(0 <= projects[key, "service"] <= e["opening_units"]
               and e["closing_units"] == projects[key, "service"] + projects[key, "build"],
               "road capacity lacks funded project")
        _check(e["capacity"] == e["base"] + ROAD_BONUS * e["opening_units"]
               and e["next_capacity"] == e["base"] + ROAD_BONUS * e["closing_units"]
               and civil[key]["capacity"] == e["capacity"] - e["works_use"] - e["relief_use"]
               and e["unused"] == e["capacity"] - sum(e[k] for k in ("works_use", "relief_use", "private_use"))
               and e["unused"] >= 0, "road capacity balance")


def audit_fiscal_year(record, *, previous_record=None):
    gov = record["government"]
    if previous_record is not None:
        _check(("competition" in record) == ("competition" in previous_record), "competition version changed mid-run")
        _check(("politics" in record) == ("politics" in previous_record), "political ledger missing or introduced mid-run")
    _check(gov["relief"]["delivered"] == sum(s["quantity"] for s in gov["relief"]["shipments"]),
           "total relief differs from actual deliveries")
    for stage in ("works", "relief"):
        _check(gov[stage]["cost_food"] == sum(s["cost_food"] for s in gov[stage]["shipments"]),
               "public freight cost differs from shipments")
    regions = _by(record["regions"], "id")
    depots = _by(gov["depots"], "region")
    levies = _by(gov["levies"], "region")
    accounts = _by(gov["accounts"], "id")
    _check(regions.keys() == depots.keys() == levies.keys(), "physical warehouses differ from regions")
    pub = {i: d["opening"].copy() for i, d in depots.items()}
    private = {i: r["opening"]["stock"].copy() for i, r in regions.items()}
    cash = {i: r["opening"]["cash"] for i, r in regions.items()}
    reserved, restored = Counter(), Counter()
    transfers = {i: dict.fromkeys(GOODS, 0) for i in regions}
    countries = _by(record["countries"], "id")
    _check(countries.keys() == accounts.keys(), "fiscal and private country accounts differ")
    combined = {owner: a["combined_open"].copy() for owner, a in accounts.items()}
    for i, r in regions.items():
        _check(depots[i]["owner"] == levies[i]["owner"] == r["owner"] and _valid(pub[i]),
               "invalid warehouse ownership or opening")
        prod = r["production"]
        for g in GOODS:
            inc = prod["produced"][g] - prod["used"][g]
            private[i][g] += inc
            combined[r["owner"]][g] += inc - r["consumption"]["used"][g]
    for t in record["border_market"]["trades"]:
        a, b, g = t["seller"], t["buyer"], t["good"]
        cash[a] += t["value"]
        cash[b] -= t["value"]
        for book, seller, buyer in ((private, a, b), (combined, regions[a]["owner"], regions[b]["owner"])):
            book[seller][g] -= t["quantity"]
            book[buyer][g] += t["quantity"]
            book[seller]["food"] -= t["cost_food"]
    for p in gov["works"]["projects"]:
        reserved[p["target"]] += p["workers"]
        restored[p["target"]] += p["soil_gain"]
        for g in GOODS:
            # Each delivered kit is consumed immediately at the worksite.
            pub[p["source"]][g] -= p["used"][g]
            combined[p["owner"]][g] -= p["used"][g]
    for s in gov["works"]["shipments"]:
        pub[s["source"]]["food"] -= s["cost_food"]
        combined[s["owner"]]["food"] -= s["cost_food"]
    for i, l in levies.items():
        _check(l["private_open"] == private[i] and l["depot_open"] == pub[i], "collection opening mismatch")
        for g in GOODS:
            q, fee = l["levied"][g], l["handling_used"][g]
            _check(0 <= fee <= q <= private[i][g] and l["deposited"][g] == q-fee, "invalid levy receipt")
            private[i][g] -= q
            transfers[i][g] -= q
            pub[i][g] += q-fee
            combined[l["owner"]][g] -= fee
        _check(l["private_close"] == private[i] and l["depot_close"] == pub[i], "collection closing mismatch")
    for s in gov["relief"]["shipments"]:
        a, b, qty, fee = s["source"], s["target"], s["quantity"], s["cost_food"]
        _check(regions[a]["owner"] == regions[b]["owner"] == s["owner"], "foreign domestic relief")
        pub[a]["food"] -= qty + fee
        private[b]["food"] += qty
        transfers[b]["food"] += qty
        combined[s["owner"]]["food"] -= fee
    for i, d in depots.items():
        _check(_valid(pub[i]) and d["spoil_food"] == pub[i]["food"]//12, "public storage loss mismatch")
        pub[i]["food"] -= d["spoil_food"]
        combined[d["owner"]]["food"] -= d["spoil_food"]
        _check(pub[i] == d["closing"], "warehouse balance differs from postings")
    for node in record["domestic"]["nodes"]:
        _check(node["opening"] == private[node["id"]], "private freight opening mismatch")
    for s in record["domestic"]["shipments"]:
        a, b, g = s["source"], s["target"], s["good"]
        private[a][g] -= s["quantity"]
        private[b][g] += s["quantity"]
        private[a]["food"] -= s["cost_food"]
        combined[regions[a]["owner"]]["food"] -= s["cost_food"]
    for i, r in regions.items():
        for g in GOODS:
            private[i][g] -= r["consumption"]["used"][g]
        _check(private[i] == r["closing"]["stock"] and _valid(private[i]), "regional private balance")
        _check(cash[i] == r["closing"]["cash"] and cash[i] >= 0, "regional border cash balance")
        p = r["production"]
        _check(reserved[i] + p["workers"] + p["soil_care"]["workers"] + p["investment"]["construction_labor"]
               == r["opening"]["population"] // 2, "public and private worker allocation")
        _check(r["opening"]["soil"] + restored[i] == p["soil_before"], "public soil treatment")
    audit_national_year(record, private_transfers=transfers)
    _check(sum(c["closing"]["cash"] - c["opening"]["cash"] for c in countries.values()) == 0, "world cash change")
    decisions = {i: a["decision"] for i, a in accounts.items()}
    _check(gov["accounts"] == country_accounts(record, decisions), "fiscal summaries differ from postings")
    for owner, a in accounts.items():
        _check(combined[owner] == a["combined_close"], "consolidated national balance")
    _road_audit(record)
    audit_appropriations(record, previous_record=previous_record)
    if "politics" in record:
        from .politics import audit_political_states
        audit_political_states(record, previous_record=previous_record)
    if "competition" in record:
        from .competition import audit_cabinets
        audit_cabinets(record, previous_record)
