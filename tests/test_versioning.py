import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from civsim.rules import Rules
from civsim.storage import read_years, verify_run, write_run
from tests.test_cli import call_cli


SAMPLE = Path(__file__).resolve().parents[1] / "examples" / "seed-42"
LEGACY_HASHES = {
    "manifest.json": "a5ce895428d4ebd39b1f438988b905c0d6cd0532b0ce3ed0c021b409e2a13c37",
    "world.json": "ed4030884c28341ebc1f5f68f66912f3248dcbfd2faa6fb1abe8e2294ea6682e",
    "years.jsonl": "9814b3c0409a7fcf4f65cc07a09f2d2b562ad1251857dcc6d8504b85272c7f11",
}


class VersioningTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.run = self.root / "new"

    def test_original_sample_and_regenerated_legacy_run_keep_all_bytes(self):
        write_run(self.run)
        for folder in (SAMPLE, self.run):
            for filename, expected in LEGACY_HASHES.items():
                self.assertEqual(hashlib.sha256((folder / filename).read_bytes()).hexdigest(), expected)
            self.assertEqual(verify_run(folder), LEGACY_HASHES["years.jsonl"])

    def test_version_two_repeats_with_saved_labor_and_order(self):
        for labor, order in [("idle", ("tools", "ore", "food")),
                             ("reallocate", ("food", "ore", "tools")),
                             ("reallocate", ("ore", "tools", "food"))]:
            rules = Rules(labor=labor, order=order)
            first = self.root / (labor + "-" + order[0])
            second = self.root / (first.name + "-repeat")
            for folder in (first, second):
                write_run(folder, seed=42, years=2, rules=rules)
                meta = json.loads((folder / "manifest.json").read_bytes())
                self.assertEqual(meta["model_version"], "2.0")
                self.assertEqual(meta["rules"], {"labor": labor, "order": list(order)})
                self.assertEqual(next(read_years(folder))["market"]["settlement_order"], list(order))
            self.assertEqual(verify_run(first), verify_run(second))
            for filename in LEGACY_HASHES:
                self.assertEqual((first / filename).read_bytes(), (second / filename).read_bytes())

    def test_manifest_rejects_inconsistent_missing_extra_or_malformed_settings(self):
        write_run(self.run, years=1, rules=Rules(labor="reallocate"))
        path = self.run / "manifest.json"
        original = json.loads(path.read_bytes())
        rules = original["rules"]
        variants = [
            {**original, "model_version": "3.0"},
            {**original, "model_version": "1.0"},
            {k: v for k, v in original.items() if k != "rules"},
            {**original, "rules": {**rules, "labor": "idle"}},
            {**original, "rules": {**rules, "unknown": 1}},
            {**original, "rules": {"order": rules["order"]}},
            {**original, "rules": {**rules, "order": "food,ore,tools"}},
            {**original, "rules": {**rules, "order": ["food", "ore", "ore"]}},
            {**original, "rules": {**rules, "labor": "invented"}},
            {**original, "rules": {**rules, "order": ["ore", "tools", "food"]}},
        ]
        for meta in variants:
            with self.subTest(meta=meta):
                path.write_text(json.dumps(meta), encoding="utf-8")
                with self.assertRaises(ValueError):
                    verify_run(self.run)

    def test_v2_replay_detects_revised_labor_inputs(self):
        write_run(self.run, years=1, rules=Rules(labor="reallocate"))
        path = self.run / "years.jsonl"
        ledger = json.loads(path.read_bytes())
        ledger["countries"][0]["production"]["idle_before"] += 1
        path.write_text(json.dumps(ledger) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "year 1"):
            verify_run(self.run)

    def test_cli_sets_policy_and_rejects_malformed_orders_before_writing(self):
        args = ("run", "--out", self.run, "--years", "1", "--labor", "reallocate")
        invalid = call_cli(*args, "--trade-order", "tools,food,tools")
        self.assertNotEqual(invalid.returncode, 0)
        self.assertFalse(self.run.exists())
        result = call_cli(*args, "--trade-order", "tools,food,ore")
        self.assertEqual(result.returncode, 0, result.stderr)
        meta = json.loads((self.run / "manifest.json").read_bytes())
        self.assertEqual(meta["rules"], {"labor": "reallocate", "order": ["tools", "food", "ore"]})
        self.assertEqual(call_cli("verify", self.run).returncode, 0)
