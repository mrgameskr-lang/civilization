import csv
import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]/"examples"
CURRENT = ROOT/"phase6c1"


def read(path):
    with path.open(encoding="utf8",newline="") as f:
        return list(csv.DictReader(f))


def key(row):
    return int(row["seed"]),int(row["year"]),int(row["owner"])


class ReleasedCivicStudyTests(unittest.TestCase):
    def test_full_control_matches_both_civil_registers_and_the_historical_path(self):
        base = CURRENT/"baseline"
        receipt = json.loads((base/"receipt.json").read_bytes())
        self.assertEqual((receipt["checkpoint_matches"],receipt["world_years"]),(120,8000))
        for name,expected in receipt["table_sha256"].items():
            self.assertEqual(hashlib.sha256((base/name).read_bytes()).hexdigest(),expected)
        replay = {(int(r["seed"]),int(r["year"])):r for r in read(base/"checkpoints.csv")}
        self.assertEqual(len(replay),120)
        for sample,first in (("dev",0),("holdout",20)):
            archived = {(int(r["seed"]),int(r["year"])):r for r in read(ROOT/"phase6b2/study"/sample/"runs.csv")
                        if r["arm"]=="D"}
            observed = read(CURRENT/"diplomacy"/sample/"runs.csv")
            self.assertEqual(len(observed),120)
            self.assertEqual({(int(r["seed"]),int(r["year"]),r["mode"]) for r in observed},
                             {(s,y,m) for s in range(first,first+20) for y in (50,100,200)
                              for m in ("observe","consult")})
            for row in observed:
                k = int(row["seed"]),int(row["year"])
                self.assertEqual(replay[k]["years_sha256"],row["economic_years_sha256"])
                self.assertEqual(replay[k]["initial_sha256"],archived[k]["initial_sha256"])
                self.assertEqual(row["economic_years_sha256"],archived[k]["years_sha256"])
                self.assertEqual(int(row["pair_years"]),28*k[1])

    def test_country_receipts_and_regional_addresses_balance(self):
        base = CURRENT/"baseline"
        national = {key(r):r for r in read(base/"country-totals.csv")}
        self.assertEqual(len(national),960)
        addresses = read(base/"regional-closes.csv")
        self.assertEqual(len(addresses),3840)
        self.assertEqual(len({(r["seed"],r["year"],r["region"]) for r in addresses}),3840)
        totals = {}
        for r in addresses:
            v = totals.setdefault(key(r),[0,0])
            v[0] += int(r["population_close"])
            v[1] += int(r["cash"])
        for sample in ("dev","holdout"):
            for old in read(ROOT/"phase6b2/study"/sample/"countries.csv"):
                if old["arm"]!="D":
                    continue
                k = key(old)
                new = national[k]
                self.assertEqual(totals[k],[int(old["closing_population"]),int(old["closing_cash"])])
                for field, source in (("population_close","closing_population"),("cash","closing_cash"),
                     ("food_eaten","food_eaten"),("food_unmet","food_deficit"),("food_need","food_need"),
                     ("support_points","support_x_members"),("discontent_points","discontent_x_members"),
                     ("members","member_years")):
                    self.assertEqual(new[field],old[source])
                self.assertLessEqual(int(new["turnovers"])+int(new["installations"]),int(new["elections"]))
