"""Cross-check published 6.0A evidence without regenerating forty 200-year worlds in CI."""
import csv
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "examples"
STUDY = ROOT / "phase6a" / "study"
SAMPLES = (("dev", 0), ("holdout", 20))
YEARS = (50, 100, 200)
GOODS = ("food", "ore", "tools")


def rows(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf8", newline="") as src:
        yield from csv.DictReader(src)


def read_json(path):
    return json.loads(path.read_text(encoding="utf8"))


def digest(path):
    with path.open("rb") as src:
        return hashlib.file_digest(src, "sha256").hexdigest()


class DiplomacyPublicationTests(unittest.TestCase):
    def test_independent_tables_and_archived_controls(self):
        tables = {"runs.csv", "countries.csv", "pairs.csv", "paired.csv", "means.csv",
                  "borders.csv.gz", "events.csv.gz", "country-years.csv.gz", "pair-years.csv.gz"}
        for sample, first in SAMPLES:
            folder = STUDY/sample
            run = read_json(folder/"execution.json")
            replay = read_json(STUDY/f"replay-{sample}.json")
            self.assertEqual((run["paths"], run["annual_transitions"]), (80, 16000))
            self.assertEqual((run["archive_5d_A"], run["archive_5d_B"], replay["replayed_checkpoints"]), (60, 60, 240))
            self.assertEqual(set(run["table_sha256"]), tables)
            self.assertEqual(run["table_sha256"], replay["table_sha256"])
            for filename, expected in run["table_sha256"].items():
                self.assertEqual(digest(folder/filename), expected, (sample, filename))
            archive = {(r["seed"], r["year"]): r for r in rows(ROOT/"phase5d"/"study"/sample/"runs.csv")
                       if r["arm"] == "on"}
            checkpoints = list(rows(folder/"runs.csv"))
            self.assertEqual(len(checkpoints), 240)
            self.assertEqual({(int(r["seed"]), r["arm"], int(r["year"])) for r in checkpoints},
                             {(s, arm, y) for s in range(first, first+20) for arm in "ABCD" for y in YEARS})
            for r in checkpoints:
                if r["arm"] in "AB":
                    old = archive[r["seed"], r["year"]]
                    self.assertEqual((r["initial_5d_sha256"], r["projected_5d_sha256"]),
                                     (old["initial_sha256"], old["years_sha256"]))
                    if r["arm"] == "A":
                        self.assertEqual(r["years_sha256"], old["years_sha256"])

    def test_annual_national_food_cash_and_migrants_close_to_checkpoints(self):
        for sample, _ in SAMPLES:
            folder = STUDY/sample
            checks = {(r["seed"], r["arm"], int(r["year"])): r for r in rows(folder/"runs.csv")}
            cumulative = Counter()
            yearly = Counter()
            count = 0
            for r in rows(folder/"country-years.csv.gz"):
                year, country = int(r["year"]), int(r["owner"])
                self.assertEqual((year, country), ((count//8)%200+1, count%8))
                count += 1
                for field in ("food_deficit", "food_need", "aid_sent", "aid_received", "aid_freight_food",
                              "aid_handling_food", "export_value", "import_value", "immigrants", "emigrants"):
                    cumulative[field] += int(r[field])
                for field in ("closing_population","closing_cash","opening_cash"):
                    yearly[field] += int(r[field])
                self.assertEqual(int(r["closing_population"])-int(r["opening_population"]),
                                 int(r["births"])-int(r["deaths"])+int(r["immigrants"])-int(r["emigrants"]))
                self.assertEqual(int(r["closing_cash"])-int(r["opening_cash"]),
                                 int(r["export_value"])-int(r["import_value"]))
                if country == 7:
                    self.assertEqual(yearly["opening_cash"], yearly["closing_cash"])
                    self.assertEqual(cumulative["immigrants"], cumulative["emigrants"])
                    self.assertEqual(cumulative["import_value"], cumulative["export_value"])
                    self.assertEqual(cumulative["aid_sent"], cumulative["aid_received"]+cumulative["aid_handling_food"])
                    if year in YEARS:
                        checkpoint = checks[r["seed"], r["arm"], year]
                        for field, value in {**cumulative, **yearly}.items():
                            self.assertEqual(int(checkpoint[field]), value, (sample, r["seed"], year, field))
                    yearly.clear()
                    if year == 200:
                        cumulative.clear()
            self.assertEqual(count, 128000)

    def test_bilateral_obligations_and_foreign_goods_match_world_totals(self):
        for sample, _ in SAMPLES:
            folder = STUDY/sample
            sums = {}
            for r in rows(folder/"pairs.csv"):
                key = r["seed"], r["arm"], r["year"]
                total = sums.setdefault(key, Counter())
                active = int(r["agreement_years"])
                outcomes = ("agreement_directions_kept","agreement_directions_breached","agreement_directions_no_opportunity")
                self.assertEqual(2*active, sum(int(r[k]) for k in outcomes))
                if int(r["physical_capacity"]) == 0:
                    self.assertEqual(active, 0)
                for d in ("ab_", "ba_"):
                    self.assertEqual(int(r[d+"aid_dispatched"]), int(r[d+"aid_received"])+int(r[d+"aid_handling_food"]))
                    for k in ("trade_value","migrants","aid_received", *("trade_"+g for g in GOODS)):
                        total[k] += int(r[d+k])
            for r in rows(folder/"runs.csv"):
                for k, value in sums[r["seed"], r["arm"], r["year"]].items():
                    self.assertEqual(int(r["border_"+k]), value, (sample, r["seed"], r["year"], k))

    def test_selected_forks_change_only_one_opening_choice(self):
        path = STUDY/"forks-dev.json"
        cases = read_json(path)["cases"]
        receipt = read_json(STUDY/"replay-forks.json")
        self.assertEqual((receipt["sha256"], receipt["cases"], receipt["identical"]), (digest(path), len(cases), True))
        self.assertEqual({(c["intervention"]["kind"], c["selection"]) for c in cases},
                         {(k, s) for k in ("no_new_pact","open_trade","open_migration") for s in ("earliest","highest_exposure")})
        for c in cases:
            self.assertIn(c["seed"], range(20))
            actual, other = c["actual"], c["alternative"]
            self.assertEqual(actual["pair"]["opening"], other["pair"]["opening"])
            self.assertEqual(c["world_delta_actual_minus_alternative"],
                             {k:v-other["world"][k] for k,v in actual["world"].items()})
            pa, pb = actual["pair"]["policy"], other["pair"]["policy"]
            if c["intervention"]["kind"] == "no_new_pact":
                self.assertTrue(pa["agreement_started"])
                self.assertFalse(pb["agreement_active"])
                self.assertEqual(pa["directions"], pb["directions"])
            else:
                src = c["intervention"]["source"]
                self.assertEqual(next(d for d in pa["directions"] if d["source"] != src),
                                 next(d for d in pb["directions"] if d["source"] != src))
                old, new = (next(d for d in policy["directions"] if d["source"] == src) for policy in (pa, pb))
                fields = ({"trade_limit_permille"} if c["intervention"]["kind"] == "open_trade"
                          else {"migration_limit_permille","migration_accept_permille"})
                self.assertTrue(any(old[k] < 1000 for k in fields))
                self.assertEqual({k:new[k] for k in fields}, dict.fromkeys(fields,1000))
                self.assertEqual({k:v for k,v in old.items() if k not in fields},
                                 {k:v for k,v in new.items() if k not in fields})
