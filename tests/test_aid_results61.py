from collections import Counter
import unittest

from experiments.aid_results61 import classify_world, count_attempt, sign


class AidResultTests(unittest.TestCase):
    def test_received_regions_include_two_way_warehouses_and_other_regions_once(self):
        rows=[dict(region=i,owner=i,food_need=100,food_eaten=65,direct_eaten_delta=d,aid_received=r,aid_sent=s)
              for i,d,r,s in ((0,5,7,1),(1,-3,0,5),(2,-2,0,0))]
        counts,exposures=classify_world(rows)
        self.assertEqual([counts[k]["net"] for k in ("receivers","donor_only","other","world")],[5,-3,-2,0])
        self.assertEqual(counts["world"]["zero"],1)
        self.assertEqual((exposures["received"],exposures["two_way"]),(7,1))
        rows[-1]["direct_eaten_delta"]=101
        with self.assertRaises(ValueError):
            classify_world(rows)

    def test_count_attempt_separates_ties_from_budget_displacing_a_delivery(self):
        counter=Counter()
        row=dict(quantity="3",uncapped_quantity="3",budget_displaced="0",binding="budget|road",
                 limit_authorized="6",limit_road="3",limit_stock="15",limit_storage="9",limit_budget="3")
        count_attempt(row,counter)
        self.assertEqual((counter["ties"],counter["budget_tied"],counter["budget_reducing"]), (1,1,0))
        self.assertEqual([k for k in counter if k.startswith("binding_")], ["binding_road","binding_budget"])
        row.update(quantity="0",uncapped_quantity="3",budget_displaced="3",binding="budget",limit_budget="1")
        count_attempt(row,counter)
        self.assertEqual((counter["minimum_lot"],counter["budget_reducing"],counter["displaced_attempt_qty"]),(1,1,3))
        row["quantity"]="2"
        with self.assertRaises(ValueError):
            count_attempt(row,counter)

    def test_sign_is_in_units_of_observations(self):
        counter=Counter()
        for val in (-3,-3,0,0,7):
            sign(counter,val)
        self.assertEqual(dict(counter),dict(negative=2,negative_units=-6,net=1,count=5,
                                           zero=2,positive=1,positive_units=7))

    def test_no_aid_year_cannot_hide_regional_changes_that_sum_to_zero(self):
        rows=[dict(region=i,owner=i,food_need=100,food_eaten=65,direct_eaten_delta=d,aid_received=0,aid_sent=0)
              for i,d in enumerate((3,-3))]
        with self.assertRaisesRegex(ValueError,"without aid"):
            classify_world(rows)
        for r in rows:
            r["direct_eaten_delta"]=0
        c,e=classify_world(rows)
        self.assertEqual((e["received"],c["world"]["zero"],c["other"]["count"]),(0,1,2))
