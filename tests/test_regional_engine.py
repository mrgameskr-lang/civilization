from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from civsim.audit import BalanceError
from civsim.border import border_market
from civsim.model import generate_world
from civsim.regional_engine import RegionalPolicy, audit_borders, audit_national_year, state, step_regional
from civsim.regional_storage import write_regional_run
from civsim.regions import audit_regions, regionalize
from civsim.storage import canonical_line, verify_run
from tests.test_cli import call_cli


class RegionalCycleTests(unittest.TestCase):
    def test_annual_continuity_for_all_account_stages(self):
        w = regionalize(generate_world(6))
        start_cash = sum(n.cash for n in w.nations)
        previous = {r.id: state(r) for r in w.regions}
        for y in range(1, 8):
            row = step_regional(w, y)
            audit_regions(w)
            audit_national_year(row)
            self.assertEqual(len(row["regions"]), 32)
            for r in row["regions"]:
                self.assertEqual(previous[r["id"]], r["opening"])
                self.assertEqual(r["opening"]["population"] + r["demography"]["births"]
                                 - r["demography"]["deaths"] + r["demography"]["immigrants"]
                                 - r["demography"]["emigrants"], r["closing"]["population"])
            previous = {r["id"]: r["closing"] for r in row["regions"]}
            self.assertEqual(sum(n.cash for n in w.nations), start_cash)
        row["countries"][0]["closing"]["stock"]["food"] += 1
        with self.assertRaises(BalanceError):
            audit_national_year(row)

    def test_diagnostic_leaves_economic_path_and_receipts_unchanged(self):
        w = regionalize(generate_world(1))
        other = deepcopy(w)
        a = step_regional(w, 1, diagnose_capacity=True)
        diag = a.pop("capacity_diagnostic")
        b = step_regional(other, 1)
        self.assertEqual(canonical_line(a), canonical_line(b))
        self.assertEqual(w, other)
        self.assertEqual(len(diag), 32)
        self.assertEqual(sum(d["actual_unmet"] for d in diag), sum(r["consumption"]["food_unmet"] for r in a["regions"]))

    def test_closure_removes_freight_and_migration_and_failed_year_is_atomic(self):
        w = regionalize(generate_world(3))
        closed = tuple(sorted((edge.a, edge.b) for edge in w.roads))
        before = deepcopy(w)
        with self.assertRaisesRegex(ValueError, "nonexistent"):
            step_regional(w, 1, RegionalPolicy(closed_roads=((0, 999),)))
        with patch("civsim.regional_engine.audit_national_year", side_effect=BalanceError("bad balance")):
            with self.assertRaises(BalanceError):
                step_regional(w, 1)
        self.assertEqual(before, w)
        row = step_regional(w, 1, RegionalPolicy(logistics="unlimited", closed_roads=closed))
        self.assertEqual(row["domestic"]["shipments"], [])
        for m in row["moves"]:
            self.assertNotEqual(w.regions[m["source"]].owner, w.regions[m["target"]].owner)

    def test_cross_border_orders_pay_food_and_cash_on_the_exact_adjacent_route(self):
        w = regionalize(generate_world(4, 12, 4, 2))
        road = w.borders[0]
        seller, buyer = w.regions[road.a], w.regions[road.b]
        for r in w.regions:
            r.stock = {"food": 100, "ore": 0, "tools": 0}
            r.population = 100
            r.cash = 0
        seller.stock["food"] = 1000
        buyer.stock["food"] = 0
        buyer.cash = 2000
        before = {r.id: state(r) for r in w.regions}
        result = border_market(w.regions, [road])
        self.assertEqual(len(result["trades"]), 1)
        t = result["trades"][0]
        self.assertEqual((t["seller"], t["buyer"]), (seller.id, buyer.id))
        self.assertLessEqual(t["quantity"], road.capacity)
        closes = {r.id: (r.stock, r.cash) for r in w.regions}
        audit_borders(w.regions, [road], result, before, closes)
        t["cost_food"] += 1
        with self.assertRaises(BalanceError):
            audit_borders(w.regions, [road], result, before, closes)

    def test_invalid_border_tiles_and_fictitious_offset_account_are_rejected(self):
        from dataclasses import replace
        w = regionalize(generate_world(0))
        edge = w.borders[0]
        bad = replace(edge, path=(edge.path[0], len(w.tiles)+1, *edge.path[2:]))
        w.borders[0] = bad
        with self.assertRaises(ValueError):
            step_regional(w, 1)
        self.assertEqual(w.year, 0)
        w.borders[0] = edge
        record = step_regional(w, 1)
        for boundary in ("opening", "closing"):
            record["countries"][0][boundary]["cash"] -= 2
            record["countries"][1][boundary]["cash"] += 2
        with self.assertRaisesRegex(BalanceError, "endpoint"):
            audit_national_year(record)

    def test_cli_paired_replay_export_and_tamper_detection(self):
        with TemporaryDirectory() as tmp:
            out, repeat = Path(tmp, "sample"), Path(tmp, "repeat")
            run = call_cli("regional", "--out", out, "--years", 2, "--seed", 5,
                           "--logistics", "unlimited", "--investment-scope", "national", "--no-soil-care")
            self.assertEqual(run.returncode, 0, run.stderr)
            original = (out / "years.jsonl").read_bytes()
            write_regional_run(repeat, seed=5, years=2, policy=RegionalPolicy("unlimited", "national", False))
            self.assertEqual(verify_run(out), verify_run(repeat))
            self.assertEqual((repeat / "years.jsonl").read_bytes(), original)
            self.assertNotEqual(call_cli("regional", "--out", out).returncode, 0)
            self.assertEqual((out / "years.jsonl").read_bytes(), original)
            panel = Path(tmp, "panel.csv")
            self.assertEqual(call_cli("analyze", out, "--csv", panel).returncode, 0)
            self.assertEqual(len(panel.read_text(encoding="utf-8-sig").splitlines()), 65)
            year = json.loads(original.splitlines()[0])
            year["regions"][0]["opening"]["soil"] += 1
            (out / "years.jsonl").write_bytes(canonical_line(year) + original.splitlines(keepends=True)[1])
            with self.assertRaisesRegex(ValueError, "year 1"):
                verify_run(out)
