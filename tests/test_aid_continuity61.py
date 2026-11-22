import unittest

from civsim.aid_budget61 import audit_fiscal61
from civsim.audit import BalanceError
from civsim.diplomacy61 import fork61, start61, step61
from civsim.model import generate_world
from civsim.regions import regionalize


def initial():
    return start61(regionalize(generate_world(0,18,12,3),3))


class FiscalContinuity61Tests(unittest.TestCase):
    def test_standard_trajectory_rejects_switch_in_either_direction(self):
        e,f = initial(),initial()
        e1,f1 = step61(e,1,"E"),step61(f,1,"F")
        e2,f2 = step61(e,2,"E"),step61(f,2,"F")
        # Year one has exactly the same physical accounts and pair memory under E and F.
        self.assertEqual(e1["countries"],f1["countries"])
        self.assertEqual(e1["diplomacy"]["pairs"],f1["diplomacy"]["pairs"])
        for current,own,other in ((e2,e1,f1),(f2,f1,e1)):
            with self.subTest(current_format=current["diplomacy"].get("phase61")):
                audit_fiscal61(current,previous_record=own)
                with self.assertRaises(BalanceError):
                    audit_fiscal61(current,previous_record=other)

    def test_single_year_diagnostic_is_an_endpoint(self):
        sim = initial()
        first = step61(sim,1,"E")
        _,diagnostic = fork61(sim,2,"E",capped=True)
        audit_fiscal61(diagnostic,previous_record=first)
        step61(sim,2,"E")
        third = step61(sim,3,"E")
        with self.assertRaises(BalanceError):
            audit_fiscal61(third,previous_record=diagnostic)
