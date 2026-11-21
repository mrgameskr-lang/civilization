import csv
import gzip
import hashlib
import json
from pathlib import Path
import unittest

from civsim import supply62
from civsim.model import generate_world
from civsim.regions import regionalize

ROOT = Path(__file__).resolve().parents[1]


def read_forks(phase, engine):
    folder = ROOT/"examples"/phase/"forks"
    cases = {}
    for row in json.loads((folder/"summary.json").read_bytes()):
        path = folder/row["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest()!=row["file_sha256"]:
            raise ValueError("published intervention archive changed")
        lines = gzip.decompress(path.read_bytes()).splitlines(keepends=True)
        if len(lines)!=2:
            raise ValueError("expected two full annual ledgers")
        world = regionalize(generate_world(row["seed"]))
        for line, key in zip(lines,("ordinary_sha256","held_sha256"),strict=True):
            if hashlib.sha256(line).hexdigest()!=row[key]:
                raise ValueError("annual intervention digest mismatch")
            engine.audit62(json.loads(line),geography=world)
        cases[row["seed"],row["year"]] = row
    return cases


def read_grid(phase, sample, arms):
    folder = ROOT/"examples"/phase/"study"/sample
    first_pass = json.loads((folder/"execution.json").read_bytes())
    replay = json.loads((folder.parent/f"replay-{sample}.json").read_bytes())
    if replay["replayed_checkpoints"]!=120 or replay["table_sha256"]!=first_pass["table_sha256"]:
        raise ValueError("independent replay receipts disagree")
    paths = {p.name:p for p in folder.iterdir() if p.name!="execution.json"}
    if set(paths)!=set(first_pass["table_sha256"]):
        raise ValueError("published science tables differ from manifest")
    for name,path in paths.items():
        with path.open("rb") as stream:
            if hashlib.file_digest(stream,"sha256").hexdigest()!=first_pass["table_sha256"][name]:
                raise ValueError(f"published table checksum mismatch: {name}")
    with (folder/"runs.csv").open(encoding="utf-8",newline="") as stream:
        rows = list(csv.DictReader(stream))
    first = 0 if sample=="dev" else 20
    expected = {(seed,arm,year) for seed in range(first,first+20) for arm in arms for year in (50,100,200)}
    if len(rows)!=len(expected) or {(int(r["seed"]),r["arm"],int(r["year"])) for r in rows}!=expected:
        raise ValueError("incomplete release grid")
    return rows


class PublishedDepotTests(unittest.TestCase):
    def test_full_same_opening_ledgers_include_private_crowdout(self):
        cases = read_forks("phase6b1",supply62)
        self.assertEqual(set(cases),{(0,4),(1,5),(2,42)})
        normal, held = (cases[2,42][k] for k in ("ordinary","held"))
        self.assertEqual((normal["public_cargo"],held["public_cargo"]), (66,0))
        self.assertEqual(normal["domestic_private_cargo"]-held["domestic_private_cargo"],-80)
        self.assertEqual(normal["unmet"]-held["unmet"],80)
        self.assertEqual(normal["foreign_private_cargo"],held["foreign_private_cargo"])

    def test_all_archived_f_trajectories_and_receipts(self):
        for sample in ("dev","holdout"):
            rows = read_grid("phase6b1",sample,"AB")
            with (ROOT/"examples/phase6a1/study"/sample/"runs.csv").open(encoding="utf-8",newline="") as f:
                original = {(r["seed"],r["year"]):r for r in csv.DictReader(f) if r["arm"]=="F"}
            for r in rows:
                if r["arm"]=="A":
                    base = original[r["seed"],r["year"]]
                    for field in ("initial_sha256","years_sha256"):
                        self.assertEqual(r[field],base[field])
                self.assertEqual(int(r["aid_budget_overrun"]),0)
