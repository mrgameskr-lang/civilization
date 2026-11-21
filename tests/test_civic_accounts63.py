import unittest
from collections import Counter
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from experiments.civic_accounts63 import archived_examples, build, check_road, regional_account, summarize_rates, year_end


class CivicAccountsTests(unittest.TestCase):
    def posting(self):
        return Counter(food_need=20, food_eaten=17, food_deficit=3, working_age=10,
                       production_workers=4, service_eligible_workers=10,
                       service_roster_open_years=4, service_enrolled=2, service_serving=6,
                       service_stationed=6, service_ration_food=4, service_rationed_at_station=4,
                       service_available=4, service_unavailable=2, service_tools_used=1,
                       closing_service_roster=6, closing_population=20,
                       opening_public_food=5, works_used_food=1, opening_public_tools=1)

    def test_public_meal_is_part_of_resident_meals_and_household_bounds_are_sharp(self):
        x=regional_account(self.posting())
        self.assertEqual((x['unprovided_food'],x['unprovided_tools']),(2,0))
        self.assertEqual((x['nonparticipant_eaten_min'],x['nonparticipant_eaten_max']),(11,13))
        self.assertEqual(x['resident_meals_without_public_ration'],13)
        self.assertEqual(x['roster_gap_with_resident_shortfall'],2)

    def test_movement_only_changes_workplace_and_real_tool_charge(self):
        r=self.posting()
        r.update(service_reassignment_in=2,service_stationed=2,service_rationed_at_station=2,
                 service_available=2)
        x=regional_account(r)
        self.assertEqual((x['unprovided_food'],x['unprovided_tools']),(2,0))
        r['service_reassignment_in']=1
        with self.assertRaises(ValueError):
            regional_account(r)

    def test_damage_to_pre_meal_stock_or_person_years_fails_before_aggregation(self):
        for col in ('opening_public_food','opening_public_tools','production_workers','closing_service_roster','food_eaten'):
            r=self.posting()
            r[col]-=1
            with self.subTest(col=col), self.assertRaises(ValueError):
                regional_account(r)

    def test_upstream_transport_is_counted_once(self):
        r=self.posting()
        r.update(public_transfer_in_food=3,depot_freight_food=2,public_works_freight_food=1)
        self.assertEqual(regional_account(r)['unprovided_food'],2)
        r['service_tools_used']=0
        with self.assertRaises(ValueError):
            regional_account(r)

    def test_pooled_and_seed_mean_use_their_own_denominators_and_skip_empty_seeds(self):
        rows=[{'x':1,'y':1},{'x':1,'y':3},{'x':0,'y':0}]
        self.assertEqual(summarize_rates(rows,'x','y'),(Fraction(2,3),Fraction(1,2),2))
        self.assertEqual(summarize_rates(rows[-1:],'x','y'),(None,None,0))

    def test_actual_shared_road_uses_close_including_unused(self):
        r=dict(works_use=1,supply_use=2,duty_use=4,relief_use=3,private_use=5,unused=5,capacity=20)
        check_road(r,4)
        for expected in (3,5):
            with self.subTest(expected=expected),self.assertRaises(ValueError):
                check_road(r,expected)
        r['unused']+=1
        with self.assertRaises(ValueError):
            check_road(r,4)
        r.update(unused=7,works_use=-1)
        with self.assertRaises(ValueError):
            check_road(r,4)

    def test_closing_food_rations_cancel_once_across_public_and_household_accounts(self):
        prior=Counter(year=1,closing_population=10,closing_public_food=3,closing_private_food=5)
        r=Counter(year=2,opening_public_food=3,food_need=10,food_eaten=10,meal_used_food=10,
                  produced_food=6,service_ration_food=2,relief_food=1,closing_private_food=4)
        self.assertEqual(year_end(r,prior),1)
        r["closing_private_food"]+=2
        with self.assertRaisesRegex(ValueError,"private stock"):
            year_end(r,prior)

    def test_published_examples_distinguish_receipts_from_actual_meals(self):
        repo=Path(__file__).resolve().parents[1]
        rows=archived_examples(repo/"examples"/"phase6b2"/"forks")
        r={(x["year"],x["branch"]):x for x in rows}
        self.assertEqual(r[1,"ordinary"]["actual_meals"]-r[1,"held"]["actual_meals"],-47)
        self.assertEqual(r[3,"ordinary"]["rations"]-r[3,"held"]["rations"],16)
        self.assertEqual(r[3,"ordinary"]["household_meals_by_region"],r[3,"held"]["household_meals_by_region"])

    def test_publication_refuses_existing_directory_and_preserves_contents(self):
        with TemporaryDirectory() as td:
            p=Path(td)
            marker=p/"keep"
            marker.write_bytes(b"original")
            with self.assertRaises(FileExistsError):
                build(p,p,p)
            self.assertEqual(marker.read_bytes(),b"original")
