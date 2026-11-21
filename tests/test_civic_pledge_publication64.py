import csv
import hashlib
import json
import unittest
from itertools import product
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "examples" / "phase6c1-followup"
STUDY = ROOT / "pledges"
COHORTS = {"dev": range(20), "holdout": range(20, 40)}
HORIZONS = (50, 100, 200)


def read_checkpoints():
    rows = {}
    for sample in COHORTS:
        with (STUDY / sample / "runs.csv").open(encoding="utf8", newline="") as stream:
            for row in csv.DictReader(stream):
                key = (int(row["seed"]), row["mode"], row["pledges"], int(row["year"]))
                if key in rows or key[0] not in COHORTS[sample]:
                    raise ValueError(f"duplicate or misplaced checkpoint {key}")
                rows[key] = row
    return rows


class CivilPledgePublicationTests(unittest.TestCase):
    def test_independent_publications_match_the_files_in_the_review(self):
        scientific_files = {
            "annual.jsonl.gz", "countries.csv", "forks.csv", "pairs.csv",
            "party-events.csv.gz", "runs.csv", "same-opening-cases.json", "source.json",
        }
        for sample in COHORTS:
            with self.subTest(sample=sample):
                folder = STUDY / sample
                run = json.loads((folder / "execution.json").read_bytes())
                repeat = json.loads((STUDY / f"replay-{sample}.json").read_bytes())
                self.assertEqual(run["sample"], sample)
                self.assertEqual(repeat["sample"], sample)
                self.assertEqual(set(run["table_sha256"]), scientific_files)
                self.assertEqual(repeat["replayed_checkpoints"], 240)
                self.assertEqual(repeat["verified_files"], len(scientific_files))
                self.assertEqual(repeat["table_sha256"], run["table_sha256"])
                for name, expected in run["table_sha256"].items():
                    with (folder / name).open("rb") as stream:
                        self.assertEqual(hashlib.file_digest(stream, "sha256").hexdigest(), expected, name)
        summary_check = json.loads((STUDY / "replay-analysis.json").read_bytes())
        self.assertEqual(summary_check["raw_checkpoints"], 480)
        self.assertTrue(summary_check["identical"])
        self.assertEqual(hashlib.sha256((STUDY / "outcomes.json").read_bytes()).hexdigest(),
                         summary_check["sha256"])

    def test_complete_factorial_and_fixed_civilian_economy(self):
        rows = read_checkpoints()
        self.assertEqual(set(rows), set(product(range(40), ("observe","consult"), ("off","on"), HORIZONS)))
        fixed = ("economic_years_sha256", "initial_sha256", "food_need", "food_eaten", "food_deficit",
                 "closing_population", "closing_cash", "observed_trade_value", "observed_migrants")
        for (seed, mode, enabled, year), row in rows.items():
            with self.subTest(seed=seed, mode=mode, enabled=enabled, year=year):
                reference = rows[seed, "consult", "off", year]
                self.assertEqual([row[k] for k in fixed], [reference[k] for k in fixed])
                self.assertEqual(row["civic_years_sha256"], rows[seed,mode,"off",year]["register_sha256"])
                signed = int(row["signed"])
                assessed = int(row["assessed"])
                self.assertEqual(signed, assessed + int(row["pending"]))
                self.assertEqual(assessed, sum(int(row[k]) for k in ("joint_kept", "joint_broken", "joint_unknown")))
                if enabled == "off" or mode == "observe":
                    self.assertEqual(signed, 0)
                else:
                    decisions = signed + int(row["defer"]) + int(row["no_agreement"])
                    self.assertEqual(decisions, int(row["source_accepted"]))

    def test_live_compatibility_and_replayed_civilian_journals_agree(self):
        rows = read_checkpoints()
        receipt = json.loads((ROOT / "compatibility.json").read_bytes())
        paths = {(p["seed"], p["mode"], p["pledges"]): p for p in receipt["paths"]}
        expected = {(s, "consult", False) for s in range(40)}
        for s in (0, 20):
            expected.update(((s, "consult", True), (s, "observe", False)))
        self.assertEqual(len(receipt["paths"]), len(expected))
        self.assertEqual(set(paths), expected)
        for (seed, mode, enabled), path in paths.items():
            self.assertEqual([r["year"] for r in path["matched"]], list(HORIZONS))
            for result in path["matched"]:
                key = (seed, mode, "on" if enabled else "off", result["year"])
                row = rows[key]
                self.assertEqual(result["initial"], row["initial_sha256"], key)
                self.assertEqual(result["economy"], row["economic_years_sha256"], key)
                self.assertEqual(result["civic"], row["civic_years_sha256"], key)
                if enabled:
                    self.assertEqual(result["pledge_years_sha256"], row["register_sha256"], key)
