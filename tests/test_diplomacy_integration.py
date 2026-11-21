from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from civsim.analysis import summary
from civsim.collective import start_collective, step_collective
from civsim.collective_storage import write_collective_run
from civsim.diplomacy import diplomacy_snapshot, fork_diplomacy_year, start_diplomacy, step_diplomacy
from civsim.diplomacy_storage import write_diplomacy_run
from civsim.government_audit import audit_fiscal_year
from civsim.model import generate_world
from civsim.regions import regionalize
from civsim.storage import canonical_line, verify_run


def world():
    return regionalize(generate_world(2, 18, 12, 3), 3)


class DiplomacyIntegrationTests(unittest.TestCase):
    def test_a_and_b_reproduce_the_5d_annual_ledger(self):
        control = start_collective(world())
        baseline, observed = (start_diplomacy(world()) for _ in range(2))
        for year in range(1, 9):
            old = canonical_line(step_collective(control, year))
            self.assertEqual(canonical_line(step_diplomacy(baseline, year, "A")), old)
            b = step_diplomacy(observed, year, "B")
            self.assertEqual(canonical_line({k: v for k, v in b.items() if k != "diplomacy"}), old)
            self.assertEqual(len(b["diplomacy"]["pairs"]), 3)
            self.assertFalse(any(p["policy"]["agreement_active"] for p in b["diplomacy"]["pairs"]))

    def test_a_initial_bytes_and_detailed_d_replay(self):
        with TemporaryDirectory() as folder:
            old, a, d = (Path(folder, n) for n in ("5d", "6a-a", "6a-d"))
            args = dict(seed=3, width=18, height=12, nations=3, years=5, per_nation=3)
            write_collective_run(old, enabled=True, **args)
            write_diplomacy_run(a, arm="A", **args)
            write_diplomacy_run(d, arm="D", **args)
            for name in ("world.json", "years.jsonl"):
                self.assertEqual((old/name).read_bytes(), (a/name).read_bytes())
            annual = d/"years.jsonl"
            self.assertEqual(verify_run(d), hashlib.sha256(annual.read_bytes()).hexdigest())
            self.assertEqual(summary(d)["diplomatic_arm"], "D")
            with self.assertRaises(FileExistsError):
                write_diplomacy_run(d, arm="B")
            lines = annual.read_bytes().splitlines(keepends=True)
            last = json.loads(lines[-1])
            last["diplomacy"]["pairs"][0]["closing"]["trust"] += 1
            annual.write_bytes(b"".join(lines[:-1]) + canonical_line(last))
            with self.assertRaises(ValueError):
                verify_run(d)

    def test_prior_history_immutability_and_atomic_failure(self):
        sim = start_diplomacy(world())
        prior = step_diplomacy(sim, 1, "D")
        opening = canonical_line(diplomacy_snapshot(sim))
        with patch("civsim.diplomatic_rules.finish_diplomacy", side_effect=ValueError("failed diplomacy")):
            with self.assertRaisesRegex(ValueError, "failed diplomacy"):
                step_diplomacy(sim, 2, "D")
        with self.assertRaises(ValueError):
            step_diplomacy(sim, 2, "C")
        with self.assertRaises(ValueError):
            fork_diplomacy_year(sim, 2, {"kind": "nonsense"})
        self.assertEqual(opening, canonical_line(diplomacy_snapshot(sim)))
        row = step_diplomacy(sim, 2, "D")
        persisted = json.loads(canonical_line(row))
        audit_fiscal_year(persisted, previous_record=prior)
        forged = deepcopy(prior)
        forged["diplomacy"]["pairs"][0]["closing"]["trust"] += 1
        with self.assertRaises(ValueError):
            audit_fiscal_year(persisted, previous_record=forged)
        row["diplomacy"]["pairs"][0]["closing"]["trust"] += 100
        self.assertNotEqual(sim.pairs[0, 1]["trust"], row["diplomacy"]["pairs"][0]["closing"]["trust"])
