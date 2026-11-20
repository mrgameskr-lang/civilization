"""Version boundaries, publication, and replay of physical capital."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from civsim.engine import step
from civsim.model import generate_world
from civsim.rules import Rules
from civsim.storage import read_years, verify_run, write_run
from tests.test_cli import call_cli


class InvestmentVersionTests(unittest.TestCase):
    def test_old_runs_and_new_runs_start_from_identical_worlds(self):
        sample = Path(__file__).resolve().parents[1] / "examples/phase2-seeds-0-19/seed13-reallocated"
        old_digest = "062ae987fe753fe2af22cb6a209b1fb6f6ae3f7b2aebcd4809815a1c8dc6d9a4"
        self.assertEqual(verify_run(sample), old_digest)
        with TemporaryDirectory() as tmp:
            for mode in ("inventory", "capital"):
                rules = Rules("reallocate", investment=mode)
                folder = Path(tmp, mode)
                repeat = Path(tmp, mode + "-repeat")
                for out in (folder, repeat):
                    write_run(out, seed=13, years=8, rules=rules)
                    meta = json.loads((out / "manifest.json").read_bytes())
                    self.assertEqual(meta["model_version"], "3.0")
                    self.assertEqual(meta["rules"]["investment"], mode)
                    self.assertEqual((out / "world.json").read_bytes(), (sample / "world.json").read_bytes())
                self.assertEqual(verify_run(folder), verify_run(repeat))
                a = (folder / "years.jsonl").read_bytes()
                self.assertEqual(a, (repeat / "years.jsonl").read_bytes())
                self.assertEqual(hashlib.sha256(a).hexdigest(), verify_run(folder))
                rows = list(read_years(folder))
                for prev, after in zip(rows, rows[1:]):
                    for i, country in enumerate(prev["countries"]):
                        self.assertEqual(country["closing"], after["countries"][i]["opening"])

    def test_missing_inconsistent_or_changed_policy_fails_replay(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp, "run")
            write_run(folder, seed=2, years=2, rules=Rules("reallocate", investment="capital"))
            path = folder / "manifest.json"
            original = json.loads(path.read_bytes())
            for mode, version in [("off", "3.0"), ("capital", "2.0"), ("inventory", "3.0"),
                                  ("unknown", "3.0"), (None, "3.0")]:
                with self.subTest(mode=mode, version=version):
                    config = dict(original["rules"], investment=mode)
                    if mode is None:
                        del config["investment"]
                    path.write_text(json.dumps(dict(original, rules=config, model_version=version)))
                    with self.assertRaises(ValueError):
                        verify_run(folder)

    def test_cli_selects_investment_and_preserves_existing_run(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp, "new")
            run = call_cli("run", "--out", out, "--years", 2, "--investment", "capital", "--labor", "reallocate")
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(call_cli("verify", out).returncode, 0)
            existing = (out / "years.jsonl").read_bytes()
            self.assertNotEqual(call_cli("run", "--out", out, "--investment", "inventory").returncode, 0)
            self.assertEqual((out / "years.jsonl").read_bytes(), existing)

    def test_existing_world_cannot_silently_drop_capital(self):
        world = generate_world(12)
        step(world, 1, Rules("reallocate", investment="capital"))
        with self.assertRaises(ValueError):
            step(world, 2, Rules("reallocate"))
        self.assertEqual(world.year, 1)
