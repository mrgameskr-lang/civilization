"""Read-only checks of actual resident meals, warehouse issues and integer roster exits."""
from collections import Counter, defaultdict

from .government_audit import _by, _check
from .model import GOODS


def _quantity(value):
    _check(type(value) is int and value >= 0, "expected an unsigned integer receipt")
    return value


def audit_meal_custody(record):
    regions = _by(record["regions"], "id")
    freight = _by(record["domestic"]["nodes"], "id")
    duties = _by(record["service"]["regions"], "id")
    levies = _by(record["government"]["levies"], "region")
    relief = _by(record["government"]["relief"]["nodes"], "id")
    _check(regions.keys() == freight.keys() == duties.keys() == levies.keys() == relief.keys(), "different meal accounts")
    movement = record["unit_game"]["receipt"]
    issues = _by(record.get("unit_upkeep", {}).get("groups", []), "location")
    relief_first = record.get("unit_upkeep", {}).get("priority") == "relief_first"
    _check(issues.keys() <= regions.keys(), "unknown depot in local inventory issue")
    receipts = []
    for home, region in sorted(regions.items()):
        node, duty = freight[home], duties[home]
        public = levies[home]["depot_close"].copy()
        if movement and movement["ok"] and movement["source"]==home:
            public["food"] -= _quantity(movement["food_spent"])
        if home in issues and not relief_first:
            for good in ("food", "tools"):
                public[good] -= _quantity(issues[home][good])
        _check(all(_quantity(public[g]) == relief[home]["depot_open"][g] for g in GOODS),
               "public custody after movement differs from the opening for relief")
        if home in issues and relief_first:
            group = issues[home]
            after = relief[home]["depot_close"].copy()
            _check(group["before"] == after, "checkout does not start at the relief closing balance")
            for good in ("food", "tools"):
                after[good] -= _quantity(group[good])
            _check(after == group["after"] and all(_quantity(q) >= 0 for q in after.values()),
                   "post-relief checkout differs from receipt")
        issued = _quantity(duty["ration_food"])
        fee, wear = _quantity(duty["travel_food"]), _quantity(duty["tools_used"])
        paid = {"food": issued + fee, "ore": 0, "tools": wear}
        _check(duty["used"] == paid and all(_quantity(duty["opening_depot"][g]) - paid[g] ==
               _quantity(duty["closing_depot"][g]) for g in GOODS), "service warehouse spending differs")
        _check(duty["owner"] == node["owner"] == region["owner"], "meal custodian differs")
        private = _quantity(node["closing"]["food"])
        need = _quantity(region["opening"]["population"])
        opening = private + issued
        eaten = min(need, opening)
        spoil = (opening - eaten) // 12
        left = opening - eaten - spoil
        meal = region["consumption"]
        _check((meal["opening_food"],meal["food_need"],meal["food_eaten"],meal["food_unmet"],
                meal["food_spoiled"],meal["closing_food"]) ==
               (opening,need,eaten,need-eaten,spoil,left) and
               meal["used"] == {"food":eaten+spoil,"ore":0,"tools":0} and
               region["closing"]["stock"]["food"] == left, "ordinary meal and public release differ")
        receipts.append({"home":home,"public_before_relief":public,"private_before_public":private,"public_issue":issued,
                         "travel_food":fee,"tools_used":wear,"meal_open":opening,"food_need":need,
                         "food_eaten":eaten,"food_unmet":need-eaten,"spoil":spoil,"food_left":left})
    return receipts


def _positions(away, staff, field):
    bins = {h:Counter({h:_quantity(r[field])}) for h,r in staff.items()}
    seen = set()
    for home,loc,n in away:
        _check(home in staff and loc in staff and home != loc and staff[home]["owner"]==staff[loc]["owner"] and
               (home,loc) not in seen and _quantity(n)>0, "invalid visiting location")
        seen.add((home,loc))
        bins[home][home] -= n
        _check(bins[home][home]>=0, "more visitors than home registrations")
        bins[home][loc] = n
    return bins


def position_exits(turn, roster):
    """Allocate *observed* exits in the order used by annual-unit/1.

    Remove at home first and then at visiting locations in reverse ID order.
    Report integer counts, with no inference about an individual resident.
    """
    staff = _by(roster, "id")
    bins = _positions(turn["opening_away"],staff,"opening_roster")
    exits = defaultdict(lambda: {"released":0,"deaths":0,"emigrants":0})

    def deduct(cause, field):
        for home, locations in bins.items():
            remaining = _quantity(staff[home][field])
            for loc in (home,*sorted((i for i in locations if i!=home),reverse=True)):
                if not remaining:
                    break
                count = min(remaining, locations[loc])
                if count:
                    locations[loc] -= count
                    remaining -= count
                    exits[home,loc][cause] += count
            _check(remaining==0, "exit exceeds people present")

    def visitors():
        return [[h,i,n] for h,counts in sorted(bins.items()) for i,n in sorted(counts.items()) if i!=h and n]

    deduct("released","released")
    _check(visitors()==turn["retained_away"], "release location differs from retained visitors")
    for home,r in staff.items():
        bins[home][home] += _quantity(r["enrolled"])
        _check(sum(bins[home].values())==r["serving"], "registration and release do not close")
    receipt = turn.get("receipt")
    if receipt and receipt["ok"]:
        h,a,b = receipt["home"],receipt["source"],receipt["destination"]
        n = _quantity(receipt["count"])
        _check(h in bins and a in staff and b in staff and a!=b and n>0 and bins[h][a]>=n and
               staff[h]["owner"]==staff[a]["owner"]==staff[b]["owner"], "invalid position transfer")
        bins[h][a] -= n
        bins[h][b] += n
    _check(visitors()==turn["after_move_away"], "position change without an accepted transfer")
    deduct("deaths","service_deaths")
    deduct("emigrants","service_emigrants")
    _check(visitors()==turn["closing_away"] and
           all(sum(bins[h].values())==_quantity(r["closing_roster"]) for h,r in staff.items()),
           "unexplained change at a closing location")
    return [{"home":h,"location":loc,**counts} for (h,loc),counts in sorted(exits.items())]


class CustodyObserver:
    """Read consecutive annual receipts. Office and location remain separate marginals."""

    def __init__(self):
        self.offices = {}
        self.latest = None

    def observe(self, record):
        from .postings65 import advance_postings, audit_postings
        from .resident_exits import audit_resident_exits
        from .unit_economy import location_totals
        service = record["service"]
        year = record["year"]
        prior_year = self.latest["year"] if self.latest is not None else 0
        _check(year == prior_year + 1, "missing opening office register")
        offices, next_book = advance_postings(self.offices,service,year=year)
        audit_postings(offices,service)
        result = {"year":year, "home_accounts":audit_resident_exits(record["regions"],service["regions"]),
                  "office_counts":offices["closing"], "present_counts":location_totals(record,"closing"),
                  "location_exits":position_exits(record["unit_game"],service["regions"]),
                  "meal_receipts":audit_meal_custody(record)}
        self.offices, self.latest = next_book, result
