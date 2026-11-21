import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from civsim.posting_archive65 import verify, write
from civsim.storage import canonical_line


class PostingArchiveTests(unittest.TestCase):
    def test_sample_publishes_once_and_verifies_in_a_new_read(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "new" / "sample.jsonl"
            digest = write(path, seed=0, years=3)
            original = path.read_bytes()
            self.assertEqual(hashlib.sha256(original).hexdigest(), digest)
            self.assertEqual(verify(path), digest)
            header, *rows = [json.loads(line) for line in original.splitlines()]
            self.assertEqual(header["semantics"], "registered_assignment")
            self.assertEqual([r["year"] for r in rows], [1, 2, 3])
            self.assertTrue(all(r["register"] is not None for r in rows))
            with self.assertRaises(FileExistsError):
                write(path, seed=1, years=1)
            self.assertEqual(path.read_bytes(), original)

    def test_replay_rejects_changed_economic_evidence_truncation_and_extra_rows(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "example.jsonl"
            write(path, seed=0, years=2)
            header, first, second = path.read_bytes().splitlines(keepends=True)
            altered = json.loads(first)
            altered["economic_sha256"] = "0" * 64
            for data in (header + canonical_line(altered) + second,
                         header + first, header + first + second + second):
                with self.subTest(size=len(data)):
                    path.write_bytes(data)
                    with self.assertRaises(ValueError):
                        verify(path)

    def test_invalid_years_leave_no_publication(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "example.jsonl"
            for years in (0, -1, True):
                with self.assertRaises(ValueError):
                    write(path, seed=0, years=years)
            self.assertFalse(path.exists())
