import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from civsim.aid61 import write_run61, verify_run61
from civsim.diplomacy_storage import write_diplomacy_run


class AidArchiveTests(unittest.TestCase):
    def test_archive_replay_and_protection(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for arm in ("A","B","C","D","E","F"):
                out = root/arm
                opts = dict(seed=0, years=2, width=18,height=12,nations=3,per_nation=3)
                write_run61(out,arm=arm,**opts)
                self.assertEqual(len(verify_run61(out)),64)
                if arm in ("A","E"):
                    old = root/("old-"+arm)
                    write_diplomacy_run(old,arm={"A":"C","E":"D"}[arm],**opts)
                    for name in ("world.json","years.jsonl"):
                        self.assertEqual((out/name).read_bytes(),(old/name).read_bytes())
                with self.assertRaises(FileExistsError):
                    write_run61(out,arm=arm,**opts)
            path = root/"F"/"manifest.json"
            manifest = json.loads(path.read_bytes())
            path.write_text(json.dumps({**manifest,"model_version":"6.0A"}),encoding="utf8")
            with self.assertRaises(ValueError):
                verify_run61(root/"F")
