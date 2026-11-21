from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from civsim.analysis import summary
from civsim.collective import collective_snapshot, fork_action_year, start_collective, step_collective
from civsim.collective_rules import ACTIVE, GROUPS
from civsim.collective_storage import write_collective_run
from civsim.competition_storage import write_competition_run
from civsim.government_audit import audit_fiscal_year
from civsim.model import generate_world
from civsim.regions import regionalize
from civsim.storage import canonical_line, verify_run


class CollectiveIntegrationTests(unittest.TestCase):
    def test_disabled_archive_matches_seed_world_and_annual_5c_bytes(self):
        with TemporaryDirectory() as folder:
            old, new = Path(folder, "5c"), Path(folder, "5d")
            options = dict(seed=3, width=18, height=12, nations=3, years=6, per_nation=3)
            write_competition_run(old, arm="C", **options)
            write_collective_run(new, enabled=False, **options)
            for filename in ("world.json", "years.jsonl"):
                self.assertEqual((old / filename).read_bytes(), (new / filename).read_bytes())
            self.assertEqual(verify_run(old), verify_run(new))
            self.assertEqual(summary(new)["collective_enabled"], False)
            with self.assertRaises(FileExistsError):
                write_collective_run(new, enabled=True, **options)

    def test_fork_recomputes_response_without_advancing_a_real_opening(self):
        sim = start_collective(regionalize(generate_world(0)))
        previous = None
        for year in range(1, 30):
            opening = deepcopy(sim)
            row = step_collective(sim, year)
            audit_fiscal_year(row, previous_record=previous)
            previous = row
            target = next(((r["id"], n) for r in row["collective"]["regions"] for n in GROUPS
                           if r["groups"][n]["action"] in ACTIVE), None)
            if target:
                break
        self.assertIsNotNone(target)
        initial = canonical_line(collective_snapshot(opening))
        actual, suppressed = fork_action_year(opening, year, *target)
        self.assertEqual(canonical_line(row), canonical_line(actual))
        self.assertEqual(initial, canonical_line(collective_snapshot(opening)))
        self.assertEqual(actual["competition"], suppressed["competition"])
        for a, b in zip(actual["collective"]["regions"], suppressed["collective"]["regions"], strict=True):
            for name in GROUPS:
                if (a["id"], name) == target:
                    self.assertEqual(b["groups"][name]["participants"], 0)
                else:
                    self.assertEqual(a["groups"][name]["action"], b["groups"][name]["action"])
                self.assertEqual(a["groups"][name]["prior"], b["groups"][name]["prior"])
        bad = deepcopy(actual)
        bad["collective"]["regions"][0]["groups"]["farm"]["closing"]["answered"] ^= True
        with self.assertRaises(ValueError):
            audit_fiscal_year(bad)

    def test_audit_failure_and_policy_mixing_preserve_the_source(self):
        sim = start_collective(regionalize(generate_world(1, 18, 12, 3), 3))
        first = step_collective(sim, 1)
        before = canonical_line(collective_snapshot(sim))
        with patch("civsim.collective.audit_actions", side_effect=ValueError("failure")):
            with self.assertRaisesRegex(ValueError, "failure"):
                step_collective(sim, 2)
        with self.assertRaises(ValueError):
            step_collective(sim, 2, False)
        self.assertEqual(before, canonical_line(collective_snapshot(sim)))
        second = step_collective(sim, 2)
        audit_fiscal_year(second, previous_record=first)
        first["collective"]["regions"][0]["groups"]["farm"]["closing"]["rest"] += 1
        with self.assertRaisesRegex(ValueError, "campaign history"):
            audit_fiscal_year(second, previous_record=first)
