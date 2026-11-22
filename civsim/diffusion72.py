"""One farm method, carried only by a realized domestic migration receipt."""
from .audit import BalanceError
from .storage import canonical_line


VERSION = "farm-exchange/1"
_RECEIPT_FIELDS = {"year", "move_index", "source", "target", "people", "distance"}


def _check(condition, message):
    if not condition:
        raise BalanceError(message)


def migration_roads(roads, blocked):
    """The diagnostic closure removes one undirected edge solely from migration."""
    if blocked is None:
        return roads
    _check(type(blocked) is tuple and len(blocked) == 2 and
           all(type(i) is int for i in blocked) and blocked[0] < blocked[1],
           "expected a sorted pair of domestic migration endpoints")
    usable = [e for e in roads if (e.a, e.b) != blocked]
    _check(len(usable) + 1 == len(roads), "migration closure requires an actual domestic road")
    return usable


def by_region(ledger):
    return {r["id"]:r for r in ledger["regions"]}


def opening(regions, roads, memory, research, year, blocked):
    prior = {r["id"]:r for r in memory or ()}
    studied = {r["id"]:r for r in research or ()}
    _check(memory is None or (len(regions) == len(memory) and prior.keys() == {r.id for r in regions}),
           "incomplete diffusion memory")
    distances = {(e.a, e.b):e.distance for e in roads}
    rows = []
    for site in sorted(regions, key=lambda r:r.id):
        state = studied.get(site.id, {})
        learned = state.get("adoption_year")
        saved = prior.get(site.id, {})
        contact = saved.get("contact")
        method = saved.get("method") if memory is not None else ("independent" if learned is not None else None)
        _check((learned is None or (type(learned) is int and learned < year)) and
               method in (None,"independent","transfer") and ((method is None) == (learned is None)),
               "origin does not agree with local mastery")
        if contact is not None:
            _check(isinstance(contact, dict) and contact.keys() == _RECEIPT_FIELDS and
                   all(type(n) is int for n in contact.values()) and contact["target"] == site.id and
                   contact["people"] > 0 and contact["move_index"] >= 0 and 0 < contact["year"] < year and
                   distances.get(tuple(sorted((contact["source"],site.id)))) == contact["distance"] and
                   (learned is None or contact["year"] < learned),
                   "invalid historical migration contact")
            source_year = studied.get(contact["source"], {}).get("adoption_year")
            _check(type(source_year) is int and source_year < contact["year"],
                   "historical migration source lacked opening mastery")
            contact = contact.copy()
        if method is not None:
            required_trials = 1 if method == "transfer" else 2
            _check(state.get("trials") == required_trials and (method != "transfer" or contact is not None),
                   "mastery origin does not match paid trials or opening contact")
        rows.append({"id":site.id, "owner":site.owner, "opening_contact":contact, "closing_contact":contact,
                     "opening_method":method, "closing_method":method, "new_contact":False})
    return {"version":VERSION, "first_turn":memory is None, "blocked_migration":list(blocked) if blocked else None,
            "regions":rows}


def finish(ledger, research, moves, roads, year):
    sites = by_region(ledger)
    for study in research["regions"]:
        site = sites[study["id"]]
        if study["level_after"] and not study["level_before"]:
            site["closing_method"] = "independent" if study["closing_trials"] == 2 else "transfer"
    distances = {(e.a, e.b):e.distance for e in roads}
    for index, move in enumerate(moves):
        source, target = sites[move["source"]], sites[move["target"]]
        if (source["opening_method"] is None or source["owner"] != target["owner"] or
            target["closing_method"] is not None or target["closing_contact"] is not None):
            continue
        edge = tuple(sorted((source["id"],target["id"])))
        _check(move["people"] > 0 and distances.get(edge) == move["distance"] and
               list(edge) != ledger["blocked_migration"], "invalid domestic knowledge receipt")
        target["closing_contact"] = {"year":year, "move_index":index, **move}
        target["new_contact"] = True


def closing(ledger):
    return [{"id":r["id"], "contact":r["closing_contact"].copy() if r["closing_contact"] else None,
             "method":r["closing_method"]} for r in ledger["regions"]]


def audit_opening(record, previous, local, roads):
    """Check consecutive years when available, or validate a standalone opening boundary."""
    ledger = record.get("diffusion")
    cfg = record["public_policy"]
    prev = (previous or {}).get("diffusion")
    if ledger is None:
        _check("diffusion_rule" not in cfg and "diffusion" not in record and prev is None, "missing diffusion rule")
        return None, roads
    year = record["year"]
    _check(cfg.get("diffusion_rule") == ledger["version"] == VERSION and record.get("research") is not None and
           type(ledger["first_turn"]) is bool, "invalid diffusion selection")
    blocked = ledger["blocked_migration"]
    _check(blocked is None or type(blocked) is list, "invalid migration closure ledger")
    edge = None if blocked is None else tuple(blocked)
    routes = migration_roads(roads, edge)
    if previous is not None or year == 1:
        _check(ledger["first_turn"] is (prev is None), "unexpected diffusion activation")
    memory = None
    if prev is not None:
        memory = closing(prev)
    elif not ledger["first_turn"]:
        memory = [{"id":r["id"], "method":r["opening_method"], "contact":r["opening_contact"]} for r in ledger["regions"]]
    research = [{"id":r["id"], "trials":r["opening_trials"], "adoption_year":r["opening_adoption_year"]}
                for r in record["research"]["regions"]]
    return opening(local, roads, memory, research, year, edge), routes


def audit_closing(expected, record, verified_moves, roads):
    finish(expected, record["research"], verified_moves, roads, record["year"])
    _check(canonical_line(expected) == canonical_line(record["diffusion"]), "unreconciled knowledge exchange")
