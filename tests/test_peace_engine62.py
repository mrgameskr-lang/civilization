from copy import deepcopy
import unittest

from civsim.model import generate_world
from civsim.peace62 import start62, step62, audit62, fork_recruit62, snapshot62
from civsim.regions import regionalize
from civsim.storage import canonical_line


class PeacetimeTests(unittest.TestCase):
    def test_roster_uses_existing_population_and_single_year_fork_preserves_all_approvals(self):
        world = regionalize(generate_world(0))
        sim = start62(world)
        first = step62(sim, 1, "D")
        original = canonical_line(snapshot62(sim))
        actual, hold = fork_recruit62(sim, 2)
        self.assertEqual(canonical_line(snapshot62(sim)), original)
        self.assertEqual(actual, step62(sim, 2, "D"))
        self.assertEqual(hold["diplomacy"]["countries"], actual["diplomacy"]["countries"])
        self.assertEqual(sum(r["enrolled"] for r in hold["service"]["regions"]), 0)
        audit62(actual, geography=world, previous_record=first)
        damaged = deepcopy(actual)
        damaged["service"]["regions"][0]["ration_food"] += 1
        with self.assertRaises(ValueError):
            audit62(damaged, geography=world, previous_record=first)
        for r, service in zip(actual["regions"], actual["service"]["regions"], strict=True):
            self.assertLessEqual(service["closing_roster"], r["closing"]["population"])
