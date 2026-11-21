import csv
import gzip
from itertools import islice
from pathlib import Path
import unittest

from civsim import peace62
from civsim.civic_observer63 import closed_directions, run
from civsim.model import generate_world
from civsim.regions import regionalize
from civsim.storage import canonical_line


class LiveCivilObserverTests(unittest.TestCase):
    def test_modes_keep_the_historical_economic_bytes(self):
        historical = peace62.start62(regionalize(generate_world(0)))
        expected = [canonical_line(peace62.step62(historical,t,"D")) for t in (1,2)]
        for mode in ("off","observe","consult"):
            with self.subTest(mode=mode):
                rows = list(run(seed=0, years=2, mode=mode))
                self.assertEqual([canonical_line(economy) for economy,_ in rows],expected)
                if mode=="off":
                    self.assertEqual([side for _,side in rows],[None,None])
                else:
                    self.assertEqual(len(rows[1][1]),28)
                    self.assertTrue(all(not p["evidence"] for p in rows[0][1].values()))
                    previous = closed_directions(0,rows[0][0])
                    self.assertEqual(sum(len(p["evidence"]) for p in rows[1][1].values()),len(previous))
                    self.assertTrue(all(p["evidence_year"]==1 for p in rows[1][1].values() if p["observed"]))

    def test_live_settlement_matches_archived_border_evidence(self):
        economy,_ = next(run(seed=0,years=1,mode="off"))
        actual = closed_directions(0,economy)
        path = Path(__file__).resolve().parents[1]/"examples/phase6b2/study/dev/foreign-years.csv.gz"
        with gzip.open(path,"rt",encoding="utf8",newline="") as stream:
            archive = (r for r in csv.DictReader(stream) if r["seed"]=="0" and r["arm"]=="D" and r["year"]=="1")
            for prior,live in zip(archive,actual,strict=True):
                for k,v in live.items():
                    self.assertEqual(prior[k],str(v))

    def test_negative_horizon_and_unknown_mode(self):
        for years,mode in ((-1,"observe"),(2,"unknown")):
            with self.assertRaises(ValueError):
                list(islice(run(0,years,mode),1))
