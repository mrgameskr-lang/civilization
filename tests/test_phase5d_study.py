import csv
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from civsim.competition import start_competition, step_competition
from civsim.model import generate_world
from civsim.regions import regionalize
from civsim.storage import canonical_line
from experiments.phase5d import Spells, run_study


def rows(file):
    with file.open(encoding="utf8", newline="") as f:
        return list(csv.DictReader(f))


class CollectiveStudyTests(unittest.TestCase):
    def test_spells_action_change_and_right_censor(self):
        h=Spells()
        h.observe(1,"petition")
        h.observe(2,"petition")
        h.observe(3,"strike")
        self.assertEqual((h.completed,h.current),( [2],1))
        h.observe(4,"accept")
        self.assertEqual((h.completed,h.current),([2,1],0))

    def test_matching_arms_control_projection_and_goods(self):
        with TemporaryDirectory() as temp:
            out=Path(temp,"study")
            run_study(out,sample="dev",seeds=1,horizons=(1,5),workers=1)
            runs=rows(out/"runs.csv")
            self.assertEqual(len(runs),4)
            self.assertEqual(len({r["initial_sha256"] for r in runs}),1)
            ref=start_competition(regionalize(generate_world(0)))
            h=hashlib.sha256()
            for year in range(1,6): h.update(canonical_line(step_competition(ref,year,"C")))
            off=next(r for r in runs if r["arm"]=="off" and r["year"]=="5")
            self.assertEqual(off["years_sha256"],h.hexdigest())
            for r in runs:
                for g in ("food","ore","tools"):
                    self.assertEqual(int(r["assessed_"+g]),sum(int(r[k+"_"+g]) for k in ("paid","concession","refused")))
            with self.assertRaises(FileExistsError): run_study(out,sample="dev",seeds=1,horizons=(1,),workers=1)
            repeat=run_study(Path(temp,"again"),sample="dev",seeds=1,horizons=(1,5),workers=1,verify=out)
            self.assertEqual(repeat["replayed_checkpoints"],4)
