import io
import json
import subprocess
import sys
from contextlib import redirect_stdout
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from civsim.chronicle import Chronicle, chronicle_text, render_highlights, render_markdown
from civsim.chronicle_event import Candidate, resolve
from civsim.storage import canonical_line


def crisis(region, score=75):
    return Candidate("food_crisis", 0, region, score, "식량이 100단위 부족했다.", {"부족량": "/unmet"})


class SelectionTests(unittest.TestCase):
    def observe(self, observer, year, *candidates):
        row = {"year": year, "unmet": 100}
        with patch("civsim.chronicle.annual_candidates", return_value=iter(candidates)):
            observer.observe(row)
        return row

    def test_evidence_is_bound_to_exact_replayed_year(self):
        observer = Chronicle(seed=0)
        row = self.observe(observer, 1, crisis(1))
        event, = observer.report()["events"]
        self.assertEqual(event["evidence"]["부족량"], {"pointer": "/unmet", "value": 100})
        self.assertEqual(event["record_sha256"], sha256(canonical_line(row)).hexdigest())
        self.assertIn("식량이 100단위 부족했다.", render_markdown(observer.report()))

    def test_persistent_crisis_reappears_on_escalation_and_after_recovery(self):
        observer = Chronicle()
        for year, score in enumerate([65, 69, 75, 72, None, 65], 1):
            self.observe(observer, year, *([] if score is None else [crisis(1, score)]))
        self.assertEqual([e["year"] for e in observer.report()["events"]], [1, 3, 6])
        self.assertEqual(observer.report()["suppressed_repeats"], 2)

    def test_cap_is_order_independent_and_does_not_hide_unpublished_episode_forever(self):
        observers = [Chronicle(), Chronicle()]
        for observer, ids in zip(observers, [range(6), reversed(range(6))]):
            self.observe(observer, 1, *(crisis(i) for i in ids))
            self.observe(observer, 2, *(crisis(i) for i in range(6)))
        report = observers[0].report()
        self.assertEqual(report, observers[1].report())
        self.assertEqual([(e["year"], e["region"]) for e in report["events"]],
                         [(1,0), (1,1), (1,2), (1,3), (2,4), (2,5)])
        self.assertEqual(report["excluded_by_year_limit"], 2)

    def test_separate_occurrences_are_not_suppressed_as_an_ongoing_crisis(self):
        observer = Chronicle()
        event = Candidate("government_turnover", 0, None, 90, "집권 세력이 바뀌었다.", {"사례":"/unmet"})
        for year in (1, 2):
            self.observe(observer, year, event)
        self.assertEqual(len(observer.report()["events"]), 2)

    def test_decade_highlights_show_distinct_observed_kinds_and_do_not_mutate_full_chronicle(self):
        observer = Chronicle(seed=20)
        for year in range(1, 12):
            transfer = Candidate("government_turnover", 0, None, 90, f"제{year}년의 집권 교체.", {"수량":"/unmet"})
            self.observe(observer, year, transfer, crisis(1))
        report = observer.report()
        before = canonical_line(report)
        preview = render_highlights(report)
        self.assertIn("제1년의 집권 교체.", preview)
        self.assertIn("제11년의 집권 교체.", preview)
        self.assertNotIn("제2년의 집권 교체.", preview)
        self.assertEqual(preview.count("식량이 100단위 부족했다."), 1)
        self.assertEqual(before, canonical_line(report))

    def test_annual_order_has_no_gaps_or_duplicates(self):
        observer = Chronicle()
        with self.assertRaises(ValueError):
            self.observe(observer, 2)
        self.observe(observer, 1)
        with self.assertRaises(ValueError):
            self.observe(observer, 1)

    def test_json_pointer_escapes_and_invalid_array_subscripts(self):
        self.assertEqual(resolve({"a/b": {"~": [3]}}, "/a~1b/~0/0"), 3)
        for pointer in ("/-1", "/00", "/foo", "/1", ""):
            with self.subTest(pointer=pointer), self.assertRaises(ValueError):
                resolve([5], pointer)


class ChronicleReplayTests(unittest.TestCase):
    slot = Path(__file__).resolve().parents[1] / "examples/annual-unit-v1/position-saves/next.json"

    def test_checked_historical_slot_and_lookup(self):
        raw = self.slot.read_bytes()
        report = json.loads(chronicle_text(self.slot, "json"))
        self.assertTrue(report["events"])
        year = report["events"][0]["year"]
        row = json.loads(chronicle_text(self.slot, "json", ledger_year=year))
        for event in (e for e in report["events"] if e["year"] == year):
            self.assertEqual(event["record_sha256"], sha256(canonical_line(row)).hexdigest())
            for fact in event["evidence"].values():
                self.assertEqual(resolve(row, fact["pointer"]), fact["value"])
        self.assertEqual(self.slot.read_bytes(), raw)
        with self.assertRaises(ValueError):
            chronicle_text(self.slot, "json", ledger_year=999)

    def test_cli_ledger_bytes_match_original_journal_digest(self):
        result = subprocess.run([sys.executable, "-m", "civsim", "chronicle", str(self.slot),
                                 "--ledger-year", "1"], capture_output=True, check=True)
        expected = json.loads(self.slot.read_bytes())["journal"]["turns"][0]["record_sha256"]
        self.assertEqual(sha256(result.stdout).hexdigest(), expected)

    def test_bad_digest_never_publishes_a_partial_report(self):
        with TemporaryDirectory() as folder:
            slot = json.loads(self.slot.read_bytes())
            slot["journal"]["turns"][-1]["record_sha256"] = "0" * 64
            path = Path(folder) / "tampered.json"
            path.write_text(json.dumps(slot), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output), self.assertRaisesRegex(ValueError, "replay differs"):
                chronicle_text(path, "markdown")
            self.assertEqual(output.getvalue(), "")
