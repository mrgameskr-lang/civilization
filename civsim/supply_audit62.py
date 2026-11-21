"""Independent public/private, border and local physical audits for the depot economy."""
from collections import Counter
from types import SimpleNamespace

from .aid_budget61 import audit_fiscal61
from .appropriation_audit import audit_appropriations
from .border import border_market, move_people
from .civic_fiscal import withheld_labor
from .diplomacy61 import audit_rules61
from .diplomatic_flows import _audit_aid, _network
from .depot_supply62 import audit_depot_supply
from .government_audit import _by, _check, _valid, country_accounts
from .model import GOODS
from .public_works import ROAD_BONUS, audit_works
from .regional_engine import audit_borders, audit_national_year
from .supply_border62 import audit_envelope, charge_border


def accounts62(record, decisions):
    accounts = country_accounts(record, decisions)
    duty = {r["id"]:r for r in record.get("service", {}).get("regions", [])}
    for account in accounts:
        n = account["id"]
        totals = account["totals"]
        supply = next(c for c in record["supply"]["countries"] if c["owner"] == n)
        totals["depot_freight_food"] = supply["aid_freight_food"] + supply["domestic_freight_food"]
        totals["public_freight_food"] += totals["depot_freight_food"]
        totals["public_cargo"] += sum(e["supply_use"] for e in record["government"]["roads"] if e["owner"] == n)
        if duty:
            local = [r for r in duty.values() if r["owner"] == n]
            totals["duty_workers"] = sum(r["serving"] for r in local)
            totals["duty_rations"] = sum(r["ration_food"] for r in local)
            totals["duty_tools"] = sum(r["used"]["tools"] for r in local)
            totals["duty_travel_food"] = sum(r["used"]["food"]-r["ration_food"] for r in local)
    return accounts


def _roads(record):
    government = record["government"]
    edges = {(e["a"],e["b"]):e for e in government["roads"]}
    civil = {(e["a"],e["b"]):e for e in record["domestic"]["roads"]}
    _check(edges.keys() == civil.keys() and len(edges) == len(government["roads"]), "duplicate or missing road")
    loads, projects = Counter(), Counter()
    for kind, stage in (("works_use",government["works"]), ("supply_use",record["supply"]),
                        ("relief_use",government["relief"]), ("private_use",record["domestic"])):
        for trip in stage["shipments"]:
            for leg in trip["legs"]:
                key = tuple(sorted((leg["a"],leg["b"])))
                _check(key in edges, "unknown freight road")
                loads[key,kind] += trip["quantity"]
    for trip in record.get("service", {}).get("moves", []):
        key = tuple(sorted((trip["home"],trip["station"])))
        _check(key in edges, "unknown posting road")
        loads[key,"duty_use"] += trip["road_load"]
    for p in government["works"]["projects"]:
        if p["edge"] is not None:
            projects[tuple(p["edge"]),p["action"]] += 1
    kinds = ("works_use","supply_use","duty_use","relief_use","private_use")
    for key,e in edges.items():
        _check(all(e[k] == loads[key,k] >= 0 for k in kinds), "overlapping domestic capacity")
        _check(0 <= projects[key,"service"] <= e["opening_units"] and
               e["closing_units"] == projects[key,"service"] + projects[key,"build"], "unfunded capacity")
        _check(e["capacity"] == e["base"] + ROAD_BONUS*e["opening_units"] and
               e["next_capacity"] == e["base"] + ROAD_BONUS*e["closing_units"] and
               e["unused"] == e["capacity"] - sum(e[k] for k in kinds) >= 0 and
               civil[key]["capacity"] == e["unused"] + e["private_use"], "domestic road residual mismatch")


def _accounts(record, previous_record=None):
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
    duties = {r["id"]:r for r in record.get("service", {}).get("regions", [])}
    for s in record["supply"]["shipments"]:
        a, b, g = s["source"], s["target"], s["good"]
        n = regions[a]["owner"]
        _check(n == regions[b]["owner"] == s["owner"], "warehouse transfer crossed national boundary")
        pub[a][g] -= s["quantity"]
        pub[a]["food"] -= s["cost_food"]
        pub[b][g] += s["quantity"]
        combined[n]["food"] -= s["cost_food"]
        _check(_valid(pub[a]), "overdrawn public dispatch")
    for i, duty in duties.items():
        for g in GOODS:
            pub[i][g] -= duty["used"][g]
            combined[regions[i]["owner"]][g] -= duty["used"][g]
        _check(_valid(pub[i]), "unfunded public duty")
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
        ration = duties[i]["ration_food"] if duties else 0
        private[i]["food"] += ration
        transfers[i]["food"] += ration
        combined[r["owner"]]["food"] += ration
        for g in GOODS:
            private[i][g] -= r["consumption"]["used"][g]
        _check(private[i] == r["closing"]["stock"] and _valid(private[i]), "regional private balance")
        _check(cash[i] == r["closing"]["cash"] and cash[i] >= 0, "regional border cash balance")
        p = r["production"]
        if civic is not None:
            _check(p["withheld_workers"]==withheld[i],"unavailable civic labor differs from group actions")
        _check(withheld.get(i,0) + (duties[i]["serving"] if duties else 0) + reserved[i] + p["workers"] + p["soil_care"]["workers"] + p["investment"]["construction_labor"]
               == r["opening"]["population"] // 2, "public and private worker allocation")
        _check(r["opening"]["soil"] + restored[i] == p["soil_before"], "public soil treatment")
    audit_national_year(record, private_transfers=transfers)
    _check(sum(c["closing"]["cash"] - c["opening"]["cash"] for c in countries.values()) == 0, "world cash change")
    decisions = {i: a["decision"] for i, a in accounts.items()}
    _check(gov["accounts"] == accounts62(record, decisions), "fiscal summaries differ from postings")
    for owner, a in accounts.items():
        _check(combined[owner] == a["combined_close"], "consolidated national balance")
    _roads(record)
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


def audit62(record, *, geography, previous_record=None, program=None):
    """Check a standalone annual entry against its immutable map and, optionally, its predecessor."""
    if "public_policy" not in record:
        _check(previous_record is None or "public_policy" not in previous_record, "control followed a different arm")
        return audit_fiscal61(record, geography=geography, previous_record=previous_record)
    cfg = record["public_policy"]
    arm = cfg["arm"]
    _check(arm in ("B","C","D") and (arm != "B") == ("service" in record) == (program is not None),
           "public program missing or mismatched")
    _check(cfg["model_version"] == ("6.0B1" if arm=="B" else "6.0B2") and
           cfg["diagnostic"] in (None,"hold_supply","hold_recruitment") and
           cfg["supply_enabled"] is (cfg["diagnostic"] != "hold_supply") and
           cfg["recruit"] is (cfg["diagnostic"] != "hold_recruitment") and
           (cfg["diagnostic"] != "hold_recruitment" or program is not None), "invalid policy intervention")
    if previous_record is not None:
        prev = previous_record.get("public_policy", {})
        _check(prev.get("arm") == arm and prev.get("diagnostic") is None, "incompatible opening policy")
        local_prev = {r["id"]:r["closing"] for r in previous_record["regions"]}
        dep_prev = {d["region"]:d["closing"] for d in previous_record["government"]["depots"]}
        _check(all(r["opening"] == local_prev[r["id"]] for r in record["regions"]) and
               all(d["opening"] == dep_prev[d["region"]] for d in record["government"]["depots"]),
               "discontinuous resident or warehouse custody")
    gov, ctx = record["government"], record["diplomacy"]
    _check(ctx["phase61"]["arm"]=="F" and ctx["intervention"] is None, "the public economy requires the capped border")
    rows = _by(record["regions"], "id")
    places = {r.id:r for r in geography.regions}
    _check(places.keys()==rows.keys(), "wrong region map")
    local = [SimpleNamespace(**r["opening"], members=places[i].members) for i,r in rows.items()]
    nodes = {r.id:r for r in local}
    plans = {a["id"]:a["decision"] for a in gov["accounts"]}
    previous = {o["region"]:o["previous"] for d in plans.values() for o in d["observations"]}
    initial = {d["region"]:d["opening"].copy() for d in gov["depots"]}
    work = gov["works"]
    roads = geography.roads
    units = {(e["a"],e["b"]):e["opening_units"] for e in gov["roads"]}
    withheld = withheld_labor(local,record["collective"])
    duty = {r["id"]:r for r in record.get("service",{}).get("regions",[])}
    occupied = {i:w+(duty[i]["serving"] if duty else 0) for i,w in withheld.items()}
    audit_works(local,roads,initial,units,plans,work,width=geography.width,withheld=occupied)
    balances = {r["id"]:r["depot_close"].copy() for r in work["nodes"]}
    after_works = {(e["a"],e["b"]):e["remaining"] for e in work["roads"]}
    after_soil = {w["id"]:w["soil_close"] for w in work["nodes"]}
    for r in local:
        r.soil = after_soil[r.id]
    audit_depot_supply(local,roads,geography.borders,balances,after_works,ctx,previous,record["supply"],
                       width=geography.width,emergency=cfg["supply_enabled"],forward=cfg["supply_enabled"])
    balances = {n["id"]:n["closing"].copy() for n in record["supply"]["nodes"]}
    if duty:
        if previous_record is not None:
            previous_roster = {r["id"]:r["closing_roster"] for r in previous_record["service"]["regions"]}
        elif record["year"] == 1:
            previous_roster = program.start_service(local)
        else:
            previous_roster = {i:r["opening_roster"] for i,r in duty.items()}
        remaining = {(e["a"],e["b"]):e["remaining"] for e in record["supply"]["roads"]}
        program.audit_service(record["service"], regions=local, roster=previous_roster, diplomacy_ctx=ctx,
                              withheld=withheld,depots=balances,roads=roads,residual=remaining,
                              vitals={i:r["demography"] for i,r in rows.items()})
        _check(record["service"]["mode"] == ("fixed" if arm=="C" else "adaptive") and
               record["service"]["recruit"] is cfg["recruit"], "unapproved roster policy")
        for i,r in duty.items():
            for g in GOODS:
                balances[i][g] -= r["used"][g]
    borders = _network(ctx["physical"], nodes)
    _check(borders == sorted(geography.borders,key=lambda e:(e.a,e.b)) and
           ctx["physical"]["width"]==geography.width, "international network mismatch")
    domestic_only, exported = Counter(), Counter()
    for trip in record["supply"]["shipments"]:
        if trip["good"] == "food" and trip["purpose"] == "domestic_reserve":
            domestic_only[trip["target"]] += trip["quantity"]
    for invoice in ctx["physical"]["aid"]["shipments"]:
        exported[invoice["source"]] += invoice["quantity"] + invoice["cost_food"]
    _check(all(q <= max(0,balances[i]["food"]-domestic_only[i]) for i,q in exported.items()),
           "unappropriated domestic food used for foreign dispatch or freight")
    _audit_aid(record,nodes,borders,balances)
    audit_envelope(ctx,record["supply"])
    access = charge_border(ctx,local,borders,geography.width,balances,record["supply"])
    for r in local:
        p = rows[r.id]["production"]
        r.stock = {g:r.stock[g]+p["produced"][g]-p["used"][g] for g in GOODS}
    produced = {r.id:{"stock":r.stock.copy(),"cash":r.cash} for r in local}
    market = border_market(local,borders,access=access)
    _check(market == record["border_market"], "private market not settled against actual border residual")
    taxes = {l["region"]:l for l in gov["levies"]}
    audit_borders(local,borders,market,produced,{i:(taxes[i]["private_open"],rows[i]["closing"]["cash"]) for i in rows})
    for r in local:
        r.stock = rows[r.id]["closing"]["stock"].copy()
    vital,moves = move_people(local,{i:r["consumption"] for i,r in rows.items()},[*roads,*borders],access=access)
    _check(moves == record["moves"] and all(vital[i]==r["demography"] for i,r in rows.items())
           and access.trace()==ctx["physical"], "foreign receipts or migration differ")
    _accounts(record, previous_record)
    audit_rules61(record, previous_record)
