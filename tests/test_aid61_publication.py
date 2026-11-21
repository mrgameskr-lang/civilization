"""Cross-check the published six-arm experiment against source worlds and legacy receipts."""
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import unittest

from civsim.aid61 import verify_run61
from civsim.government import start_government
from civsim.model import GOODS, generate_world
from civsim.regions import regionalize


ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "examples/phase6a1/study"
LEGACY = ROOT / "examples/phase6a/study"
SAMPLES = (("dev", range(20)), ("holdout", range(20, 40)))
YEARS = (50, 100, 200)


def rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        yield from csv.DictReader(stream)


def key(row):
    return int(row["seed"]), row["arm"], int(row["year"])


class PublishedAidStudyTests(unittest.TestCase):
    def test_independent_replay_receipts_cover_the_published_bytes(self):
        for sample, _ in SAMPLES:
            directory = STUDY / sample
            original = json.loads((directory / "execution.json").read_bytes())
            repeat = json.loads((STUDY / f"replay-{sample}.json").read_bytes())
            for receipt in (original, repeat):
                self.assertEqual(receipt["sample"], sample)
                self.assertEqual(receipt["annual_transitions"], 24000)
                self.assertEqual((receipt["archive_6a_A"], receipt["archive_6a_E"]), (60, 60))
            self.assertEqual(repeat["replayed_checkpoints"], 360)
            self.assertEqual(original["table_sha256"], repeat["table_sha256"])
            self.assertEqual(len(original["table_sha256"]), 9)
            for name, expected in repeat["table_sha256"].items():
                with (directory / name).open("rb") as file:
                    self.assertEqual(hashlib.file_digest(file, "sha256").hexdigest(), expected, name)

    def test_all_480_legacy_checkpoints_and_control_worlds(self):
        receipt = json.loads((STUDY.parent / "legacy-ab.json").read_bytes())
        self.assertEqual(receipt["annual_transitions"], 16000)
        ab = {key(r): r["sha256"] for r in receipt["verified"]}
        self.assertEqual(len(ab), 240)
        for sample, seeds in SAMPLES:
            old = {key(r): r for r in rows(LEGACY / sample / "runs.csv")}
            current = {key(r): r for r in rows(STUDY / sample / "runs.csv")}
            self.assertEqual(set(current), {(s, a, y) for s in seeds for a in "ABCDEF" for y in YEARS})
            for s in seeds:
                initial = old[s, "C", 50]["initial_sha256"]
                for y in YEARS:
                    for a in "ABCDEF":
                        self.assertEqual(current[s, a, y]["initial_sha256"], initial)
                    for new_arm, old_arm in (("A", "C"), ("E", "D")):
                        self.assertEqual(current[s, new_arm, y]["years_sha256"], old[s, old_arm, y]["years_sha256"])
                    for a in "AB":
                        self.assertEqual(ab[s, a, y], old[s, a, y]["years_sha256"])

    def test_checkpoint_balances_reconstructed_from_initial_regions(self):
        common = ("closing_population", "closing_cash", "food_eaten", "food_deficit",
                  "aid_sent", "aid_received", "actual_debit", "direct_eaten_delta",
                  *(f"closing_{book}_{g}" for book in ("private", "public") for g in GOODS))
        for sample, seeds in SAMPLES:
            opening = {}
            for seed in seeds:
                world = regionalize(generate_world(seed))
                fiscal = start_government(world)
                for nation in world.nations:
                    local = [r for r in world.regions if r.owner == nation.id]
                    opening[seed, nation.id] = {
                        g: (sum(r.stock[g] for r in local), sum(fiscal.depots[r.id][g] for r in local))
                        for g in GOODS}
            region_totals = defaultdict(Counter)
            for r in rows(STUDY / sample / "regions.csv"):
                totals = region_totals[(*key(r), int(r["owner"]))]
                totals.update({k: int(r[k]) for k in common})
                totals["count"] += 1
            self.assertEqual(len(region_totals), len(seeds) * 6 * len(YEARS) * 8)
            for r in rows(STUDY / sample / "countries.csv"):
                seed, arm, year = key(r)
                owner = int(r["owner"])
                balance = region_totals.pop((seed, arm, year, owner))
                self.assertEqual(balance["count"], 4)
                def number(field):
                    return int(r[field])
                for k in common:
                    self.assertEqual(balance[k], number(k), (seed, arm, year, owner, k))
                self.assertEqual(number("opening_cash") + number("export_value") - number("import_value"),
                                 number("closing_cash"))
                self.assertEqual(number("opening_population") + number("births") - number("deaths")
                                 + number("immigrants") - number("emigrants"), number("closing_population"))
                self.assertEqual(number("food_eaten") + number("food_deficit"), number("food_need"))
                self.assertEqual(number("aid_sent") + number("aid_unshipped"), number("aid_authorized"))
                self.assertEqual(number("aid_sent") + number("aid_freight_food"), number("actual_debit"))
                if arm in "ACD":
                    self.assertEqual(number("aid_authorized"), 0)
                if arm == "F":
                    self.assertEqual(number("budget_overrun"), 0)
                    self.assertEqual(number("overrun_donor_years"), 0)
                for g in GOODS:
                    private, public = opening[seed, owner][g]
                    private += (number("produced_" + g) - number("used_" + g) - number("meal_used_" + g)
                                + number("import_" + g) - number("export_" + g) - number("levied_" + g))
                    public += number("levied_" + g)
                    if g == "food":
                        private += number("relief_food") - number("trade_freight_food") - number("civil_freight_food")
                        public += (number("aid_received") - number("actual_debit") - number("relief_food")
                                   - number("public_freight_food") - number("public_spoil_food")
                                   - number("collection_cost_food"))
                    else:
                        public -= number("works_" + g)
                    self.assertEqual((private, public), (number("closing_private_" + g), number("closing_public_" + g)))
            self.assertFalse(region_totals)

    def test_published_four_year_full_ledger(self):
        self.assertEqual(verify_run61(ROOT / "samples/phase6a1/seed0-capped"),
                         "b5683aecfce60fce74cccedebb43305bcfede4675186db7bd9458778da322c6b")
