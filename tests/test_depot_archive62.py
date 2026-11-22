from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from civsim.depot62_cli import archive


class PublicDepotArchiveTests(unittest.TestCase):
    def test_replay_and_refuse_duplicate_destination(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp)/"public"
            meta = dict(schema=1,model_version="6.0B1",arm="B",seed=0,years=2)
            archive(out,meta=meta)
            self.assertEqual(len(archive(out)),64)
            with self.assertRaises(FileExistsError):
                archive(out,meta=meta)
            with (out/"years.jsonl").open("ab") as file:
                file.write(b"{}\n")
            with self.assertRaises(ValueError):
                archive(out)
