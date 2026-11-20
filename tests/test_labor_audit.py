import unittest
from copy import deepcopy
from unittest.mock import patch

from civsim.audit import BalanceError, audit
from civsim.economy import produce
from civsim.engine import step
from civsim.model import generate_world
from civsim.rules import Rules


def crowded_world():
    world = generate_world(42, width=5, height=1, nations=1)
    world.nations[0].population = 1005
    world.nations[0].stock["food"] = 0
    return world


class LaborAuditTests(unittest.TestCase):
    def test_worker_totals_farm_capacity_and_negative_idle_are_audited(self):
        original = step(crowded_world(), 1, Rules(labor="reallocate"))
        for field, key, value in [
            ("workers", None, 501), ("labor_before", "farm", 382), ("labor", "factory", 203),
            ("active_labor", "mine", 201), ("land_capacity", None, 101),
            ("active_farmers", None, 101), ("active_labor", "farm", 101),
            ("idle_before", None, -1), ("idle_after", None, -1), ("reassigned", "mine", -1),
            ("idle_after", None, False),
        ]:
            with self.subTest(field=field, key=key):
                record = deepcopy(original)
                labor = record["countries"][0]["production"]
                if key is None:
                    labor[field] = value
                else:
                    labor[field][key] = value
                with self.assertRaises(BalanceError):
                    audit(record)

    def test_moving_odd_worker_to_wrong_sector_fails_even_with_balanced_totals(self):
        record = step(crowded_world(), 1, Rules(labor="reallocate"))
        p = record["countries"][0]["production"]
        # All national labor totals and transfers still add up.
        for field in ("reassigned", "active_labor", "labor"):
            p[field]["mine"] += 1
            p[field]["factory"] -= 1
        self.assertEqual(sum(p["active_labor"].values()), p["workers"])
        with self.assertRaises(BalanceError):
            audit(record)

    def test_changed_order_idle_policy_keeps_surplus_assigned_to_farms(self):
        record = step(crowded_world(), 1, Rules(order=("tools", "food", "ore")))
        p = record["countries"][0]["production"]
        self.assertEqual((p["idle_before"], p["idle_after"]), (281, 281))
        audit(record)
        # The transfer is internally balanced but the idle policy forbids it.
        p["reassigned"]["factory"] += 1
        p["labor"]["farm"] -= 1
        p["labor"]["factory"] += 1
        p["active_labor"]["factory"] += 1
        p["idle_after"] -= 1
        with self.assertRaises(BalanceError):
            audit(record)

    def test_v2_step_preserves_year_and_nations_when_labor_audit_fails(self):
        def corrupt_production(*args):
            trace = produce(*args)
            trace["workers"] += 1
            return trace

        world = crowded_world()
        before = deepcopy(world)
        with patch("civsim.engine.economy.produce", side_effect=corrupt_production):
            with self.assertRaises(BalanceError):
                step(world, 1, Rules(labor="reallocate"))
        self.assertEqual(world, before)
