"""Cross-check published trajectories against independent runners and pre-3.1 archives."""
import csv
import hashlib
import json
from pathlib import Path
import unittest


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
ROOT = EXAMPLES / "phase31"


def rows(path):
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


class Published31Tests(unittest.TestCase):
    def test_independent_500_year_baselines_and_two_policy_checkpoints(self):
        long_paths = rows(ROOT / "long-primary.csv")
        self.assertEqual(len(long_paths), 20 * 2 * 7)
        baseline = {(r["seed"], r["year"]): r for r in rows(ROOT / "stability/checkpoints.csv")
                    if r["arm"] == "baseline"}
        dev = {(r["seed"], r["arm"], r["horizon"]): r for r in rows(ROOT / "investment/dev/runs.csv")}
        for r in long_paths:
            self.assertEqual(int(r["population_delta"]), int(r["births"]) - int(r["deaths"]))
            if r["policy"] == "off":
                other = baseline[r["seed"], r["year"]]
                self.assertEqual((r["population"], r["deposit"]), (other["pop_close"], other["deposit_close"]))
            if int(r["year"]) <= 200:
                arm = "control" if r["policy"] == "off" else r["policy"]
                other = dev[r["seed"], arm, r["year"]]
                self.assertEqual((r["population"], r["deposit"]), (other["final_population"], other["final_deposit"]))

    def test_disjoint_matched_design_and_unchanged_archival_controls(self):
        historical = {(r["seed"], r["horizon"]): r for r in rows(EXAMPLES / "phase3/runs.csv")
                      if r["arm"] == "capital"}
        designs = set()
        for split, start in (("dev", 0), ("holdout", 20)):
            base = ROOT / "investment" / split
            meta = json.loads((base / "execution.json").read_bytes())
            self.assertEqual(meta["seeds"], list(range(start, start + 20)))
            designs.add(meta["model_sha256"])
            matrix = rows(base / "runs.csv")
            self.assertEqual(len({(r["seed"], r["arm"], r["horizon"]) for r in matrix}), 640)
            for seed in meta["seeds"]:
                self.assertEqual(len({r["initial_sha256"] for r in matrix if int(r["seed"]) == seed}), 1)
            if split == "dev":
                controls = [r for r in matrix if r["arm"] == "control" and r["horizon"] in ("50", "200")]
                self.assertEqual(len(controls), len(historical))
                for r in controls:
                    ref = historical[r["seed"], r["horizon"]]
                    self.assertEqual((r["initial_sha256"], r["years_sha256"]),
                                     (ref["initial_sha256"], ref["years_sha256"]))
        self.assertEqual(len(designs), 1)

    def test_country_and_world_archives_have_the_published_file_digests(self):
        base = ROOT / "stability"
        manifest = json.loads((base / "manifest.json").read_bytes())
        for name, digest in manifest["sha256"].items():
            self.assertEqual(hashlib.sha256((base / name).read_bytes()).hexdigest(), digest, name)
