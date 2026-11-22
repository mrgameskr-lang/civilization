"""Check one chronological replay against original crossings, settlements and labor accounts."""
from collections import Counter, defaultdict
import json

from civsim.annual_game import load
from civsim.chronicle import Chronicle
from civsim.chronicle_event import resolve
from experiments.check_research71 import require
from experiments.research71 import digest


def inspect_save(path):
    class CrossingReceipts:
        def __init__(self):
            self.rows = {}
            self.events = {}
            self.last = defaultdict(Counter)
            self.counts = Counter()

        def observe(self, row):
            year = row["year"]
            owners = {r["id"]:r["owner"] for r in row["regions"]}
            physical = row["diplomacy"]["physical"]
            desks, workers = {}, Counter()
            prior = self.last
            self.last = defaultdict(Counter)
            for index, p in enumerate(row["crisis"]["pairs"]):
                pair = (p["a"], p["b"])
                facts = prior[pair]
                require(p["evidence_year"] == year-1 and p["trade_denied"] == facts["trade_denied"] and
                        p["people_denied"] == facts["people_denied"] and p["breaches"] == facts["breaches"],
                        "opening crisis evidence differs from previous settled receipts")
                if p["staffed"]:
                    require(all(c["selected"] for c in p["choices"]) and p["workers"] == 2, "unpaid desk")
                    workers.update(p["road"])
                    desks[tuple(sorted(p["road"]))] = p
                if p["transition"] != "none":
                    self.events[year, *pair] = f"/crisis/pairs/{index}/transition"
            # Rebuild remaining review slots and stage costs independently of the desk executor.
            processed = defaultdict(Counter)
            for channel, name in (("trade_attempts", "goods"), ("migration_attempts", "people")):
                for t in physical[channel]:
                    edge = tuple(sorted((t["source"], t["target"])))
                    pair = tuple(sorted(owners[i] for i in edge))
                    if name == "goods":
                        refused, passed = t["denied"], t["quantity"]
                    else:
                        refused, passed = t["denied_exit"] + t["denied_entry"], t["people"]
                    self.last[pair]["trade_denied" if name == "goods" else "people_denied"] += refused
                    require(refused + passed == t["feasible"], "crossing attempts do not balance")
                    if "appeal_granted" in t:
                        used = processed[edge]
                        require(edge in desks and t["appeal_remaining_before"] == 4-sum(used.values())
                                and t["ordinary_passed"] + t["appeal_granted"] == passed
                                and 0 <= t["appeal_granted"] <= t["appeal_remaining_before"],
                                "review allowance and crossing receipt differ")
                        used[name] += t["appeal_granted"]
            for edge, desk in desks.items():
                for name in ("goods", "people"):
                    require(processed[edge][name] == desk[name+"_released"], "desk approvals do not match receipts")
                    self.counts[name+"_released"] += processed[edge][name]
            for pair in row["diplomacy"]["pairs"]:
                self.last[pair["a"],pair["b"]]["breaches"] = sum(
                    f["agreement_breach"] for f in pair["flows"]["directions"])
            work = {r["id"]: r["workers_reserved"] for r in row["government"]["works"]["nodes"]}
            service = {r["id"]:r["serving"] for r in row["service"]["regions"]}
            for r in row["regions"]:
                p, i = r["production"], r["id"]
                employed = (p["workers"] + p["soil_care"]["workers"] + p["investment"]["construction_labor"]
                            + p["withheld_workers"] + work[i] + service[i] + workers[i])
                require(employed == r["opening"]["population"]//2, "local worker-years do not reconcile")
            self.counts["worker_years"] += sum(workers.values())
            self.rows[year] = {"crisis": row["crisis"], "countries": row["countries"],
                               "diplomacy": row["diplomacy"]}

    receipts = CrossingReceipts()
    seed = json.loads(path.read_bytes())["journal"]["seed"]
    chronicle = Chronicle(seed)
    journal, _ = load(path, observers=(receipts, chronicle))
    events = [e for e in chronicle.report()["events"] if e["kind"].startswith("border_crisis_")]
    observed = set()
    for e in events:
        y = e["year"]
        key = y, e["country"], e["counterparty"]
        require(key not in observed and receipts.events[key] == e["evidence"]["transition"]["pointer"]
                and e["record_sha256"] == journal["turns"][y-1]["record_sha256"], "event hash or pointer mismatch")
        observed.add(key)
        for fact in e["evidence"].values():
            require(resolve(receipts.rows[y], fact["pointer"]) == fact["value"], "event differs from its source")
    require(observed == receipts.events.keys(), "missing transition from chronicle")
    return {"seed": seed, "years": len(journal["turns"]), "transitions": len(events), **receipts.counts,
            "journal_sha256": digest(journal)}
