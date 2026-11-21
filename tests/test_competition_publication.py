"""Verify the published 40-seed trial and replay receipts without rerunning 80,000 years."""
import csv
import hashlib
import json
from pathlib import Path
import unittest


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


class CompetitionPublicationTests(unittest.TestCase):
    def test_replay_receipts_cover_the_archived_five_arm_matrix(self):
        directory = EXAMPLES / "phase5c" / "study"
        tables = {"countries.csv", "elections.csv", "means.csv", "negative.csv", "paired.csv",
                  "parties.csv", "preferences.csv", "regions.csv", "runs.csv", "cases.json"}
        for sample, first in (("dev", 0), ("holdout", 20)):
            with self.subTest(sample=sample):
                cohort = directory / sample
                receipt = read_json(cohort / "execution.json")
                replay = read_json(directory / f"replay-{sample}.json")
                self.assertEqual(set(receipt["table_sha256"]), tables)
                for doc in (receipt, replay):
                    self.assertEqual((doc["sample"], doc["first_seed"], doc["seeds"], doc["horizons"]),
                                     (sample, first, 20, [50, 100, 200]))
                    self.assertEqual((doc["paths"], doc["annual_transitions"], doc["archived_5b_checkpoints"]),
                                     (100, 20000, 60))
                self.assertEqual(replay["replayed_checkpoints"], 300)
                self.assertEqual(receipt["table_sha256"], replay["table_sha256"])
                for filename, digest in receipt["table_sha256"].items():
                    with (cohort / filename).open("rb") as f:
                        self.assertEqual(hashlib.file_digest(f, "sha256").hexdigest(), digest, filename)

                rows = read_rows(cohort / "runs.csv")
                keys = {(int(r["seed"]), r["arm"], int(r["year"])) for r in rows}
                expected = {(s, arm, year) for s in range(first, first + 20) for arm in "ABCDE"
                            for year in (50, 100, 200)}
                self.assertEqual(len(rows), len(keys))
                self.assertEqual(keys, expected)
                archive = {(int(r["seed"]), int(r["year"])): r for r in read_rows(
                    EXAMPLES / "phase5b" / "study" / sample / "runs.csv") if r["arm"] == "on"}
                for r in rows:
                    old = archive[int(r["seed"]), int(r["year"])]
                    self.assertEqual(r["initial_political_sha256"], old["initial_political_sha256"])
                    if r["arm"] == "A":
                        self.assertEqual(r["political_sha256"], old["years_sha256"])
