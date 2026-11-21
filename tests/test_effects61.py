import unittest
from fractions import Fraction

from experiments.effects61 import compare, direction_year, fraction, signs


def observation(a,b,food=0,started=0,terminated=0,active=0):
    return {"source":a,"target":b,"trade_food":food,"trade_ore":0,"trade_tools":0,"trade_value":3*food,
            "agreement_active":active,"agreement_started":started,"agreement_terminated":terminated,"migrants":0,
            "trade_denied":0,"exit_denied":0,"entry_denied":0}


class EffectsTests(unittest.TestCase):
    def test_reciprocal_trade_counts_one_partner_and_bilateral_events_once(self):
        totals,partners = direction_year([observation(0,1,5,1,0,1),observation(1,0,9,1,0,1),
                                         observation(1,2,0,0,1,1),observation(2,1,0,0,1,1)])
        self.assertEqual(totals["export_food"],14)
        self.assertEqual((totals["agreement_years"],totals["agreements_started"],totals["agreements_terminated"]),(2,1,1))
        self.assertEqual(totals["trade_partner_years"],2)
        self.assertEqual(partners,{(0,1)})
        with self.assertRaisesRegex(ValueError,"bilateral"):
            direction_year([observation(0,1,5,1,0,1)])

    def test_paired_residual_and_zero_rate_are_exact(self):
        levels=dict(zip("ABCDEF",(2,4,5,1,11,10),strict=True))
        self.assertEqual(compare(levels,"I"),5)
        self.assertEqual(compare(levels,"F-E"),-1)
        self.assertEqual(signs([Fraction(1,10**18),0,-1]),(1,1,1))
        self.assertEqual(fraction(0,0),0)
        with self.assertRaises(ValueError):
            fraction(2,0)
