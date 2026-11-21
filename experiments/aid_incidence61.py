"""One-year food incidence with the same production, government approvals and border laws."""
from types import SimpleNamespace

from civsim.border import border_market
from civsim.civic_fiscal import collect_civic
from civsim.diplomatic_flows import ForeignFlows
from civsim.economy import consume
from civsim.logistics import ship
from civsim.public_works import execute_relief, residual_roads


def replay_meals(row, geography, shipments):
    """Settle a supplied subset of the audited shipments, then recompute all downstream food uses."""
    gov = row["government"]
    places = {r.id:r for r in geography.regions}
    regions = []
    for entry in row["regions"]:
        opening = entry["opening"]
        regions.append(SimpleNamespace(**{**opening, "members":places[entry["id"]].members,
                                         "stock":entry["production"]["closing_stock"].copy()}))
    public = {n["id"]:n["depot_close"].copy() for n in gov["works"]["nodes"]}
    # The published directions already contain each government's effective trade and migration permissions.
    access = ForeignFlows(row["diplomacy"],regions,geography.borders,geography.width)
    for s in shipments:
        source, target = s["source"], s["target"]
        public[source]["food"] -= s["quantity"] + s["cost_food"]
        public[target]["food"] += s["received"]
        access.aid_used[tuple(sorted((source,target)))] += s["quantity"]
    border_market(regions,geography.borders,access=access)
    plans = {c["id"]:c["decision"] for c in gov["accounts"]}
    collect_civic(regions,public,plans,row["collective"])
    available = {(e["a"],e["b"]):e["capacity"]-e["works_use"] for e in gov["roads"]}
    limits = {c["id"]:c["admin_remaining"] for c in row["collective"]["responses"]}
    _, remaining = execute_relief(regions,geography.roads,public,plans,available,limits,width=geography.width)
    ship(regions,residual_roads(geography.roads,remaining),"limited",width=geography.width)
    return {r.id:consume(r) for r in regions}


def meal_incidence(row, geography):
    """Actual food eaten minus meals without any international public cargo in this year."""
    actual = {r["id"]:r["consumption"] for r in row["regions"]}
    shipments = row["diplomacy"]["physical"]["aid"]["shipments"]
    if not shipments:
        return dict.fromkeys(actual,0)
    if replay_meals(row,geography,shipments) != actual:
        raise ValueError("post-production replay with the original invoices differs from the actual meal ledger")
    without = replay_meals(row,geography,())
    return {i:meal["food_eaten"]-without[i]["food_eaten"] for i,meal in actual.items()}
