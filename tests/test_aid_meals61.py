import hashlib
import json
from pathlib import Path
import unittest

from civsim.model import generate_world
from civsim.regions import regionalize
from civsim.storage import canonical_line
from experiments.aid_incidence61 import meal_incidence, replay_meals

ARCHIVE = Path(__file__).resolve().parents[1]/"examples"/"phase6a"/"seed0-diplomacy"


class AidMealTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = regionalize(generate_world(0))
        cls.years = [json.loads(line) for line in (ARCHIVE/"years.jsonl").read_bytes().splitlines()]

    def test_post_production_replay_reconstructs_actual_meals(self):
        for row in self.years:
            self.assertEqual(replay_meals(row, self.world, row["diplomacy"]["physical"]["aid"]["shipments"]),
                             {r["id"]:r["consumption"] for r in row["regions"]})

    def test_a_receipt_and_extra_food_eaten_are_separate_observations(self):
        row = self.years[3]
        before = hashlib.sha256(canonical_line(row)).digest()
        delivered = sum(s["received"] for s in row["diplomacy"]["physical"]["aid"]["shipments"])
        delta = meal_incidence(row, self.world)
        self.assertEqual(delivered, 228)
        self.assertNotEqual(sum(delta.values()), delivered)
        self.assertEqual(before, hashlib.sha256(canonical_line(row)).digest())
        self.assertEqual(meal_incidence(self.years[0], self.world), dict.fromkeys(delta,0))
