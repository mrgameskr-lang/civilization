import csv
import hashlib
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from civsim.competition import start_competition, step_competition
from civsim.collective_storage import write_collective_run
from civsim.model import generate_world
from civsim.regions import regionalize
from civsim.storage import canonical_line
from experiments.phase5d import Spells, run_study
from experiments.collective_forks5d import run_forks


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
        h.observe(5,"petition","soil")
        h.observe(6,"petition","relief")
        self.assertEqual(h.current,1)

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
            saved=Path(temp,"saved")
            write_collective_run(saved,seed=0,years=5,enabled=True)
            on=next(r for r in runs if r["arm"]=="on" and r["year"]=="5")
            self.assertEqual(hashlib.sha256((saved/"years.jsonl").read_bytes()).hexdigest(),on["years_sha256"])
            with gzip.open(out/"events.csv.gz","rt",encoding="utf8",newline="") as stream:
                event=list(csv.DictReader(stream))
            self.assertEqual(len(event),int(on["active_group_years"]))
            self.assertTrue(any(r["year"]=="5" and r["next_closing_support"]=="" for r in event))
            self.assertEqual(sum(int(r["participants"]) for r in event),int(on["participant_years"]))
            forkfile=Path(temp,"forks.json")
            self.assertGreater(run_forks(out,forkfile),0)
            for case in json.loads(forkfile.read_text(encoding="utf8"))["cases"]:
                self.assertEqual(case["suppressed"]["measure"]["participants"],0)
                self.assertGreater(case["delta_actual_minus_suppressed"]["participants"],0)
            for r in runs:
                for g in ("food","ore","tools"):
                    self.assertEqual(int(r["assessed_"+g]),sum(int(r[k+"_"+g]) for k in ("paid","concession","refused")))
            with self.assertRaises(FileExistsError): run_study(out,sample="dev",seeds=1,horizons=(1,),workers=1)
            repeat=run_study(Path(temp,"again"),sample="dev",seeds=1,horizons=(1,5),workers=1,verify=out)
            self.assertEqual(repeat["replayed_checkpoints"],4)
