import tempfile
import os
import unittest
from pathlib import Path
import hashlib
from io import StringIO

from experiments.civic_disputes63 import (
    check_direction_year, NATIONAL_POSTINGS, audit_national_year, verify_tables,
)


class DiplomaticArchiveTests(unittest.TestCase):
    def test_adjacent_pair_requires_a_unique_row_each_way(self):
        rows = [{"source": 0, "target": 1}, {"source": 1, "target": 0}]
        self.assertEqual(check_direction_year(rows, {(0, 1)}, 3), {(0, 1): 2})
        with self.assertRaises(ValueError):
            check_direction_year(rows[:1], {(0, 1)}, 3)
        with self.assertRaises(ValueError):
            check_direction_year(rows + rows[:1], {(0, 1)}, 3)
        self.assertEqual(check_direction_year(rows + [{"source": 0, "target": 2}], {(0, 1)}, 3),
                         {(0, 1): 2, (0, 2): 1})

    def test_national_payments_and_border_denials_have_the_correct_direction(self):
        country = {i: {k: 0 for _, _, k in NATIONAL_POSTINGS} for i in range(2)}
        row = {"source": 0, "target": 1, **{k: 0 for k, _, _ in NATIONAL_POSTINGS}}
        row.update(sent=5, received=4, cost_food=2, handling_food=1, entry_denied=8, migrants=3)
        country[0].update(aid_sent=5, aid_freight_food=2, aid_handling_food=1, foreign_out=3)
        country[1].update(aid_received=4, foreign_in=3, entry_denied_in=8)
        audit_national_year([row], country)
        country[0]["entry_denied_in"] = 8
        with self.assertRaises(ValueError):
            audit_national_year([row], country)

    def test_repeat_verification_reads_all_bytes(self):
        with tempfile.TemporaryDirectory() as name:
            d = Path(name)
            old, new = d/"old", d/"new"
            old.mkdir()
            new.mkdir()
            for folder in (old,new):
                (folder/"test.csv").write_bytes(b"12\n")
                os.utime(folder/"test.csv", (1600000000,1600000000))
            verify_tables(old, new, ("test.csv",))
            (new/"test.csv").write_bytes(b"13\n")
            os.utime(new/"test.csv", (1600000000,1600000000))
            with self.assertRaises(ValueError):
                verify_tables(old, new, ("test.csv",))

    def test_first_year_has_no_evidence_and_all_28_pairs_are_preserved(self):
        from experiments.civic_disputes63 import StudyPath
        records = StringIO()
        path = StudyPath(7, "consult")
        result = path.advance(1, [], records)
        self.assertEqual(len(result), 28)
        values = path.world_totals()
        self.assertEqual(values["pair_years"], 28)
        self.assertEqual(values["no_direction_years"], 28)
        self.assertEqual(values["observed_years"], 0)
        self.assertEqual(values["start"], 0)
        self.assertEqual(path.digest.hexdigest(), hashlib.sha256(records.getvalue().encode()).hexdigest())

    def test_next_year_separates_quiet_observed_years_from_missing_evidence(self):
        from experiments.analyze_civic63 import following_outcome
        self.assertEqual(following_outcome({"observed": False, "event": "unobserved"}), "unobserved")
        self.assertEqual(following_outcome({"observed": True, "event": "ease"}), "eased")
        self.assertEqual(following_outcome({"observed": True, "event": "continue"}), "continued")
