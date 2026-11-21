"""One local inventory checkout per turn for up to two player-marked game pieces."""
from collections import Counter
from dataclasses import asdict, dataclass

from .government_audit import _check
from .inventory_sets import take_sets

VERSION = "annual-unit-upkeep/1"
RELIEF_FIRST_VERSION = "annual-unit-upkeep/2"


@dataclass(frozen=True)
class Upkeep:
    home: int
    count: int

    def __post_init__(self):
        if type(self.home) is not int or self.home < 0 or type(self.count) is not int or self.count not in (1, 2):
            raise ValueError("select one or two existing pieces from a home region")


def _places(home, away, total):
    counts = Counter({loc: n for h, loc, n in away if h == home})
    counts[home] = total - sum(counts.values())
    _check(counts[home] >= 0, "visiting pieces exceed the home register")
    return counts


def _mark(config, places):
    # When enabling on an existing save, mark existing visitors first.
    left = config.count
    marked = []
    for loc in sorted(places, key=lambda i: (i == config.home, i)):
        n = min(places[loc], left)
        if n:
            marked.append([loc, n, 0])
            left -= n
    return sorted(marked)


def settle(config, previous, turn, service, depots, *, relief_first=False):
    """Pay from the live local balance after movement. Never enroll replacements."""
    home = config.home
    region = next((r for r in service["regions"] if r["id"] == home), None)
    _check(region is not None, "unknown home region for game pieces")
    opening = _places(home, turn["opening_away"], region["opening_roster"])
    start = _mark(config, opening) if previous is None else [row.copy() for row in previous]
    counts = Counter()
    for loc, n, paid in start:
        _check(type(loc) is int and loc in opening and type(n) is int and type(paid) is int
               and loc not in counts and 0 <= paid <= n <= opening[loc] and n > 0, "invalid opening game pieces")
        counts[loc] = n
    _check(start == sorted(start) and sum(counts.values()) <= config.count, "duplicate or excess game pieces")
    retained = _places(home, turn["retained_away"], region["opening_roster"] - region["released"])
    kept = Counter({loc: min(n, retained[loc]) for loc, n in counts.items()})
    released = sum(counts.values()) - sum(kept.values())
    receipt = turn["receipt"]
    moved = 0
    if receipt and receipt["ok"] and receipt["home"] == home:
        src, dst = receipt["source"], receipt["destination"]
        moved = min(kept[src], receipt["count"])
        kept[src] -= moved
        kept[dst] += moved

    present = _places(home, turn["after_move_away"], region["serving"])
    groups = []
    for loc, n in sorted(kept.items()):
        if not n:
            continue
        _check(n <= present[loc], "marked pieces exceed physical location")
        stock = depots[loc]
        before = stock.copy()
        paid = take_sets(stock, n)
        groups.append({"home":home, "location":loc, "nominal":n, "supplied":paid, "unsupplied":n-paid,
                       "food":paid, "tools":paid, "before":before, "after":stock.copy()})
    result = {"version":VERSION, "selection":asdict(config), "first_turn":previous is None, "opening":start,
              "released":released, "marked_moved":moved, "groups":groups}
    if relief_first:
        result.update(version=RELIEF_FIRST_VERSION, priority="relief_first")
    return result


def close(ledger, turn, service):
    """Keep marked pieces last in each location's exit queue, paid pieces last among those marked."""
    home = ledger["selection"]["home"]
    staff = next(r for r in service["regions"] if r["id"] == home)
    available = _places(home, turn["closing_away"], staff["closing_roster"])
    closing = []
    exits = 0
    for g in ledger["groups"]:
        loc = g["location"]
        n = min(g["nominal"], available[loc])
        exits += g["nominal"] - n
        if n:
            closing.append([loc, n, min(n, g["supplied"])])
    ledger.update(closing=closing, demographic_exits=exits)
