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
        file = ROOT / "long-primary.csv"
        long_paths = rows(file)
        horizons = (50, 100, 150, 200, 300, 400, 500)
        expected = {(s, p, y) for s in range(20) for p in ("off", "combined-multi") for y in horizons}
        self.assertEqual(len(long_paths), len(expected))
        self.assertEqual({(int(r["seed"]), r["policy"], int(r["year"])) for r in long_paths}, expected)
        self.assertEqual(hashlib.sha256(file.read_bytes()).hexdigest(),
                         "ce0c2ac1e61d4379c2908b854e392fcb40fa26ec8d9e64ab89df921ee0489bb3")
        baseline = {(r["seed"], r["year"]): r for r in rows(ROOT / "stability/checkpoints.csv")
                    if r["arm"] == "baseline"}
        dev = {(r["seed"], r["arm"], r["horizon"]): r for r in rows(ROOT / "investment/dev/runs.csv")}
        last = {}
        for r in long_paths:
            key = r["seed"], r["policy"]
            previous_year, population = last.get(key, (0, int(dev[r["seed"], "control", "50"]["initial_population"])))
            self.assertEqual(int(r["interval_start"]), previous_year + 1)
            self.assertEqual(int(r["population"]), population + int(r["population_delta"]))
            self.assertLessEqual(int(r["interval_min_population"]), min(population, int(r["population"])))
            self.assertGreaterEqual(int(r["interval_max_population"]), max(population, int(r["population"])))
            last[key] = int(r["year"]), int(r["population"])
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
