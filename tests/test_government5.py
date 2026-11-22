import hashlib
import json
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from civsim.analysis import summary
from civsim.fiscal_storage import write_government_run
from civsim.government import fiscal_snapshot, start_government, step_government
from civsim.government_audit import audit_fiscal_year
from civsim.model import generate_world
from civsim.regional_production import produce_regions
from civsim.regions import regionalize
from civsim.storage import canonical_line, verify_run


class FiscalIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sim = start_government(regionalize(generate_world(0)))
        cls.years = [step_government(sim, year, "integrated") for year in range(1, 5)]

    def test_private_and_public_are_distinct_owner_accounts(self):
        for y in self.years:
            audit_fiscal_year(json.loads(canonical_line(y)))
            for a in y["government"]["accounts"]:
                private = a["private_close"]
                for good, held in a["public_close"].items():
                    self.assertEqual(a["combined_close"][good], private[good] + held)
            self.assertEqual(sum(c["closing"]["cash"]-c["opening"]["cash"] for c in y["countries"]), 0)

    def test_cross_year_public_balances_and_delayed_capacity(self):
        for before, after in zip(self.years, self.years[1:]):
            for d, e in zip(before["government"]["depots"], after["government"]["depots"], strict=True):
                self.assertEqual(d["closing"], e["opening"])
            for d, e in zip(before["government"]["roads"], after["government"]["roads"], strict=True):
                self.assertEqual(d["next_capacity"], e["capacity"])

    def test_fiscal_audit_rejects_forged_stock_capacity_and_private_cash(self):
        def warehouse(y):
            y["government"]["depots"][0]["closing"]["tools"] += 2
        def double_count(y):
            y["government"]["accounts"][0]["combined_close"]["food"] += 1
        def capacity(y):
            y["government"]["roads"][0]["capacity"] += 48
        def unrecorded_payment(y):
            group = [r for r in y["regions"] if r["owner"] == 0]
            group[0]["closing"]["cash"] += 1
            group[1]["closing"]["cash"] -= 1
        for forge in (warehouse, double_count, capacity, unrecorded_payment):
            with self.subTest(forge=forge.__name__):
                record = deepcopy(self.years[-1])
                forge(record)
                with self.assertRaises(ValueError):
                    audit_fiscal_year(record)

    def test_failed_year_or_policy_switch_does_not_commit(self):
        sim = start_government(regionalize(generate_world(2)))
        step_government(sim, 1, "integrated")
        before = canonical_line(fiscal_snapshot(sim))
        with patch("civsim.government.audit_fiscal_year", side_effect=ValueError("test close failure")):
            with self.assertRaises(ValueError):
                step_government(sim, 2, "integrated")
        for year, mode in ((2,"none"), (4,"integrated")):
            with self.assertRaises(ValueError):
                step_government(sim, year, mode)
        self.assertEqual(before, canonical_line(fiscal_snapshot(sim)))

    def test_public_workers_are_deducted_from_the_entire_private_workforce(self):
        a = regionalize(generate_world(1)).regions[0]
        with self.assertRaises(ValueError):
            produce_regions([a], {a.owner:1000}, public_labor={a.id:a.population//2 + 1})
        p = produce_regions([a], {a.owner:1000}, public_labor={a.id:a.population//2})[a.id]
        self.assertEqual(sum(p["produced"].values()), 0)
        self.assertEqual(p["soil_care"]["workers"] + p["investment"]["construction_labor"] + p["workers"], 0)

    def test_file_replay_summary_and_exclusive_creation(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp, "run")
            write_government_run(out, seed=2, years=2, policy="infrastructure")
            raw = (out / "years.jsonl").read_bytes()
            self.assertEqual(verify_run(out), hashlib.sha256(raw).hexdigest())
            totals = summary(out)
            self.assertEqual((totals["model_version"], totals["policy"]), ("5.0A", "infrastructure"))
            with self.assertRaises(FileExistsError):
                write_government_run(out, years=1)
            (out / "years.jsonl").write_bytes(raw.replace(b'"relief_food":0', b'"relief_food":1', 1))
            with self.assertRaises(ValueError):
                verify_run(out)
