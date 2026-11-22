from copy import deepcopy
from hashlib import sha256
import unittest
from unittest.mock import patch

from civsim.annual_game import create, play
from civsim.chronicle import Chronicle, render_markdown
from civsim.chronicle_event import Candidate, resolve
from civsim.storage import canonical_line


def year_row(year, before=0, after=0, transition="none"):
    pair = {"a": 1, "b": 3, "opening_level": before, "closing_level": after,
            "transition": transition, "road": [7, 13], "evidence_year": year-1,
            "trade_denied": 4 if after > before else 0, "people_denied": 0,
            "breaches": 0, "tension": 125, "trust": 410, "staffed": False,
            "workers": 0, "goods_released": 0, "people_released": 0}
    flows = [{"source": source, "target": target, "trade_denied": 0, "migration_denied_exit": 0,
              "migration_denied_entry": 0, "agreement_breach": 0} for source, target in ((1, 3), (3, 1))]
    flows[0]["trade_denied"] = pair["trade_denied"]
    opening = {"year": year-1, "tension": 125, "trust": 410, "last": flows}
    return {"year": year, "crisis": {"pairs": [pair]},
            "diplomacy": {"pairs": [{"a": 1, "b": 3, "opening": opening}],
                          "physical": {"trade_attempts": [], "migration_attempts": []}}}


class CrisisChronicleTests(unittest.TestCase):
    def test_seed_zero_observed_crisis_and_prior_denials_join_across_years(self):
        game, book = create(0), Chronicle(0)
        previous = None
        kinds = {"start": "border_crisis_started", "escalate": "border_crisis_escalated",
                 "ease": "border_crisis_eased", "resolve": "border_crisis_resolved"}
        seen = set()
        for year in range(1, 9):
            cmd = {1: {"move": None, "research": True, "diffusion": True, "crisis": True},
                   2: {"move": None, "public_farm": True, "reserve_policy": "emergency"}}.get(year)
            row = play(game, cmd)
            book.observe(row)
            events = [e for e in book.report()["events"] if e["year"] == year and e["kind"] in kinds.values()]
            expected = {(p["a"], p["b"], kinds[p["transition"]]) for p in row["crisis"]["pairs"]
                        if p["transition"] != "none"}
            self.assertEqual({(e["country"], e["counterparty"], e["kind"]) for e in events}, expected)
            for event in events:
                seen.add(event["kind"])
                self.assertEqual(event["record_sha256"], sha256(canonical_line(row)).hexdigest())
                for fact in event["evidence"].values():
                    self.assertEqual(resolve(row, fact["pointer"]), fact["value"])
                old = next(p for p in previous["diplomacy"]["pairs"]
                           if (p["a"], p["b"]) == (event["country"], event["counterparty"]))
                self.assertEqual(sum(f["trade_denied"] for f in old["flows"]["directions"]),
                                 event["evidence"]["trade_denied"]["value"])
            previous = row
        self.assertEqual(seen, set(kinds.values()))

    @patch("civsim.chronicle.annual_candidates", return_value=[])
    def test_only_observed_transitions_with_current_and_prior_evidence(self, _):
        book = Chronicle(seed=0)
        rows = [year_row(1), year_row(2, 0, 1, "start"), year_row(3, 1, 2, "escalate"),
                year_row(4, 2, 2), year_row(5, 2, 1, "ease"), year_row(6, 1, 0, "resolve")]
        rows[2]["crisis"]["pairs"][0].update(staffed=True, workers=2, goods_released=1)
        rows[2]["diplomacy"]["physical"]["trade_attempts"].append({"source": 7, "target": 13, "appeal_granted": 1})
        snapshot = deepcopy(rows)
        for row in rows:
            book.observe(row)
        events = book.report()["events"]
        self.assertEqual([e["kind"] for e in events], ["border_crisis_started", "border_crisis_escalated",
                                                       "border_crisis_eased", "border_crisis_resolved"])
        self.assertEqual(rows, snapshot)
        for event in events:
            year = event["year"]
            self.assertEqual((event["country"], event["counterparty"], event["region"]), (1, 3, None))
            self.assertEqual(event["record_sha256"], sha256(canonical_line(rows[year-1])).hexdigest())
            self.assertEqual(event["evidence"]["evidence_year"]["value"], year-1)
            for fact in event["evidence"].values():
                self.assertEqual(resolve(rows[year-1], fact["pointer"]), fact["value"])
        self.assertEqual(events[1]["evidence"]["goods_released"]["value"], 1)
        self.assertEqual(events[1]["evidence"]["trade_receipt_0"]["pointer"],
                         "/diplomacy/physical/trade_attempts/0/appeal_granted")
        self.assertEqual(events[1]["evidence"]["trade_denied_0"]["pointer"],
                         "/diplomacy/pairs/0/opening/last/0/trade_denied")
        self.assertIn("해소", render_markdown(book.report()))

    def test_all_pairs_remain_visible_in_crowded_year(self):
        ordinary = [Candidate("headline", i, None, 80, "사건", {"year": "/year"}) for i in range(5)]
        book = Chronicle()
        row = year_row(2, 0, 1, "start")
        another = dict(row["crisis"]["pairs"][0], a=2, b=5, road=[8, 21])
        row["crisis"]["pairs"].append(another)
        second_pair = deepcopy(row["diplomacy"]["pairs"][0])
        second_pair.update(a=2, b=5)
        for flow, endpoints in zip(second_pair["opening"]["last"], ((2, 5), (5, 2))):
            flow.update(source=endpoints[0], target=endpoints[1])
        row["diplomacy"]["pairs"].append(second_pair)
        with patch("civsim.chronicle.annual_candidates", return_value=ordinary):
            book.observe(year_row(1))
            book.observe(row)
        second = [e for e in book.report()["events"] if e["year"] == 2]
        self.assertEqual(len(second), 6)
        self.assertEqual([(e["country"], e["counterparty"]) for e in second
                          if e["kind"] == "border_crisis_started"], [(1, 3), (2, 5)])

    @patch("civsim.chronicle.annual_candidates", return_value=[])
    def test_rejects_invented_or_mislabeled_transition(self, _):
        for before, after, label in ((1, 1, "start"), (0, 1, "none"), (2, 1, "resolve")):
            with self.subTest(label=label):
                book = Chronicle()
                book.observe(year_row(1))
                with self.assertRaises(ValueError):
                    book.observe(year_row(2, before, after, label))

    @patch("civsim.chronicle.annual_candidates", return_value=[])
    def test_prior_denials_and_funded_clearances_must_match_their_receipts(self, _):
        for forged in ({"trade_denied": 900}, {"goods_released": 5}):
            book = Chronicle()
            book.observe(year_row(1))
            row = year_row(2, 0, 1, "start")
            row["crisis"]["pairs"][0].update(forged)
            with self.assertRaises(ValueError):
                book.observe(row)
