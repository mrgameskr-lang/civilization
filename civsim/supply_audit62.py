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
from .logistics import audit_logistics
from .model import GOODS
from .public_harvest import RESERVE_POLICIES
from .public_works import ROAD_BONUS, audit_relief, audit_works, residual_roads
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
        if "emergency_relief" in record:
            trips = [s for s in record["emergency_relief"]["shipments"] if s["owner"] == n]
            totals["emergency_food"] = sum(s["quantity"] for s in trips)
            totals["emergency_freight_food"] = sum(s["cost_food"] for s in trips)
            totals["public_freight_food"] += totals["emergency_freight_food"]
            totals["public_cargo"] += sum(e["emergency_use"] for e in record["government"]["roads"] if e["owner"] == n)
        if "unit_game" in record:
            receipt = record["unit_game"]["receipt"]
            totals["unit_move_food"] = receipt["food_spent"] if receipt and receipt["owner"] == n else 0
        if "unit_upkeep" in record:
            groups = [g for g in record["unit_upkeep"]["groups"] if duty[g["home"]]["owner"] == n]
            for good in ("food", "tools"):
                totals["unit_upkeep_"+good] = sum(g[good] for g in groups)
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
    stages = [("works_use",government["works"]), ("supply_use",record["supply"]),
              ("relief_use",government["relief"]), ("private_use",record["domestic"])]
    if "emergency_relief" in record:
        stages.append(("emergency_use", record["emergency_relief"]))
    for kind, stage in stages:
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
    if "emergency_relief" in record:
        kinds += ("emergency_use",)
    if "unit_game" in record:
        kinds += ("unit_use",)
        receipt = record["unit_game"]["receipt"]
        if receipt and receipt["ok"]:
            loads[tuple(receipt["road"]), "unit_use"] += receipt["count"]
    for key,e in edges.items():
        _check(all(e[k] == loads[key,k] >= 0 for k in kinds), "overlapping domestic capacity")
        _check(0 <= projects[key,"service"] <= e["opening_units"] and
               e["closing_units"] == projects[key,"service"] + projects[key,"build"], "unfunded capacity")
        _check(e["capacity"] == e["base"] + ROAD_BONUS*e["opening_units"] and
               e["next_capacity"] == e["base"] + ROAD_BONUS*e["closing_units"] and
               e["unused"] == e["capacity"] - sum(e[k] for k in kinds) >= 0 and
               civil[key]["capacity"] == e["unused"] + e["private_use"], "domestic road residual mismatch")


def _charge_sets(groups, pub, combined, regions):
    for g in groups:
        i = g["location"]
        _check(g["before"] == pub[i] and g["food"] == g["tools"] == g["supplied"]
               == min(pub[i]["food"], pub[i]["tools"], g["nominal"]), "invalid local inventory issue")
        for good in ("food","tools"):
            pub[i][good] -= g[good]
            combined[regions[i]["owner"]][good] -= g[good]
        _check(g["after"] == pub[i] and _valid(pub[i]), "local inventory closing differs")


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
    for h in record.get("public_harvest", {}).get("regions", ()):
        i, q = h["id"], h["food_public"]
        private[i]["food"] -= q
        transfers[i]["food"] -= q
        pub[i]["food"] += q
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
    receipt = record.get("unit_game",{}).get("receipt")
    if receipt and receipt["ok"]:
        i = receipt["source"]
        _check(pub[i]["food"] == receipt["food_before"], "unit move depot opening differs")
        pub[i]["food"] -= receipt["food_spent"]
        combined[regions[i]["owner"]]["food"] -= receipt["food_spent"]
        _check(pub[i]["food"] == receipt["food_after"] >= 0, "unit move depot closing differs")
    issue = record.get("unit_upkeep", {})
    relief_first = issue.get("priority") == "relief_first"
    if not relief_first:
        _charge_sets(issue.get("groups", ()), pub, combined, regions)
    for s in gov["relief"]["shipments"]:
        a, b, qty, fee = s["source"], s["target"], s["quantity"], s["cost_food"]
        _check(regions[a]["owner"] == regions[b]["owner"] == s["owner"], "foreign domestic relief")
        pub[a]["food"] -= qty + fee
        private[b]["food"] += qty
        transfers[b]["food"] += qty
        combined[s["owner"]]["food"] -= fee
    if relief_first:
        _charge_sets(issue["groups"], pub, combined, regions)
    for s in record.get("emergency_relief", {}).get("shipments", ()):
        a, b, q, fee = s["source"], s["target"], s["quantity"], s["cost_food"]
        owner = regions[a]["owner"]
        _check(owner == s["owner"] == regions[b]["owner"] and 0 < q <= pub[a]["food"] - fee and fee >= 0,
               "unfunded emergency delivery")
        pub[a]["food"] -= q+fee
        private[b]["food"] += q
        transfers[b]["food"] += q
        combined[owner]["food"] -= fee
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


def _audit_domestic_delivery(record, geography):
    """Reconstruct the balance and physical network at each domestic dispatch boundary."""
    gov = record["government"]
    levies = _by(gov["levies"],"region")
    places = {r.id:r for r in geography.regions}
    local = []
    for row in record["regions"]:
        i = row["id"]
        place = SimpleNamespace(**row["opening"],members=places[i].members)
        place.stock = levies[i]["private_close"].copy()
        local.append(place)
    depots = {i:l["depot_close"].copy() for i,l in levies.items()}
    plans = {a["id"]:a["decision"] for a in gov["accounts"]}
    admin = {r["id"]:r["admin_remaining"] for r in record["collective"]["responses"]}
    stage = record.get("supply",gov["works"])
    left = {(e["a"],e["b"]):e["remaining"] for e in stage["roads"]}
    for move in record.get("service",{}).get("moves",[]):
        edge = tuple(sorted((move["home"],move["station"])))
        _check(edge in left and left[edge]>=move["road_load"]>=0,"unfunded travel before domestic relief")
        left[edge] -= move["road_load"]
    if "unit_game" in record:
        from .unit_economy import Move, apply_move, audit_positions, begin_turn, close_turn
        game = record["unit_game"]
        cmd = Move(**game["command"]) if game["command"] is not None else None
        rebuilt = begin_turn(game["opening_away"],cmd,record["service"])
        apply_move(rebuilt,record["service"],geography.roads,depots,left)
        close_turn(rebuilt,record["service"])
        _check(rebuilt == game, "unit receipt, position or population differs from replay")
        audit_positions(game,record["service"])
    issue = record.get("unit_upkeep")
    relief = gov["relief"]
    relief_first = issue is not None and issue.get("priority") == "relief_first"
    if relief_first:
        from .public_works import execute_relief
        expected, _ = execute_relief(local, geography.roads, depots, plans, left, admin, width=geography.width)
        _check(expected == relief, "relief-first dispatch differs from replay")
    if issue is not None:
        from .unit_upkeep import Upkeep, close, settle
        opening = None if issue["first_turn"] else issue["opening"]
        replay = settle(Upkeep(**issue["selection"]), opening, game, record["service"], depots, relief_first=relief_first)
        close(replay, game, record["service"])
        _check(replay == issue, "local game inventory differs from replay")
    if not relief_first:
        audit_relief(local,geography.roads,depots,plans,left,admin,relief,width=geography.width)
    relief_nodes = _by(relief["nodes"],"id")
    for place in local:
        place.stock["food"] = relief_nodes[place.id]["private_food_close"]
    left = {(e["a"],e["b"]):e["remaining"] for e in relief["roads"]}
    if "emergency_relief" in record:
        from .emergency_relief import execute_emergency_relief
        from .storage import canonical_line
        if not relief_first:
            depots = {i:n["depot_close"].copy() for i,n in relief_nodes.items()}
        paid = {r["id"]:r["ration_food"] for r in record.get("service", {}).get("regions", [])}
        if not paid:
            paid = dict.fromkeys(depots, 0)
        expected, left = execute_emergency_relief(local, geography.roads, depots, left, relief, paid, width=geography.width)
        _check(canonical_line(expected) == canonical_line(record["emergency_relief"]), "emergency relief differs from replay")
    _check(record["domestic"]["mode"]=="limited","private road capacity must be finite")
    audit_logistics(local,residual_roads(geography.roads,left),record["domestic"],width=geography.width)


def audit62(record, *, geography, previous_record=None, program=None):
    """Check a standalone annual entry against its immutable map and, optionally, its predecessor."""
    if "public_policy" not in record:
        _check(previous_record is None or "public_policy" not in previous_record, "control followed a different arm")
        for entry in (record,previous_record):
            if entry is not None:
                ctx = entry.get("diplomacy",{})
                _check(ctx.get("phase61",{}).get("arm")=="F" and ctx.get("intervention") is None
                       and "supply" not in entry and "service" not in entry and "unit_upkeep" not in entry
                       and "public_harvest" not in entry and "emergency_relief" not in entry and "research" not in entry
                       and "diffusion" not in entry,
                       "control requires the ordinary historical F policy")
        audit_fiscal61(record, geography=geography, previous_record=previous_record)
        _audit_domestic_delivery(record,geography)
        return
    cfg = record["public_policy"]
    harvest = record.get("public_harvest")
    reserve_policy = cfg.get("reserve_policy")
    _check("reserve_policy" not in cfg or (type(reserve_policy) is str and reserve_policy in RESERVE_POLICIES
           and harvest is not None), "invalid reserve policy")
    _check(("emergency_relief" in record) == (reserve_policy == "emergency"), "emergency authorization mismatch")
    prior_policy = (previous_record or {}).get("public_policy", {}).get("reserve_policy")
    _check(prior_policy in (None, reserve_policy), "reserve policy continuity")
    _check(("public_harvest" in record) == ("harvest_rule" in cfg)
           and (harvest is not None or "public_harvest" not in record)
           and (harvest is not None or "public_harvest" not in (previous_record or {})),
           "missing or discontinuous public harvest rule")
    arm = cfg["arm"]
    game = record.get("unit_game")
    if game is not None or "unit_rule" in cfg:
        from .unit_economy import VERSION
        _check(game is not None and arm=="C" and cfg.get("unit_rule")==game["version"]==VERSION,
               "invalid game rule")
        if previous_record is not None or record["year"]==1:
            prior_positions = (previous_record or {}).get("unit_game",{}).get("closing_away",[])
            _check(game["opening_away"]==prior_positions, "discontinuous unit positions")
    elif previous_record is not None:
        _check("unit_game" not in previous_record, "lost unit position ledger")
    issue = record.get("unit_upkeep")
    prior = (previous_record or {}).get("unit_upkeep")
    if issue is not None or "upkeep_rule" in cfg or prior is not None:
        from .unit_upkeep import RELIEF_FIRST_VERSION, VERSION as UPKEEP_VERSION
        expected = RELIEF_FIRST_VERSION if (issue or {}).get("priority") == "relief_first" else UPKEEP_VERSION
        _check(game is not None and issue is not None and cfg.get("upkeep_rule") == issue["version"] == expected
               and type(issue["first_turn"]) is bool, "missing or invalid game inventory version")
        if previous_record is not None or record["year"] == 1:
            _check(issue["first_turn"] is (prior is None), "unexpected game inventory activation")
        if prior is not None:
            _check(issue["opening"] == prior["closing"] and issue["selection"] == prior["selection"]
                   and issue["version"] == prior["version"],
                   "game inventory status not carried across turns")
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
    from .research71 import audit as audit_research
    from . import diffusion72
    exchange, migration_roads = diffusion72.audit_opening(record, previous_record, local, roads)
    knowledge = diffusion72.by_region(exchange) if exchange is not None else None
    trial_targets, farm_levels = audit_research(record, previous_record, local, plans, knowledge=knowledge)
    audit_works(local,roads,initial,units,plans,work,width=geography.width,withheld=occupied,trial_targets=trial_targets)
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
        options = {}
        if game is not None:
            from .unit_economy import absent_from_home, begin_turn
            options["away"] = absent_from_home(begin_turn(game["opening_away"],None,record["service"]))
        program.audit_service(record["service"], regions=local, roster=previous_roster, diplomacy_ctx=ctx,
                              withheld=withheld,depots=balances,roads=roads,residual=remaining,
                              vitals={i:r["demography"] for i,r in rows.items()}, **options)
        _check(record["service"]["mode"] == ("fixed" if arm=="C" else "adaptive") and
               record["service"]["recruit"] is cfg["recruit"], "unapproved roster policy")
        for i,r in duty.items():
            for g in GOODS:
                balances[i][g] -= r["used"][g]
    borders = _network(ctx["physical"], nodes)
    public_crop = {}
    if harvest is not None or farm_levels is not None:
        from .model import climate_factor
        from .public_harvest import harvest_row, harvest_version
        from .regional_production import audit_production
        from .storage import canonical_line
        # The producer's receipt is also untrusted on replay. Anchor gross food,
        # productive labor and land to independent resident and public-works accounts.
        gross_open = {i:{**r["opening"], "soil":after_soil[i]} for i,r in rows.items()}
        gross_close = {i:{**r["opening"], "stock":r["production"]["closing_stock"],
                          **{k:r["closing"][k] for k in ("soil","capital","deposit")}} for i,r in rows.items()}
        labor = {w["id"]:occupied[w["id"]] + w["workers_reserved"] for w in work["nodes"]}
        weather = {n.id:climate_factor(geography.seed, record["year"], n.id) for n in geography.nations}
        _check(all(r["climate"] == weather[r["owner"]] for r in rows.values()), "crop climate differs from seed")
        audit_production(gross_open, gross_close, {i:r["production"] for i,r in rows.items()},
                         weather, public_labor=labor, farm_levels=farm_levels)
    if harvest is not None:
        reserve_days = RESERVE_POLICIES.get(reserve_policy)
        version = harvest_version(reserve_days)
        expected = [harvest_row(i, rows[i]["owner"], rows[i]["production"], initial[i], balances[i], reserve_days=reserve_days)
                    for i in sorted(rows)]
        _check(cfg["harvest_rule"] == version and
               canonical_line(harvest) == canonical_line({"version":version, "regions":expected}),
               "public harvest allocation mismatch")
        for h in expected:
            i, q = h["id"], h["food_public"]
            public_crop[i] = q
            balances[i]["food"] += q
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
        r.stock["food"] -= public_crop.get(r.id, 0)
    produced = {r.id:{"stock":r.stock.copy(),"cash":r.cash} for r in local}
    market = border_market(local,borders,access=access)
    _check(market == record["border_market"], "private market not settled against actual border residual")
    taxes = {l["region"]:l for l in gov["levies"]}
    audit_borders(local,borders,market,produced,{i:(taxes[i]["private_open"],rows[i]["closing"]["cash"]) for i in rows})
    for r in local:
        r.stock = rows[r.id]["closing"]["stock"].copy()
    vital,moves = move_people(local,{i:r["consumption"] for i,r in rows.items()},[*migration_roads,*borders],access=access)
    _check(moves == record["moves"] and all(vital[i]==r["demography"] for i,r in rows.items())
           and access.trace()==ctx["physical"], "foreign receipts or migration differ")
    if exchange is not None:
        diffusion72.audit_closing(exchange, record, moves, roads)
    _accounts(record, previous_record)
    _audit_domestic_delivery(record,geography)
    audit_rules61(record, previous_record)
