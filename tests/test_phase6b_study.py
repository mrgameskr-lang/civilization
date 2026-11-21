import csv
import gzip
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from civsim.diplomacy61 import start61, step61
from civsim.model import generate_world
from civsim.regions import regionalize
from civsim.storage import canonical_line
from experiments.phase6b import run_study


def rows(path):
    file=gzip.open if path.suffix==".gz" else open
    with file(path,"rt",encoding="utf8",newline="") as f: return list(csv.DictReader(f))


class PublicTransportStudyTests(unittest.TestCase):
    def test_raw_balances_and_baseline_replay(self):
        with TemporaryDirectory() as temp:
            folder=Path(temp)/"study"
            opts=dict(sample="dev",seeds=1,horizons=(1,3),workers=1)
            run_study(folder,**opts)
            runs=rows(folder/"runs.csv")
            self.assertEqual(len(runs),4)
            world=start61(regionalize(generate_world(0)))
            sha=hashlib.sha256()
            for y in (1,2,3): sha.update(canonical_line(step61(world,y,"F")))
            self.assertEqual(next(r["years_sha256"] for r in runs if r["arm"]=="A" and r["year"]=="3"),sha.hexdigest())
            region=rows(folder/"region-years.csv.gz")
            national=rows(folder/"country-years.csv.gz")
            self.assertEqual((len(region),len(national)),(32*3*2,8*3*2))
            for row in national:
                lookup=[r for r in region if all(r[k]==row[k] for k in ("seed","arm","year","owner"))]
                for k in ("food_need","food_eaten","food_deficit","aid_sent","depot_freight_food","closing_population"):
                    self.assertEqual(int(row[k]),sum(int(r[k]) for r in lookup))
                self.assertLessEqual(int(row["aid_total_debit"]),int(row["aid_budget"]))
            b=next(r for r in runs if r["arm"]=="B" and r["year"]=="3")
            self.assertEqual(int(b["food_deficit"]),sum(int(r["food_deficit"]) for r in region if r["arm"]=="B"))
            with self.assertRaises(FileExistsError): run_study(folder,**opts)
            meta=run_study(Path(temp)/"again",**opts,verify=folder)
            self.assertEqual(meta["replayed_checkpoints"],4)
