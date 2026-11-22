import csv
import gzip
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from civsim.diplomacy import start_diplomacy, step_diplomacy
from civsim.model import generate_world
from civsim.regions import regionalize
from civsim.storage import canonical_line
from experiments.phase6a1 import contrasts, run_study, terminal_reasons


def rows(path):
    opener = gzip.open if path.suffix==".gz" else open
    with opener(path, "rt", encoding="utf8", newline="") as stream:
        return list(csv.DictReader(stream))


class AidFactorialStudyTests(unittest.TestCase):
    def test_unfilled_quantity_accounts_for_ties_and_minimum_lot(self):
        self.assertEqual(terminal_reasons(43,[(["stock","storage"],0),(["authorized","budget"],1)]),
                         ["budget","minimum_lot","stock","storage"])
        self.assertEqual(terminal_reasons(1,[]),["minimum_lot"])
        self.assertEqual(terminal_reasons(2,[]),["no_border_route"])
    def test_interaction_contrast_uses_the_same_baseline(self):
        values = dict(zip("ABCDEF",(10,14,7,13,18,17),strict=True))
        self.assertEqual(contrasts(values),
                         {"B-A":4,"C-A":-3,"D-A":3,"E-A":8,"F-E":-1,"I":4})

    def test_country_region_and_archive_continuity(self):
        with TemporaryDirectory() as temp:
            out = Path(temp,"study")
            args = dict(sample="dev",seeds=1,horizons=(1,3),workers=1)
            run_study(out,**args)
            runs = rows(out/"runs.csv")
            self.assertEqual(len(runs),12)
            self.assertEqual(len({r["initial_sha256"] for r in runs}),1)
            end = {r["arm"]:r for r in runs if r["year"]=="3"}
            for arm,old in (("A","C"),("E","D")):
                source = start_diplomacy(regionalize(generate_world(0)))
                digest = hashlib.sha256()
                for y in (1,2,3):
                    digest.update(canonical_line(step_diplomacy(source,y,old)))
                self.assertEqual(digest.hexdigest(),end[arm]["years_sha256"])
            panel = rows(out/"region-years.csv.gz")
            nations = rows(out/"country-years.csv.gz")
            self.assertEqual((len(panel),len(nations)),(32*3*6,8*3*6))
            for r in nations:
                match = [p for p in panel if all(p[k]==r[k] for k in ("arm","year","owner"))]
                for key in ("food_eaten","food_deficit","aid_received","aid_sent","aid_freight_food","closing_population"):
                    self.assertEqual(int(r[key]),sum(int(p[key]) for p in match))
                self.assertEqual(int(r["actual_debit"]),int(r["aid_sent"])+int(r["aid_freight_food"]))
                if r["arm"]=="F": self.assertEqual(int(r["budget_overrun"]),0)
                q=int(r["planned_budget"])
                available=q if r["arm"] in "BEF" else 0
                self.assertEqual(available,int(r["available_aid_budget"]))
                self.assertEqual(int(r["unspent_budget"]),max(0,available-int(r["actual_debit"])))
                self.assertEqual(int(r["approved_donor_budget"]),q if int(r["aid_authorized"]) else 0)
            directions=rows(out/"direction-years.csv.gz")
            for arm,r in end.items():
                self.assertEqual(2*int(r["agreements_terminated"]),sum(int(d["agreement_terminated"]) for d in directions if d["arm"]==arm))
            with self.assertRaises(FileExistsError): run_study(out,**args)
            repeat = run_study(Path(temp,"repeat"),**args,verify=out)
            self.assertEqual(repeat["replayed_checkpoints"],12)
