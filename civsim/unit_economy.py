"""Player-issued moves on the generated economy's existing domestic edges."""
from collections import Counter
from dataclasses import asdict, dataclass

from .government_audit import _check
from .unit_board import assess_crossing

VERSION = "annual-unit/1"


@dataclass(frozen=True)
class Move:
    home: int
    source: int
    destination: int
    count: int

    def __post_init__(self):
        if not all(type(i) is int and i >= 0 for i in (self.home, self.source, self.destination, self.count)):
            raise ValueError("expected nonnegative integer region IDs and count")


@dataclass
class AnnualUnitGame:
    economy: object

    @property
    def away(self):
        return [list(row) for row in self.economy.unit_positions or ()]


def _away_counts(rows, roster, owners):
    counts = Counter()
    prev = None
    for row in rows:
        _check(type(row) is list and len(row) == 3 and all(type(i) is int for i in row), "invalid position row")
        home, location, n = row
        key = (home, location)
        _check(home in owners and location in owners and owners[home] == owners[location] and
               home != location and n > 0 and (prev is None or prev < key), "invalid or duplicate away group")
        counts[home] += n
        _check(counts[home] <= roster[home], "away count exceeds home roster")
        prev = key
    return counts


def _retain(rows, limits):
    # No individual IDs. Remove exits from the home location first, then the
    # highest-numbered visiting location. New registrations always start at home.
    left = limits.copy()
    result = []
    for home, location, n in rows:
        kept = min(left[home], n)
        if kept:
            result.append([home, location, kept])
            left[home] -= kept
    return result


def begin_turn(opening, command, service):
    from copy import deepcopy
    staff = service["regions"]
    _away_counts(opening, {r["id"]:r["opening_roster"] for r in staff}, {r["id"]:r["owner"] for r in staff})
    retained = _retain(opening, {r["id"]:r["opening_roster"]-r["released"] for r in staff})
    return {"version": VERSION, "opening_away": deepcopy(opening), "retained_away": retained,
            "command": asdict(command) if command is not None else None}


def absent_from_home(turn):
    totals = Counter()
    for home, _, n in turn["retained_away"]:
        totals[home] += n
    return totals


def apply_move(turn, service, roads, depots, remaining):
    """Debit the live post-collection depot and pre-relief shared capacity together."""
    away = {(h, loc): n for h, loc, n in turn["retained_away"]}
    order = turn["command"]
    receipt = None
    if order is not None:
        move = Move(**order)
        home, src, dst, q = move.home, move.source, move.destination, move.count
        staff = {r["id"]:r for r in service["regions"]}
        edge = tuple(sorted((src, dst)))
        owner = staff[home]["owner"] if home in staff else None
        valid = (src in staff and dst in staff and owner is not None and
                 staff[src]["owner"] == staff[dst]["owner"] == owner and edge in remaining and
                 any((e.a,e.b) == edge for e in roads))
        tokens = 0
        if home in staff:
            row = staff[home]
            tokens = (max(0, row["opening_roster"]-row["released"]-absent_from_home(turn)[home]-row["reassignment_out"])
                      if src == home else away.get((home,src),0))
        food = depots[src]["food"] if src in depots else None
        capacity = remaining.get(edge)
        reason, cost, load = (assess_crossing(count=q,tokens=tokens,food=food,remaining=capacity)
                              if valid else ("invalid_edge",0,0))
        ok = reason == "moved"
        if ok:
            if src != home:
                away[home,src] -= q
            if dst != home:
                away[home,dst] = away.get((home,dst),0)+q
            depots[src]["food"] -= cost
            remaining[edge] -= load
        receipt = {**order, "ok":ok, "reason":reason, "owner":owner, "road":list(edge) if valid else None,
                   "eligible_at_source":tokens, "food_before":food, "food_after":depots[src]["food"] if src in depots else None,
                   "remaining_before":capacity, "remaining_after":remaining.get(edge), "food_spent":cost, "road_used":load}
    turn["receipt"] = receipt
    turn["after_move_away"] = [[h,loc,n] for (h,loc),n in sorted(away.items()) if n]


def close_turn(turn, service):
    turn["closing_away"] = _retain(turn["after_move_away"], {r["id"]:r["closing_roster"] for r in service["regions"]})


def location_totals(record, when):
    """Count physical presence once per registered resident at the opening or close."""
    _check(when in ("opening","closing"), "choose opening or closing")
    staff = record["service"]["regions"]
    residents = {r["id"]:r[when+"_roster"] for r in staff}
    owners = {r["id"]:r["owner"] for r in staff}
    away = record["unit_game"][when+"_away"]
    _away_counts(away,residents,owners)
    totals = residents.copy()
    for home, location, q in away:
        totals[home] -= q
        totals[location] += q
    return totals


def audit_positions(turn, service):
    """Check transfer double entry and bound all other changes by observed roster exits."""
    def table(name):
        return Counter({(h,loc):n for h,loc,n in turn[name]})

    opening, retained, moved, closing = (table(k) for k in
        ("opening_away","retained_away","after_move_away","closing_away"))
    actual = moved.copy()
    actual.subtract(retained)
    expected = Counter()
    receipt = turn["receipt"]
    if receipt and receipt["ok"]:
        h, a, b, q = (receipt[k] for k in ("home","source","destination","count"))
        _check(receipt["food_before"]-receipt["food_after"]==receipt["food_spent"]==q and
               receipt["remaining_before"]-receipt["remaining_after"]==receipt["road_used"]==q,
               "unit crossing cost differs from head count")
        if a!=h:
            expected[h,a]-=q
        if b!=h:
            expected[h,b]+=q
    _check(actual==expected and retained<=opening and closing<=moved, "unreceipted change of location")
    released, exits = Counter(), Counter()
    for (h,_), n in (opening-retained).items():
        released[h] += n
    for (h,_), n in (moved-closing).items():
        exits[h] += n
    for r in service["regions"]:
        _check(released[r["id"]]<=r["released"] and exits[r["id"]]<=r["service_deaths"]+r["service_emigrants"],
               "unit lost without a resident roster exit")
    for when in ("opening","closing"):
        location_totals({"service":service,"unit_game":turn},when)


def step_game(game, command=None, *, upkeep=None, relief_first=None, public_farm=None):
    """Run a full year of the existing fixed 6.0B2 economy and commit its closing positions."""
    from . import service62
    from .supply62 import advance62
    year = game.economy.world.year + 1
    return advance62(game.economy, year, "C", program=service62, mode="fixed",
                     unit_input=(game.away, command), upkeep=upkeep, relief_first=relief_first,
                     public_farm=public_farm)


def audit_game(record, geography, previous=None):
    """Replay the physical annual stages and separately check household and roster balances."""
    from .peace62 import audit62
    from .posting_engine65 import audit_households
    _check(record.get("unit_game",{}).get("version")==VERSION, "missing annual game record")
    audit62(record, geography=geography, previous_record=previous)
    audit_households(record,previous=previous)
