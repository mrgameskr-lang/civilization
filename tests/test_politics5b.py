from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from civsim.analysis import summary
from civsim.government import fiscal_snapshot, start_government, step_government
from civsim.government_audit import audit_fiscal_year
from civsim.model import generate_world
from civsim.political_storage import write_political_run
from civsim.politics import political_snapshot, start_political, step_political
from civsim.regions import regionalize
from civsim.storage import canonical_line, verify_run


def initial():
    return regionalize(generate_world(3, 18, 12, 3), 3)


class PoliticalIntegrationTests(unittest.TestCase):
    def test_off_economy_is_exact_fiscal_engine_and_observes_history(self):
        control = start_government(initial())
        shadow = start_political(initial())
        self.assertEqual(fiscal_snapshot(control), political_snapshot(shadow)["fiscal"])
        for year in range(1, 12):
            a = step_government(control, year, "integrated")
            row = step_political(shadow, year, False)
            self.assertEqual(canonical_line(a), canonical_line({k:v for k,v in row.items() if k != "politics"}))
            self.assertEqual(row["politics"]["regions"][0]["closing"]["year"], year)

    def test_independent_observation_and_prior_checks_reject_forgery(self):
        sim = start_political(initial())
        prev = step_political(sim, 1)
        current = json.loads(canonical_line(step_political(sim, 2)))
        audit_fiscal_year(current, previous_record=prev)
        forged = deepcopy(current)
        forged["politics"]["countries"][0]["recommendation"]["changed"] ^= True
        with self.assertRaises(ValueError):
            audit_fiscal_year(forged, previous_record=prev)
        forged = deepcopy(current)
        forged["politics"]["regions"][0]["closing"]["groups"]["farm"]["support"] += 1
        with self.assertRaises(ValueError):
            audit_fiscal_year(forged, previous_record=prev)
        obsolete = deepcopy(prev)
        obsolete["politics"]["regions"][0]["closing"]["groups"]["farm"]["support"] += 1
        with self.assertRaises(ValueError):
            audit_fiscal_year(current, previous_record=obsolete)

    def test_neutral_first_year_and_lagged_approval(self):
        a = step_political(start_political(initial()), 1, True)
        b = step_political(start_political(initial()), 1, False)
        self.assertEqual(a["government"], b["government"])
        self.assertEqual(a["politics"]["regions"], b["politics"]["regions"])
        self.assertTrue(all(not c["recommendation"]["changed"] for c in a["politics"]["countries"]))

    def test_atomic_publication_and_no_shared_memory_with_returned_ledger(self):
        sim = start_political(initial())
        row = step_political(sim, 1, True)
        before = canonical_line(political_snapshot(sim))
        row["politics"]["regions"][0]["closing"]["groups"]["farm"]["support"] = -999
        self.assertEqual(before, canonical_line(political_snapshot(sim)))
        with patch("civsim.politics.audit_political_states", side_effect=ValueError("injected close failure")):
            with self.assertRaises(ValueError):
                step_political(sim, 2, True)
        for year, setting in ((2,False), (3,True), (2,1)):
            with self.assertRaises(ValueError):
                step_political(sim, year, setting)
        self.assertEqual(before, canonical_line(political_snapshot(sim)))

    def test_archive_replay_version_summary_and_no_overwrite(self):
        with TemporaryDirectory() as parent:
            for enabled in (False, True):
                path = Path(parent, str(enabled))
                write_political_run(path, feedback=enabled, years=3, seed=3, width=18, height=12,
                                    nations=3, per_nation=3)
                data = path / "years.jsonl"
                self.assertEqual(verify_run(path), hashlib.sha256(data.read_bytes()).hexdigest())
                result = summary(path)
                self.assertEqual((result["model_version"], result["feedback"]), ("5.0B", enabled))
                with self.assertRaises(FileExistsError):
                    write_political_run(path)
                blob = data.read_bytes()
                altered = blob.replace(b'"feedback":true', b'"feedback":false', 1) if enabled else blob + b'\n'
                data.write_bytes(altered)
                with self.assertRaises(ValueError):
                    verify_run(path)
