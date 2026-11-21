from copy import deepcopy
import unittest
from unittest.mock import patch

from civsim.diplomacy import diplomacy_snapshot, start_diplomacy, step_diplomacy
from civsim.diplomacy61 import audit_rules61, fork61, snapshot61, start61, step61
from civsim.model import generate_world
from civsim.regions import regionalize
from civsim.storage import canonical_line


def make():
    return regionalize(generate_world(0,18,12,3),3)


class Annual61Tests(unittest.TestCase):
    def test_two_controls_match_archived_rules_at_every_step(self):
        for arm,reference in (("A","C"),("E","D")):
            sim,old = start61(make()),start_diplomacy(make())
            self.assertEqual(snapshot61(sim),diplomacy_snapshot(old))
            for year in range(1,10):
                self.assertEqual(canonical_line(step61(sim,year,arm)),canonical_line(step_diplomacy(old,year,reference)))

    def test_instruments_do_not_appear_in_closed_arms(self):
        for arm in ("B","C","D","F"):
            with self.subTest(arm=arm):
                sim,previous = start61(make()),None
                for year in range(1,9):
                    row = step61(sim,year,arm)
                    audit_rules61(row,previous)
                    ctx = row["diplomacy"]
                    self.assertEqual(ctx["phase61"]["arm"],arm)
                    for pair in ctx["pairs"]:
                        for d in pair["policy"]["directions"]:
                            if arm in ("C","D"):
                                self.assertEqual(d["aid_offer"]+d["aid_request"]+d["aid_quantity"],0)
                            if arm in ("B","D"):
                                self.assertEqual(d["trade_limit_permille"],1000)
                            if arm in ("B","C"):
                                self.assertEqual((d["migration_limit_permille"],d["migration_accept_permille"]),(1000,1000))
                    previous=row
                tampered = deepcopy(row)
                tampered["diplomacy"]["phase61"]["export"] = not ctx["phase61"]["export"]
                with self.assertRaises(ValueError):
                    audit_rules61(tampered)

    def test_identical_opening_without_eligible_instruments_keeps_real_economy_equal(self):
        control = step61(start61(make()),1,"E")
        original = {k:v for k,v in control.items() if k!="diplomacy"}
        for arm in ("B","C","D","F"):
            with self.subTest(arm=arm):
                row = step61(start61(make()),1,arm)
                self.assertEqual({k:v for k,v in row.items() if k!="diplomacy"},original)
                self.assertEqual(row["diplomacy"]["events"],control["diplomacy"]["events"])
                self.assertEqual(row["diplomacy"]["pairs"],control["diplomacy"]["pairs"])

    def test_failed_audit_and_unsupported_forks_leave_state_unchanged(self):
        sim = start61(make())
        first = step61(sim,1,"B")
        before = canonical_line(snapshot61(sim))
        with patch("civsim.diplomacy61.audit_fiscal61",side_effect=ValueError("injected failure")):
            with self.assertRaisesRegex(ValueError,"injected failure"):
                step61(sim,2,"B")
        with self.assertRaises(ValueError):
            step61(sim,2,"C")
        with self.assertRaises(ValueError):
            fork61(sim,2,"B",suppress_aid=(0,0))
        self.assertEqual(before,canonical_line(snapshot61(sim)))
        row = step61(sim,2,"B")
        forged = deepcopy(first)
        forged["diplomacy"]["pairs"][0]["closing"]["trust"]+=1
        with self.assertRaises(ValueError):
            audit_rules61(row,forged)

    def test_suppressed_authorized_aid_and_binding_cap_on_development_opening(self):
        sim = start61(regionalize(generate_world(0)))
        for year in (1,2,3):
            step61(sim,year,"E")
        opening = canonical_line(snapshot61(sim))
        actual,blocked = fork61(sim,4,"E",suppress_aid=(2,3))
        p,q = actual["diplomacy"],blocked["diplomacy"]
        self.assertEqual([r["policy"] for r in p["pairs"]],[r["policy"] for r in q["pairs"]])
        shipments = lambda ctx: [s for s in ctx["physical"]["aid"]["shipments"] if (s["donor"],s["recipient"])==(2,3)]
        self.assertTrue(shipments(p))
        self.assertFalse(shipments(q))
        _,capped = fork61(sim,4,"E",capped=True)
        limited = capped["diplomacy"]
        self.assertEqual([r["policy"] for r in p["pairs"]],[r["policy"] for r in limited["pairs"]])
        expected = next(d["aid_budget"] for r in p["pairs"] for d in r["policy"]["directions"]
                        if (d["source"],d["target"])==(2,3))
        paid = lambda ctx: sum(s["quantity"]+s["cost_food"] for s in shipments(ctx))
        self.assertGreater(paid(p),expected)
        self.assertLessEqual(paid(limited),expected)
        self.assertEqual(opening,canonical_line(snapshot61(sim)))
        self.assertEqual(canonical_line(step61(sim,4,"E")),canonical_line(actual))
