import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from civsim.storage import read_years, verify_run, write_run


class RunStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.a = self.root / "one"

    def test_fifty_year_byte_replay_and_other_seed(self):
        b, c = self.root / "two", self.root / "three"
        for path, seed in [(self.a, 42), (b, 42), (c, 8)]:
            write_run(path, seed=seed)
        for name in ("manifest.json", "world.json", "years.jsonl"):
            self.assertEqual((self.a / name).read_bytes(), (b / name).read_bytes())
        raw = (self.a / "years.jsonl").read_bytes()
        self.assertNotEqual(raw, (c / "years.jsonl").read_bytes())
        self.assertEqual(verify_run(self.a), hashlib.sha256(raw).hexdigest())
        self.assertEqual(len(list(read_years(b))), 50)

    def test_replay_detects_even_an_unbalanced_or_audit_neutral_edit(self):
        write_run(self.a, years=2)
        path = self.a / "years.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        row = json.loads(lines[0])
        # The value is evidence about production; a pure balance check cannot detect this edit.
        row["countries"][0]["climate"] += 1
        lines[0] = json.dumps(row)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "year 1"):
            verify_run(self.a)
        path.write_text(lines[0] + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "year"):
            list(read_years(self.a))

    def test_original_run_is_protected_and_failed_run_is_never_published(self):
        write_run(self.a, years=1)
        with self.assertRaises(FileExistsError):
            write_run(self.a, years=2)
        with patch("civsim.storage.step", side_effect=RuntimeError("interrupted")):
            with self.assertRaises(RuntimeError):
                write_run(self.root / "broken", years=1)
        self.assertEqual(list(self.root.iterdir()), [self.a])
        with self.assertRaises(ValueError):
            write_run(self.root / "zero", years=0)

