import unittest
from copy import deepcopy

from civsim.model import generate_world
from civsim.peace62 import start62, step62
from civsim.regions import regionalize
from experiments.civic_baseline63 import civic_year


class CivicLedgerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        engine = start62(regionalize(generate_world(0)))
        cls.record = step62(engine, 1, "D")

    def test_population_meals_and_government_food_have_distinct_ledgers(self):
        regions, countries = civic_year(self.record)
        self.assertEqual(len(countries), 8)
        self.assertEqual(len(regions), 32)
        self.assertEqual(sum(r["food_need"] for r in regions), sum(r["population_open"] for r in regions))
        self.assertEqual(sum(r["turnovers"] for r in countries), 0)
        self.assertEqual(sum(r["food_unmet"]+r["food_eaten"] for r in regions),
                         sum(r["food_need"] for r in regions))
        self.assertTrue(all(r["food_need"]==r["population_open"] for r in regions))

    def test_rejects_invented_cash_meals_or_public_stocks(self):
        for change in ("cash", "meal", "warehouse"):
            with self.subTest(change=change):
                row = deepcopy(self.record)
                if change=="cash":
                    row["regions"][0]["closing"]["cash"] += 1
                elif change=="meal":
                    row["regions"][0]["consumption"]["food_eaten"] += 1
                else:
                    row["government"]["depots"][0]["closing"]["ore"] += 1
                with self.assertRaises(ValueError):
                    civic_year(row)
