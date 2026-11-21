"""Reconstruct annual fiscal authorizations from opening balances and observed lags."""
from collections import Counter
from types import SimpleNamespace

from .audit import BalanceError
from .fiscal_policy import audit_collection, decide
from .model import GOODS
from .regions import Road


def _check(condition, message):
    if not condition:
        raise BalanceError("fiscal appropriation: " + message)


def _indexed(rows, fields):
    keys = [tuple(row[k] for k in fields) for row in rows]
    _check(len(set(keys)) == len(rows), "duplicate " + ", ".join(fields))
    return {key[0] if len(key) == 1 else key: row for key, row in zip(keys, rows, strict=True)}


def _decision_view(d):
    """A JSON archive represents live edge tuples as lists."""
    copy = {**d, "candidates": [dict(c) for c in d["candidates"]]}
    for c in [copy, *copy["candidates"]]:
        if c["target_edge"] is not None:
            c["target_edge"] = tuple(c["target_edge"])
    if copy["action"] == "road":
        copy["target"] = tuple(copy["target"])
    return copy


def _previous_observation(r):
    return {"unmet": r["consumption"]["food_unmet"], "food_need": r["consumption"]["food_need"],
            "food_output": r["production"]["produced"]["food"],
            "pop_delta": r["closing"]["population"]-r["opening"]["population"],
            "soil_delta": r["closing"]["soil"]-r["opening"]["soil"]}


def _spending(gov, plans):
    spending = {i: Counter() for i in plans}
    project_ids = {}
    for p in gov["works"]["projects"]:
        owner, action = p["owner"], p["action"]
        _check(p["project_id"] not in project_ids and owner in plans, "unknown or duplicate project")
        project_ids[p["project_id"]] = (owner, action)
        if action == "service":
            continue
        d = plans[owner]
        _check((action == "build" and d["action"] == "road" and tuple(p["edge"]) == tuple(d["target_edge"]))
               or (action == "soil" and d["action"] == "soil" and p["target"] == d["target_region"]),
               "project has no matching authorization")
        spending[owner].update({g: p["used"][g] for g in GOODS})
        spending[owner]["workers"] += p["workers"]
        spending[owner]["admin_units"] += 1
    for s in gov["works"]["shipments"]:
        owner, action = project_ids[s["project_id"]]
        _check((s["owner"], s["purpose"]) == (owner, action), "unattributed project freight")
        if action != "service":
            spending[owner]["food"] += s["cost_food"]
    delivery = Counter()
    for s in gov["relief"]["shipments"]:
        owner = s["owner"]
        d = plans[owner]
        _check(d["action"] == "relief" and s["target"] == d["target_region"], "unauthorized relief")
        delivery[owner] += s["quantity"]
        spending[owner]["food"] += s["quantity"]+s["cost_food"]
    for r in gov["levies"]:
        owner, gross = r["owner"], r["extra_levy"]["food"]
        if gross:
            spending[owner]["admin_units"] += 1
            spending[owner]["food"] += gross
    admin = _indexed(gov["relief"]["admin"], ("owner",))
    _check(admin.keys() == plans.keys(), "missing relief administration account")
    for owner, d in plans.items():
        spending[owner]["admin_units"] += int(delivery[owner] > 0)
        throughput = d["relief_throughput"] if gov["mode"] != "none" else 0
        _check(admin[owner]["used"] == delivery[owner] <= d["relief_limit"] <= throughput == admin[owner]["limit"],
               "unsupported relief disbursement")
        _check(all(0 <= spending[owner][k] <= limit for k, limit in d["budget"].items()),
               "discretionary spending exceeds appropriation")


def _audit(record, previous_record):
    gov = record["government"]
    regions = _indexed(record["regions"], ("id",))
    depots = _indexed(gov["depots"], ("region",))
    accounts = _indexed(gov["accounts"], ("id",))
    roads = _indexed(gov["roads"], ("a","b"))
    civilian = _indexed(record["domestic"]["roads"], ("a","b"))
    _check(roads.keys()==civilian.keys() and regions.keys()==depots.keys(), "inconsistent opening network")
    regional = {i: SimpleNamespace(**r["opening"]) for i,r in regions.items()}
    stocks = {i: d["opening"] for i,d in depots.items()}
    _check(all(i==r.id and r.owner==regions[i]["owner"]==depots[i]["owner"] for i,r in regional.items()),
           "inconsistent opening ownership")
    _check(set(accounts)=={r.owner for r in regional.values()}, "missing country account")
    if previous_record is not None:
        _check(previous_record["year"]+1==record["year"] and previous_record["government"]["mode"]==gov["mode"],
               "previous record is outside this policy or time period")
        prior_regions = _indexed(previous_record["regions"], ("id",))
        prior_roads = _indexed(previous_record["government"]["roads"], ("a","b"))
        _check(prior_regions.keys()==regions.keys() and prior_roads.keys()==roads.keys(), "previous geography differs")
    plans = {}
    for owner, a in accounts.items():
        d = a["decision"]
        _check(a["mode"]==gov["mode"] and d["owner"]==owner, "decision ownership or regime")
        local = [r for r in regional.values() if r.owner==owner]
        observations = _indexed(d["observations"], ("region",))
        _check(set(observations)=={r.id for r in local}, "observation coverage")
        previous = {}
        for r in local:
            old = observations[r.id]["previous"]
            _check(all(type(n) is int for n in old.values())
                   and 0 <= old["unmet"] <= old["food_need"] and old["food_output"]>=0,
                   "invalid reported previous observation")
            if record["year"] == 1:
                _check(not any(old.values()), "first-year decision contains previous observations")
            else:
                _check(old["food_need"] + old["pop_delta"] == r.population, "historical population mismatch")
            if previous_record is not None:
                _check(old==_previous_observation(prior_regions[r.id]), "decision used incorrect lagged observation")
            previous[r.id] = old
        network, units, usage = [], {}, {}
        road_options = [c for c in d["candidates"] if c["action"]=="road"]
        lags = {tuple(c["target_edge"]): c["inputs"]["previous_used"] for c in road_options}
        for key, row in roads.items():
            start, end = key
            _check(regional[start].owner == regional[end].owner == row["owner"], "foreign planning road")
            if row["owner"] != owner:
                continue
            network.append(Road(start, end, civilian[key]["distance"], row["base"], ()))
            units[key], usage[key] = row["opening_units"], lags[key]
            _check(type(usage[key]) is int and usage[key]>=0 and (record["year"]!=1 or usage[key]==0),
                   "invalid prior congestion")
            if previous_record is not None:
                last = prior_roads[key]
                _check(usage[key] == last["capacity"]-last["unused"], "decision used incorrect prior road loads")
        expected = decide(owner, local, network, stocks, previous, units, gov["mode"], usage)
        if "competition" in record:
            from .competition import audit_competition_plan
            expected = audit_competition_plan(record, expected)
        elif "politics" in record:
            from .politics import audit_plan
            expected = audit_plan(record["politics"], expected)
        _check(_decision_view(d)==expected, "decision differs from opening state, eligible candidates or budget")
        plans[owner] = expected
    if record.get("competition", {}).get("tax_policy") == "platform":
        from .tax_policy5c import audit_collection_with_rates
        tariffs = {c["id"]: c["tariff"] for c in record["competition"]["countries"]}
        audit_collection_with_rates(regional.values(), plans, gov["mode"], gov["levies"], tariffs)
    else:
        audit_collection(regional.values(), plans, gov["mode"], gov["levies"])
    _spending(gov, plans)


def audit_appropriations(record, *, previous_record=None):
    """Audit approvals and taxes in memory or after JSON decoding.

    Later-year histories are reported inputs in a standalone annual record. Pass the prior year
    to verify their provenance. Archive verification also replays the complete causal history.
    """
    try:
        _audit(record, previous_record)
    except (KeyError, TypeError, IndexError) as error:
        raise BalanceError("malformed fiscal authorization record") from error
