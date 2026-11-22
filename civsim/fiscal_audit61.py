"""Versioned fiscal posting audit for 6.0A.1. The legacy dispatcher embeds the 6.0A policy."""
from collections import Counter
from types import SimpleNamespace

from .appropriation_audit import audit_appropriations
from .government_audit import _by, _check, _road_audit, _valid, country_accounts
from .model import GOODS
from .regional_engine import audit_national_year


def audit_accounts61(record, previous_record=None):
    gov = record["government"]
    if previous_record is not None:
        _check(("competition" in record) == ("competition" in previous_record), "competition version changed mid-run")
        _check(("politics" in record) == ("politics" in previous_record), "political ledger missing or introduced mid-run")
        _check(("diplomacy" in record) == ("diplomacy" in previous_record), "foreign policy version changed mid-run")
    _check(gov["relief"]["delivered"] == sum(s["quantity"] for s in gov["relief"]["shipments"]),
           "total relief differs from actual deliveries")
    for stage in ("works", "relief"):
        _check(gov[stage]["cost_food"] == sum(s["cost_food"] for s in gov[stage]["shipments"]),
               "public freight cost differs from shipments")
    regions = _by(record["regions"], "id")
    depots = _by(gov["depots"], "region")
    levies = _by(gov["levies"], "region")
    accounts = _by(gov["accounts"], "id")
    civic = record.get("collective")
    withheld = {}
    if civic is not None:
        from .civic_fiscal import withheld_labor
        _check(record.get("competition",{}).get("arm")=="C" and record["competition"]["tax_policy"]=="fixed",
               "invalid civic treatment baseline")
        withheld = withheld_labor([SimpleNamespace(**r["opening"]) for r in regions.values()],civic)
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
    if "diplomacy" in record:
        for s in record["diplomacy"]["physical"]["aid"]["shipments"]:
            a,b = s["source"],s["target"]
            outgoing = s["quantity"] + s["cost_food"]
            _check(regions[a]["owner"]==s["donor"]!=s["recipient"]==regions[b]["owner"]
                   and pub[a]["food"]>=outgoing, "aid exceeds its local public appropriation")
            pub[a]["food"] -= outgoing
            pub[b]["food"] += s["received"]
            combined[s["donor"]]["food"] -= outgoing
            combined[s["recipient"]]["food"] += s["received"]
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
        if civic is not None:
            _check(p["withheld_workers"]==withheld[i],"unavailable civic labor differs from group actions")
        _check(withheld.get(i,0) + reserved[i] + p["workers"] + p["soil_care"]["workers"] + p["investment"]["construction_labor"]
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
    if civic is not None:
        from .collective import audit_actions
        audit_actions(record,previous_record)
