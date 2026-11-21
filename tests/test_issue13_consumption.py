"""Document the sign of actual meal incidence at the archived overspend."""
import unittest

from civsim.diplomacy61 import fork61, start61, step61
from civsim.model import generate_world
from civsim.regions import regionalize


def recipient(row):
    regions = {r["id"]:r for r in row["regions"] if r["owner"]==3}
    national = next(r for r in row["government"]["accounts"] if r["id"]==3)
    imports = sum(t["quantity"] for t in row["border_market"]["trades"] if t["buyer"] in regions and t["good"]=="food")
    food = sum(r["consumption"]["food_eaten"] for r in regions.values())
    return imports, food, national["totals"]["relief_food"], national["public_close"]["food"]


class Issue13MealTests(unittest.TestCase):
    def test_warehouse_food_and_private_imports_compete_for_the_road(self):
        sim = start61(regionalize(generate_world(0)))
        for y in range(1,4):
            step61(sim,y,"E")
        original, capped = fork61(sim,4,"E",capped=True)
        _, withheld = fork61(sim,4,"E",suppress_aid=(2,3))
        self.assertEqual(recipient(original), (513,6893,0,165))
        self.assertEqual(recipient(capped), (526,6906,0,154))
        self.assertEqual(recipient(withheld), (650,7030,0,0))
