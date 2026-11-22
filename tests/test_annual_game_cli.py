import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class GameSaveTests(unittest.TestCase):
    def test_move_reloads_on_next_year_and_original_slot_survives(self):
        with tempfile.TemporaryDirectory() as root:
            def run(*args):
                return subprocess.run([sys.executable,"-B","-m","civsim.annual_game",*args],
                                      cwd=Path(__file__).resolve().parents[1], capture_output=True,check=True)
            paths = [str(Path(root)/f"year-{i}.json") for i in range(4)]
            run("new","--seed","0","--out",paths[0])
            run("step",paths[0],"--out",paths[1])
            before=Path(paths[1]).read_bytes()
            moved=json.loads(run("step",paths[1],"--move","5","5","4","1","--out",paths[2]).stdout)
            after=json.loads(run("step",paths[2],"--out",paths[3]).stdout)
            self.assertTrue(moved["receipt"]["ok"])
            self.assertEqual(moved["closing_away"],[[5,4,1]])
            slot=json.loads(Path(paths[2]).read_bytes())
            self.assertEqual(slot["closing_away"],[[5,4,1]])
            self.assertEqual(after["opening_away"],moved["closing_away"])
            self.assertEqual(Path(paths[1]).read_bytes(),before)
            self.assertEqual(json.loads(run("show",paths[3]).stdout)["year"],3)
            slot["closing_away"]=[]
            edited=Path(root)/"edited.json"
            edited.write_text(json.dumps(slot),encoding="utf8")
            with self.assertRaises(subprocess.CalledProcessError):
                run("show",str(edited))
