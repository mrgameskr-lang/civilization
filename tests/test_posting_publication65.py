import csv
import gzip
import hashlib
import json
from pathlib import Path
import unittest


DATA = Path(__file__).resolve().parents[1] / "examples" / "phase6c1-m1"
HORIZONS = (50, 100, 200)


def csv_rows(path):
    with path.open(encoding="utf8", newline="") as stream:
        return list(csv.DictReader(stream))


class ReviewedPostingDataTests(unittest.TestCase):
    def test_disabled_policy_matches_all_three_pr18_streams_and_both_studies(self):
        receipt = json.loads((DATA / "pr18-replay.json").read_bytes())
        historical = {(r["seed"], r["year"]): r for r in receipt["checkpoints"]}
        self.assertEqual(len(receipt["checkpoints"]), 120)
        self.assertEqual(set(historical), {(s, y) for s in range(40) for y in HORIZONS})
        prior = DATA.parent / "phase6c1-followup" / "pledges"
        for cohort, start in (("dev", 0), ("holdout", 20)):
            sources = {(int(r["seed"]), int(r["year"])): r for r in csv_rows(prior / cohort / "runs.csv")
                       if r["mode"] == "consult" and r["pledges"] == "on"}
            rows = csv_rows(DATA / cohort / "runs.csv")
            by_key = {(int(r["seed"]), int(r["year"]), r["arm"]): r for r in rows}
            self.assertEqual(len(rows), 180)
            for seed in range(start, start + 20):
                for year in HORIZONS:
                    check = historical[seed, year]
                    source = sources[seed, year]
                    for name in ("economic_years_sha256", "civic_years_sha256", "register_sha256"):
                        self.assertEqual(check[name], source[name], (seed, year, name))
                    a = by_key[seed, year, "A"]
                    fixed = by_key[seed, year, "A_fixed"]
                    b = by_key[seed, year, "B"]
                    self.assertEqual(a["economy_sha256"], check["economic_years_sha256"])
                    self.assertEqual(a["initial_sha256"], b["initial_sha256"])
                    self.assertEqual(fixed["affiliation_sha256"], "")
                    self.assertTrue(b["affiliation_sha256"])
                    for k in fixed:
                        if k != "arm" and fixed[k] != "":
                            self.assertEqual(fixed[k], b[k], (seed, year, k))

    def test_archived_first_eight_affiliations_match_the_separately_published_seed_zero(self):
        preview = [json.loads(line) for line in (DATA / "seed0-eight-years.jsonl").read_bytes().splitlines()]
        self.assertEqual((preview[0]["seed"], preview[0]["years"], preview[0]["semantics"]),
                         (0, 8, "registered_assignment"))
        with gzip.open(DATA / "dev/seed-00/affiliations.jsonl.gz", "rb") as stream:
            for year, row in enumerate(preview[1:], 1):
                self.assertEqual(row["year"], year)
                self.assertEqual(row["register"], json.loads(stream.readline()))

    def test_every_final_b_replay_matches_the_corresponding_fixed_economy_and_new_register(self):
        receipt = json.loads((DATA / "register-repeat.json").read_bytes())
        self.assertEqual((receipt["world_years"], receipt["matched_economy"], receipt["matched_affiliation"]),
                         (8000, 120, 120))
        for name, digest in receipt["code_sha256"].items():
            self.assertEqual(hashlib.sha256((DATA.parents[1] / name).read_bytes()).hexdigest(), digest)
        repeat = {(r["seed"], r["year"]): r for r in receipt["checkpoints"]}
        self.assertEqual(len(repeat), 120)
        for cohort in ("dev", "holdout"):
            rows = csv_rows(DATA / cohort / "runs.csv")
            for row in rows:
                if row["arm"] == "B":
                    expected = repeat[int(row["seed"]), int(row["year"])]
                    self.assertEqual(row["affiliation_sha256"], expected["affiliation_sha256"])
                    self.assertEqual(row["economy_sha256"], expected["economy_sha256"])

    def test_reviewed_cohort_files_have_the_verified_bytes(self):
        for cohort in ("dev", "holdout"):
            folder = DATA / cohort
            manifest = json.loads((folder / "execution.json").read_bytes())
            expected = {"runs.csv", "regions.csv"}
            for seed in manifest["seeds"]:
                expected.update(f"seed-{seed:02d}/{name}" for name in
                                ("cases.json", "economic-regions.csv.gz", "affiliations.jsonl.gz"))
            self.assertEqual(len(expected), 62)
            self.assertEqual(set(manifest["table_sha256"]), expected)
            for name, digest in manifest["table_sha256"].items():
                with (folder / name).open("rb") as stream:
                    self.assertEqual(hashlib.file_digest(stream, "sha256").hexdigest(), digest, name)
            repeat = json.loads((DATA / f"replay-{cohort}.json").read_bytes())
            self.assertEqual(len(repeat["identical_seed_files"]), 3)
            for name in repeat["identical_seed_files"]:
                self.assertEqual(repeat["table_sha256"][name], manifest["table_sha256"][name], name)
        summary = json.loads((DATA / "replay-analysis.json").read_bytes())
        self.assertTrue(summary["byte_identical"])
        self.assertEqual(summary["register_checkpoints"], 120)
        self.assertEqual(summary["summary_sha256"], hashlib.sha256((DATA / "outcomes.json").read_bytes()).hexdigest())
