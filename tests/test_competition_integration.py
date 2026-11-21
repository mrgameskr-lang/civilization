from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from civsim.analysis import summary
from civsim.competition import competition_snapshot, fork_tax_year, start_competition, step_competition
from civsim.competition_storage import write_competition_run
from civsim.government_audit import audit_fiscal_year
from civsim.model import generate_world
from civsim.politics import start_political, step_political
from civsim.regions import regionalize
from civsim.storage import canonical_line, verify_run


def world():
    return regionalize(generate_world(3, 18, 12, 3), 3)


class CompetitionIntegrationTests(unittest.TestCase):
    def test_a_projects_to_exact_legacy_and_b_changes_only_preferences_initially(self):
        incumbent, a, b = start_political(world()), start_competition(world()), start_competition(world())
        for year in range(1, 7):
            legacy = step_political(incumbent, year, True)
            row = step_competition(a, year, "A")
            diff = step_competition(b, year, "B")
            self.assertEqual(canonical_line(legacy), canonical_line({k:v for k,v in row.items() if k!="competition"}))
            if year == 1:
                self.assertEqual(row["government"], diff["government"])
            for journal in (row, diff):
                self.assertTrue(all(c["election"] is None for c in journal["competition"]["countries"]))

    def test_annual_ballot_appropriation_and_archive_tampering(self):
        sim = start_competition(world())
        for y in range(1, 5):
            prior = step_competition(sim, y, "C")
        row = json.loads(canonical_line(step_competition(sim, 5, "C")))
        audit_fiscal_year(row, previous_record=prior)
        for c in row["competition"]["countries"]:
            self.assertTrue(c["election"]["election"])
        for field in ("ballot", "cabinet", "tariff", "choice", "historical"):
            with self.subTest(field=field):
                altered, prev = deepcopy(row), deepcopy(prior)
                c = altered["competition"]["countries"][0]
                if field=="ballot":
                    c["election"]["participation_points"] += 1
                elif field=="cabinet":
                    c["closing"]["incumbent"] = "forged"
                elif field=="tariff":
                    c["tariff"] = "forged"
                elif field=="choice":
                    c["outgoing_choice"] = {"action":"forged"}
                else:
                    prev["competition"]["countries"][0]["closing"]["term_start"] += 1
                with self.assertRaises(ValueError):
                    audit_fiscal_year(altered, previous_record=prev)

    def test_assets_carry_across_government_installation(self):
        sim = start_competition(world())
        for year in range(1, 5):
            prior = step_competition(sim, year, "C")
        current = step_competition(sim, 5, "C")
        self.assertTrue(any(c["election"]["installation"] for c in current["competition"]["countries"]))
        for key in ("countries", "regions", "depots", "roads"):
            with self.subTest(inherited=key):
                damaged = deepcopy(prior)
                if key in ("countries", "regions"):
                    damaged[key][0]["closing"]["cash"] += 1
                elif key == "depots":
                    damaged["government"][key][0]["closing"]["tools"] += 1
                else:
                    damaged["government"][key][0]["next_capacity"] += 1
                with self.assertRaises(ValueError):
                    audit_fiscal_year(current, previous_record=damaged)

    def test_standalone_year_rejects_shifted_election_counts(self):
        sim = start_competition(world())
        for year in range(1, 7):
            row = step_competition(sim, year, "C")
        cabinet = row["competition"]["countries"][0]
        for endpoint in ("opening", "closing"):
            cabinet[endpoint]["elections"] += 100
        with self.assertRaisesRegex(ValueError, "calendar"):
            audit_fiscal_year(row)

    def test_counterfactual_tax_preserves_openings_election_and_source(self):
        sim = start_competition(world())
        for y in range(1, 5):
            step_competition(sim, y, "C")
        old = canonical_line(competition_snapshot(sim))
        fixed, variable = fork_tax_year(sim, 5)
        self.assertEqual(old, canonical_line(competition_snapshot(sim)))
        self.assertEqual(fixed["government"]["works"], variable["government"]["works"])
        for a,b in zip(fixed["competition"]["countries"], variable["competition"]["countries"], strict=True):
            self.assertEqual(a["election"], b["election"])
            self.assertEqual(a["closing"], b["closing"])
        for a,b in zip(fixed["regions"], variable["regions"], strict=True):
            self.assertEqual(a["production"], b["production"])
            self.assertEqual(a["opening"], b["opening"])

    def test_failed_audit_or_regime_change_does_not_advance_state(self):
        sim = start_competition(world())
        r = step_competition(sim, 1, "D")
        initial = canonical_line(competition_snapshot(sim))
        r["competition"]["countries"][0]["closing"]["incumbent"] = "forged"
        self.assertEqual(initial, canonical_line(competition_snapshot(sim)))
        with patch("civsim.competition.audit_cabinets", side_effect=ValueError("injected failure")):
            with self.assertRaises(ValueError):
                step_competition(sim, 2, "D")
        for args in ((3,"D","fixed"), (2,"C","fixed"), (2,"D","platform")):
            with self.assertRaises(ValueError):
                step_competition(sim, *args)
        self.assertEqual(initial, canonical_line(competition_snapshot(sim)))

    def test_run_replay_and_version_dispatch(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp, "race")
            write_competition_run(out, seed=3, years=5, arm="C", tax_policy="platform",
                                  width=18, height=12, nations=3, per_nation=3)
            raw = out/"years.jsonl"
            self.assertEqual(verify_run(out), hashlib.sha256(raw.read_bytes()).hexdigest())
            totals = summary(out)
            self.assertEqual((totals["model_version"], totals["tax_policy"],totals["total_election"]),
                             ("5.0C","platform",3))
            with self.assertRaises(FileExistsError):
                write_competition_run(out)
            lines = raw.read_bytes().splitlines(keepends=True)
            last = json.loads(lines[-1])
            last["competition"]["countries"][0]["governing_faction"] = "forged"
            raw.write_bytes(b"".join(lines[:-1]) + canonical_line(last))
            with self.assertRaises(ValueError):
                verify_run(out)
