"""Classify unfilled two-item purchases from actual balances at checkout."""
from civsim.model import GOODS

COLUMNS = ("region", "year", "home", "marked", "paid", "missing_food_only", "missing_tools_only",
           "missing_both", "before_food", "before_tools", "after_food", "after_tools",
           "movement_food", "old_public_issue_food", "old_public_travel_food", "old_public_tools",
           "relief_open_food", "relief_close_food", "private_delivered_food", "food_eaten", "food_unmet")


def shortage(n, food, tools):
    """Give each available item to the lowest numbered slot; classify each slot exactly once."""
    if any(type(x) is not int or x < 0 for x in (n, food, tools)):
        raise ValueError("invalid inventory balance")
    f, t = min(n, food), min(n, tools)
    return min(f,t), max(0,t-f), max(0,f-t), n-max(f,t)


def checkout_rows(record):
    issue = record.get("unit_upkeep", {})
    after_relief = issue.get("priority") == "relief_first"
    groups = {g["location"]: g for g in issue.get("groups", [])}
    move = record["unit_game"]["receipt"]
    levy = {r["region"]:r for r in record["government"]["levies"]}
    relief = {r["id"]:r for r in record["government"]["relief"]["nodes"]}
    service = {r["id"]:r for r in record["service"]["regions"]}
    private = {r["id"]:r for r in record["domestic"]["nodes"]}
    rows = {}
    for r in record["regions"]:
        i = r["id"]
        fee = move["food_spent"] if move and move["ok"] and move["source"] == i else 0
        boundary = levy[i]["depot_close"].copy()
        boundary["food"] -= fee
        if after_relief:
            if boundary != relief[i]["depot_open"]:
                raise ValueError("wrong relief opening balance")
            boundary = relief[i]["depot_close"]
        g = groups.get(i)
        n = g["nominal"] if g else 0
        paid, food_only, tool_only, both = shortage(n, boundary["food"], boundary["tools"])
        after = {k:boundary[k] - (paid if k in ("food","tools") else 0) for k in GOODS}
        if g and (g["before"] != boundary or g["after"] != after or g["supplied"] != paid
                  or g["unsupplied"] != food_only + tool_only + both or g["food"] != g["tools"] or g["food"] != paid):
            raise ValueError("classified purchases differ from actual checkout")
        if not after_relief and after != relief[i]["depot_open"]:
            raise ValueError("unreceipted expense before relief")
        s = service[i]
        rows[i] = [i, record["year"], g["home"] if g else None, n, paid, food_only, tool_only, both,
                   boundary["food"],boundary["tools"],after["food"],after["tools"],fee,s["ration_food"],
                   s["travel_food"],s["tools_used"],relief[i]["depot_open"]["food"],relief[i]["depot_close"]["food"],
                   private[i]["imports"]["food"],r["consumption"]["food_eaten"],r["consumption"]["food_unmet"]]
    if set(groups) - rows.keys():
        raise ValueError("checkout at a missing region")
    return rows
