import csv
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from civsim.model import generate_world
from civsim.competition_storage import write_competition_run
from civsim.politics import start_political, step_political
from civsim.regions import regionalize
from civsim.storage import canonical_line
from experiments.phase5c import DemandProfile, Tenure, run_study


def rows(file):
    with file.open(encoding="utf-8",newline="") as f:
        return list(csv.DictReader(f))


class CompetitionStudyTests(unittest.TestCase):
    def test_colocated_pairs_and_population_weighted_hhi(self):
        d=DemandProfile()
        d.observe({"farm":{"members":90,"demand":"soil"},"industry":{"members":10,"demand":"road"},
                   "consumer":{"members":0,"demand":"none"}})
        d.observe({"farm":{"members":10,"demand":"road"},"industry":{"members":10,"demand":"road"},
                   "consumer":{"members":10,"demand":"none"}})
        self.assertEqual((d.pairs["pairs"],d.pairs["different"]),(4,3))
        self.assertEqual((d.pairs["active_pairs"],d.pairs["active_different"]),(2,1))
        group=next(r for r in d.summary({}) if r["group"]=="farm")
        self.assertAlmostEqual(group["expressed_hhi"],.82)

    def test_completed_spells_exclude_open_and_caretaker(self):
        t=Tenure()
        for y,p in enumerate(("caretaker","mutualists","mutualists","builders","builders"),1):
            t.observe(y,p)
        self.assertEqual(t.snapshot(),{"completed_spells":1,"completed_tenure_years":2,
                         "open_spells":1,"open_tenure_years":2,"longest_observed_tenure":2})

    def test_published_rows_match_5b_and_replay(self):
        with TemporaryDirectory() as tmp:
            output=Path(tmp,"study")
            run_study(output,sample="dev",seeds=1,horizons=(1,5),workers=1)
            results=rows(output/"runs.csv")
            self.assertEqual(len(results),10)
            baseline=start_political(regionalize(generate_world(0)))
            digest=hashlib.sha256()
            for y in range(1,6): digest.update(canonical_line(step_political(baseline,y,True)))
            a=next(r for r in results if r["arm"]=="A" and r["year"]=="5")
            self.assertEqual(a["political_sha256"],digest.hexdigest())
            saved=Path(tmp,"full")
            write_competition_run(saved,seed=0,years=5,arm="C",tax_policy="platform")
            e=next(r for r in results if r["arm"]=="E" and r["year"]=="5")
            for name,key in (("world.json","initial_sha256"),("years.jsonl","years_sha256")):
                self.assertEqual(hashlib.sha256((saved/name).read_bytes()).hexdigest(),e[key])
            self.assertEqual(len({r["initial_sha256"] for r in results}),1)
            self.assertEqual(len(rows(output/"paired.csv")),8)
            elections=rows(output/"elections.csv")
            self.assertEqual({r["arm"] for r in elections},{"C","D","E"})
            self.assertTrue(all(r["year"]=="5" and r["turnover"]=="0" for r in elections))
            for r in elections:
                self.assertEqual(sum(int(r["votes_"+p]) for p in ("stewards","builders","mutualists","restraint")),
                                 int(r["participation_points"]))
            for row in results:
                for g in ("food","ore","tools"):
                    self.assertEqual(int(row["private_stock_"+g])+int(row["public_stock_"+g]),
                                     int(row["combined_stock_"+g]))
            with self.assertRaises(FileExistsError):
                run_study(output,sample="dev",seeds=1,horizons=(1,),workers=1)
            meta=run_study(Path(tmp,"repeat"),sample="dev",seeds=1,horizons=(1,5),workers=1,verify=output)
            self.assertEqual(meta["replayed_checkpoints"],10)
