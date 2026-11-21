"""Check the public 5D data against both repeats, historical records and annual nation rows."""
import csv
import gzip
import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1] / "examples"
DATA = ROOT / "phase5d"
GOODS = ("food", "ore", "tools")


def rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


class CollectivePublicationTests(unittest.TestCase):
    def test_frozen_outputs_replay_and_project_to_5c(self):
        expected_files = {"runs.csv", "countries.csv", "regions.csv", "actions.csv", "responses.csv",
                          "paired.csv", "means.csv", "cases.json", "events.csv.gz"}
        for sample, first in (("dev", 0), ("holdout", 20)):
            with self.subTest(sample=sample):
                folder = DATA/"study"/sample
                receipt = json.loads((folder/"execution.json").read_text(encoding="utf-8"))
                repeat = json.loads((folder.parent/f"replay-{sample}.json").read_text(encoding="utf-8"))
                self.assertEqual((receipt["paths"], receipt["annual_transitions"]), (40, 8000))
                self.assertEqual((repeat["replayed_checkpoints"], receipt["archived_5c_checkpoints"]), (120, 60))
                self.assertEqual(receipt["table_sha256"], repeat["table_sha256"])
                self.assertEqual(set(receipt["table_sha256"]), expected_files)
                for name, digest in receipt["table_sha256"].items():
                    with (folder/name).open("rb") as stream:
                        self.assertEqual(hashlib.file_digest(stream, "sha256").hexdigest(), digest, name)
                collected = rows(folder/"runs.csv")
                self.assertEqual(len(collected), 120)
                self.assertEqual({(int(r["seed"]), r["arm"], int(r["year"])) for r in collected},
                                 {(s, a, y) for s in range(first, first+20)
                                  for a in ("off", "on") for y in (50, 100, 200)})
                old = {(r["seed"], r["year"]): r["years_sha256"]
                       for r in rows(ROOT/"phase5c"/"study"/sample/"runs.csv") if r["arm"] == "C"}
                self.assertEqual({(r["seed"], r["year"]): r["years_sha256"] for r in collected
                                  if r["arm"] == "off"}, old)

    def test_annual_country_panels_sum_to_published_paths(self):
        for sample in ("dev", "holdout"):
            folder = DATA/"study"/sample
            checkpoints = {(r["seed"], r["arm"], r["year"]): r for r in rows(folder/"runs.csv")}
            totals, populations, unique = {}, {}, set()
            with gzip.open(DATA/"country-years"/f"{sample}.csv.gz", "rt", encoding="utf-8", newline="") as stream:
                for r in csv.DictReader(stream):
                    key = (r["seed"], r["arm"])
                    point = (*key, r["year"])
                    ident = (*point, r["owner"])
                    self.assertNotIn(ident, unique)
                    unique.add(ident)
                    total = totals.setdefault(key, dict.fromkeys(("food_need", "food_unmet", "withheld_workers",
                                            *(g+"_output" for g in GOODS), *("refused_"+g for g in GOODS)), 0))
                    for k in total:
                        total[k] += int(r[k])
                    populations[point] = populations.get(point, 0) + int(r["closing_population"])
                    if r["owner"] == "7" and point in checkpoints:
                        c = checkpoints[point]
                        for k, n in total.items():
                            self.assertEqual(n, int(c["food_deficit" if k == "food_unmet" else k]), (point, k))
                        self.assertEqual(populations[point], int(c["final_population"]))
            self.assertEqual(len(unique), 64000)
