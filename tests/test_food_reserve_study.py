import json
from pathlib import Path
import unittest

from experiments.food_reserve_study import small_case


class PairedStudyTests(unittest.TestCase):
    def test_same_opening_replays_published_farm_and_household_receipts(self):
        published = Path(__file__).resolve().parents[1] / "examples/food-reserve-v1/same-opening.json"
        actual = small_case(0)
        self.assertEqual(actual, json.loads(published.read_bytes()))
        difference = actual["year_two_C_minus_A"]
        self.assertEqual(difference["food_need"], 0)
        self.assertEqual(difference["harvest_total"], 0)
        self.assertEqual(difference["harvest_public"], -difference["harvest_private"])
        self.assertEqual(difference["public_farm_workers"], -difference["private_farm_workers"])
        self.assertGreater(difference["public_close"], 0)
        self.assertLess(difference["food_eaten"], 0)
