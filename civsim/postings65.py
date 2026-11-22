"""Nominal office affiliation of residents on the fixed peacetime register.

The closed economic year is read-only. An inherited round-trip receipt is
evidence for one office entry, never evidence of residence at that office.
"""
from .regions import _split


def _check(ok, reason):
    if not ok:
        raise ValueError("nominal affiliation: " + reason)


def _natural(value):
    return type(value) is int and value >= 0


def start_postings(regions):
    """The register opens empty alongside the original resident roll."""
    ids = [r["id"] if isinstance(r, dict) else r.id for r in regions]
    _check(all(_natural(i) for i in ids) and len(ids) == len(set(ids)), "invalid home office IDs")
    return {}


def _rows(book):
    return [{"home": h, "post": p, "count": q} for (h,p),q in sorted(book.items()) if q]


def _read(rows):
    book = {}
    for row in rows:
        _check(set(row) == {"home","post","count"}, "unexpected register columns")
        h,p,q = row["home"],row["post"],row["count"]
        _check(all(_natural(v) for v in (h,p,q)) and q and (h,p) not in book,
               "duplicate or invalid register row")
        book[h,p] = q
    _check(rows == _rows(book), "noncanonical register order")
    return book


def _homes(service):
    _check(service["mode"] == "fixed" and service["stage"] == "closed", "closed fixed roll required")
    regions = {}
    for r in service["regions"]:
        i = r["id"]
        _check(all(_natural(r[k]) for k in ("id","owner","population","opening_roster","enrolled",
                                            "released","serving","service_deaths","service_emigrants","closing_roster")),
               "invalid resident count")
        _check(i not in regions and r["released"] <= r["opening_roster"] <= r["population"]
               and r["serving"] == r["opening_roster"] - r["released"] + r["enrolled"]
               and r["serving"] <= r["population"]
               and r["serving"] - r["service_deaths"] - r["service_emigrants"] == r["closing_roster"],
               "source home census does not close")
        regions[i] = r
    return regions


def _home_totals(book, regions, field):
    totals = dict.fromkeys(regions, 0)
    for key,q in book.items():
        _check(type(key) is tuple and len(key) == 2 and all(_natural(i) for i in key)
               and _natural(q) and q > 0, "invalid home/office balance")
        h,p = key
        _check(h in regions and p in regions and regions[h]["owner"] == regions[p]["owner"],
               "unknown or foreign affiliation")
        totals[h] += q
    _check(all(q == regions[h][field] for h,q in totals.items()), f"{field} differs from source roll")


def _deduct(book, regions, field):
    """A home total leaves its offices in proportion to their positive counts."""
    removed = {}
    grouped = {h: [] for h in regions}
    for h,p in sorted(book):
        grouped[h].append(p)
    for h,posts in grouped.items():
        weights = [book[h,p] for p in posts]
        total = regions[h][field]
        _check(total <= sum(weights), "exit exceeds remaining home roll")
        for p,q in zip(posts, _split(total,weights), strict=True):
            if q:
                removed[h,p] = q
                book[h,p] -= q
                if not book[h,p]:
                    del book[h,p]
    return removed


def _invoices(service, regions):
    seen = set()
    totals = dict.fromkeys(regions, 0)
    for index,invoice in enumerate(service["moves"]):
        h,p,q = invoice["home"],invoice["station"],invoice["people"]
        distance = invoice["distance"]
        _check(all(_natural(v) for v in (h,p,q,distance,invoice["owner"],invoice["road_load"],invoice["travel_food"]))
               and h in regions and p in regions and h != p and q > 0 and distance > 0
               and regions[h]["owner"] == invoice["owner"] == regions[p]["owner"]
               and (h,p) not in seen, "invalid or duplicate source receipt")
        _check(invoice["road_load"] == 2*q and invoice["travel_food"] == (2*q*distance + 99)//100,
               "source round-trip receipt does not balance")
        totals[h] += q
        _check(totals[h] <= regions[h]["serving"], "source receipts exceed its resident register")
        seen.add((h,p))
        yield index,h,p,q


def _selected_hold(hold):
    if hold is None:
        return None
    _check(isinstance(hold,(tuple,list)) and len(hold) == 3 and all(_natural(i) for i in hold)
           and hold[0] == hold[1] != hold[2], "invalid hold")
    return tuple(hold)


def advance_postings(opening, service, *, hold=None, year=None):
    """Return the yearly nominal ledger and sparse closing (home,office) counts.

    Input receipts stay in the order finalized by the existing economy. Only
    entries still at their home office can acquire an outside affiliation.
    Holding an entry cannot offer the same residents to a later receipt.
    """
    regions = _homes(service)
    _check(year is None or (_natural(year) and year > 0), "invalid register year")
    _check(year != 1 or not opening, "first year requires an empty register")
    hold = _selected_hold(hold)
    book = dict(opening)
    _home_totals(book,regions,"opening_roster")
    ledger = {"year":year, "hold":list(hold) if hold else None, "opening":_rows(book)}
    ledger["released"] = _rows(_deduct(book,regions,"released"))
    intake = {(i,i):r["enrolled"] for i,r in regions.items() if r["enrolled"]}
    for key,q in intake.items():
        book[key] = book.get(key,0) + q
    ledger["enrolled"] = _rows(intake)
    eligible = {i:book.get((i,i),0) for i in regions}
    assignments = []
    did_hold = False
    for index,h,p,q in _invoices(service,regions):
        before = eligible[h]
        accepted = min(before,q)
        held = hold == (h,h,p)
        assigned = 0 if held else accepted
        if held:
            _check(accepted > 0, "hold requires a positive normal entry")
            did_hold = True
        eligible[h] -= accepted
        if assigned:
            book[h,h] -= assigned
            if not book[h,h]:
                del book[h,h]
            book[h,p] = book.get((h,p),0) + assigned
        reason = ("held" if held else "no_unassigned" if not assigned else
                  "partial" if assigned < q else "assigned")
        assignments.append({"invoice":index, "home":h, "source":h, "destination":p,
                            "invoice_people":q, "eligible":before, "assigned":assigned,
                            "held":held, "reason":reason})
    _check(hold is None or did_hold, "hold does not match a normal entry")
    _home_totals(book,regions,"serving")
    ledger["assignments"] = assignments
    ledger["during"] = _rows(book)
    ledger["deaths"] = _rows(_deduct(book,regions,"service_deaths"))
    ledger["emigrants"] = _rows(_deduct(book,regions,"service_emigrants"))
    _home_totals(book,regions,"closing_roster")
    ledger["closing"] = _rows(book)
    return ledger, book


def audit_postings(ledger, service, *, previous=None):
    """Independently reconcile each office's entries/exits, then replay the rule."""
    banks = {k:_read(ledger[k]) for k in ("opening","released","enrolled","during","deaths","emigrants","closing")}
    if previous is not None:
        _check(_natural(previous["year"]) and previous["year"] > 0 and _natural(ledger["year"])
               and ledger["year"] == previous["year"] + 1, "nonconsecutive years")
        _check(_read(previous["closing"]) == banks["opening"], "prior offices do not carry")
    regions = _homes(service)
    for key,field in (("opening","opening_roster"),("released","released"),("enrolled","enrolled"),
                      ("during","serving"),("deaths","service_deaths"),("emigrants","service_emigrants"),
                      ("closing","closing_roster")):
        _home_totals(banks[key],regions,field)
    balances = dict(banks["opening"])
    for stage,sign in (("released",-1),("enrolled",1)):
        for key,q in banks[stage].items():
            balances[key] = balances.get(key,0) + sign*q
            _check(balances[key] >= 0, "negative office balance")
    for row in ledger["assignments"]:
        h,p,q = row["home"],row["destination"],row["assigned"]
        _check(_natural(q) and q <= balances.get((h,h),0), "overdrawn home office")
        balances[h,h] = balances.get((h,h),0) - q
        balances[h,p] = balances.get((h,p),0) + q
    _check(_rows(balances) == ledger["during"], "office assignment balance differs")
    for stage in ("deaths","emigrants"):
        for key,q in banks[stage].items():
            balances[key] = balances.get(key,0)-q
            _check(balances[key] >= 0, "overdrawn office exit")
    _check(_rows(balances) == ledger["closing"], "office closing balance differs")
    expected,_ = advance_postings(banks["opening"],service,hold=ledger["hold"],year=ledger["year"])
    _check(ledger == expected and all(type(r["held"]) is bool and
           all(_natural(r[k]) for k in ("invoice","home","source","destination","invoice_people","eligible","assigned"))
           for r in ledger["assignments"]), "source, eligibility or proportional exit differs")
