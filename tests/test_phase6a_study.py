import csv
import gzip
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from civsim.collective import start_collective, step_collective
from civsim.model import generate_world
from civsim.regions import regionalize
from civsim.storage import canonical_line
from experiments.phase6a import country_years, physical, run_study
from experiments.diplomacy_forks6a import choose


def read(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf8", newline="") as stream:
        return list(csv.DictReader(stream))


class DiplomacyStudyTests(unittest.TestCase):
    def test_independent_country_balances_detect_missing_cash(self):
        world = regionalize(generate_world(0))
        row = step_collective(start_collective(world), 1)
        owners = {r.id:r.owner for r in world.regions}
        _, flows, cap = physical(row,world.borders,owners)
        countries = country_years(row,flows)
        self.assertEqual(sum(c["export_value"] for c in countries.values()),
                         sum(t["value"] for t in row["border_market"]["trades"]))
        self.assertEqual(sum(cap.values()),sum(b.capacity for b in world.borders))
        row["countries"][0]["closing"]["cash"] += 1
        with self.assertRaisesRegex(ValueError,"closure"):
            country_years(row, flows)

    def test_forks_only_select_natural_development_decisions(self):
        row = {"seed":"0","arm":"C","year":"2","a":"0","b":"1","agreements_started":"1",
               "ab_trade_value":"200","ba_trade_value":"0"}
        chosen = choose([row,{**row,"year":"3","ab_trade_value":"250"}])
        self.assertEqual({(c["selection"],c["year"]) for c in chosen},{("earliest",2),("highest_exposure",3)})
        self.assertTrue(all(c["intervention"]=={"kind":"no_new_pact","a":0,"b":1} for c in chosen))
        with self.assertRaises(ValueError): choose([{**row,"seed":"20"}])

    def test_paired_histories_ledgers_and_replay(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "study"
            opts = dict(sample="dev", seeds=1, horizons=(1, 3), workers=1)
            run_study(out, **opts)
            runs = read(out / "runs.csv")
            self.assertEqual(len(runs), 8)
            self.assertEqual(len({r["initial_sha256"] for r in runs}), 1)
            initial = regionalize(generate_world(0))
            original = start_collective(initial)
            digest = hashlib.sha256()
            for year in range(1, 4):
                digest.update(canonical_line(step_collective(original, year, True)))
            end = {r["arm"]:r for r in runs if r["year"] == "3"}
            self.assertEqual(end["A"]["years_sha256"], digest.hexdigest())
            self.assertEqual(end["B"]["projected_5d_sha256"], digest.hexdigest())
            self.assertNotEqual(end["B"]["years_sha256"], digest.hexdigest())
            self.assertEqual(len(read(out / "pairs.csv")), 28*8)
            self.assertEqual(len(read(out / "pair-years.csv.gz")), 28*3*4)
            self.assertEqual(len(read(out / "borders.csv.gz")), 2*len(initial.borders)*8)
            nation = read(out / "country-years.csv.gz")
            self.assertEqual(len(nation), 8*3*4)
            for row in nation:
                self.assertEqual(int(row["closing_population"])-int(row["opening_population"]),
                                 int(row["births"])-int(row["deaths"])+int(row["immigrants"])-int(row["emigrants"]))
                self.assertEqual(int(row["closing_cash"])-int(row["opening_cash"]),
                                 int(row["export_value"])-int(row["import_value"]))
            for arm, r in end.items():
                self.assertEqual(int(r["food_deficit"]), sum(int(x["food_deficit"]) for x in nation if x["arm"] == arm))
            with self.assertRaises(FileExistsError):
                run_study(out, **opts)
            again = run_study(root / "again", verify=out, **opts)
            self.assertEqual(again["replayed_checkpoints"], 8)
