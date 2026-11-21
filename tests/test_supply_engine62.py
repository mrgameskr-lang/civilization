import unittest
from copy import deepcopy

from civsim.supply_border62 import charge_border, audit_envelope
from civsim.diplomacy61 import start61, step61
from civsim.model import generate_world
from civsim.regions import regionalize
from civsim.storage import canonical_line
from civsim.supply62 import start62, snapshot62, step62, fork_supply62, audit62


def fresh():
    return regionalize(generate_world(0))


class DepotEngineTests(unittest.TestCase):
    def test_domestic_reserve_stays_in_custody_and_prepaid_freight_consumes_one_budget(self):
        from tests.test_aid_budget61 import context, setup_case
        ctx = context({(0,1):20}, {0:12})
        template, _ = setup_case(ctx)
        vault = {i:dict(food=(30 if i==0 else 0),ore=0,tools=0) for i in range(3)}
        supply = {"countries":[{"owner":i,"aid_freight_food":3 if i==0 else 0} for i in range(3)],
                  "shipments":[{"good":"food","purpose":"domestic_reserve","target":0,"quantity":24}]}
        flow = charge_border(ctx,list(template.nodes.values()),list(template.borders.values()),64,vault,supply)
        self.assertEqual((flow.aid["shipments"][0]["quantity"],vault[0]["food"]), (5,24))
        d = flow.aid["donors"][0]
        self.assertEqual((d["border_debit"],d["actual_debit"],d["remaining_budget"]), (6,9,3))
        audit_envelope({**ctx,"physical":flow.trace()}, supply)

    def test_control_is_original_capped_path(self):
        base, control = start61(fresh()), start62(fresh())
        for year in range(1, 5):
            self.assertEqual(canonical_line(step61(base, year, "F")), canonical_line(step62(control, year, "A")))
        with self.assertRaises(ValueError):
            step62(control, 5, "B")

    def test_fork_is_single_year_and_fiscal_audit_identifies_forged_cost(self):
        sim = start62(fresh())
        for year in range(1, 4):
            step62(sim, year, "B")
        before = canonical_line(snapshot62(sim))
        actual, suppressed = fork_supply62(sim, 4)
        self.assertEqual(before, canonical_line(snapshot62(sim)))
        self.assertEqual(actual, step62(sim, 4, "B"))
        self.assertFalse(suppressed["supply"]["shipments"])
        self.assertEqual([p["policy"] for p in actual["diplomacy"]["pairs"]],
                         [p["policy"] for p in suppressed["diplomacy"]["pairs"]])
        for donor in actual["diplomacy"]["physical"]["aid"]["donors"]:
            self.assertEqual(donor["actual_debit"], donor["internal_freight"] + donor["border_debit"])
            self.assertLessEqual(donor["actual_debit"], donor["planned_budget"])
        damaged = deepcopy(actual)
        damaged["government"]["roads"][0]["supply_use"] += 1
        with self.assertRaises(ValueError):
            audit62(damaged, geography=fresh())
