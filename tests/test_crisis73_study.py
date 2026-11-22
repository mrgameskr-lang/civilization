import unittest

from experiments.crisis73 import command_for, paired_worlds


class CrisisStudyTests(unittest.TestCase):
    def test_actual_same_opening_costs_and_migrants_are_counted_separately(self):
        from experiments.crisis73_fork import smoke
        result = smoke()
        self.assertEqual((result["seed"], result["year"], result["pair"]), (0, 6, [2, 3]))
        self.assertEqual(result["normal"]["pair"]["people_released"], 3)
        self.assertEqual(result["world_difference"]["workers"], 2)
        self.assertEqual(result["world_difference"]["quantity"], 0)
        for paid, held in zip(result["normal"]["local_production"], result["held"]["local_production"], strict=True):
            self.assertEqual(paid["private_workers"] + 1, held["private_workers"])
        self.assertEqual(result["no_history_case"]["active_pairs"], 0)

    def test_pair_only_switches_crisis_at_opening(self):
        from experiments.diffusion72 import command_for as legacy
        for year in (1, 2, 3, 50, 100, 200):
            expected = legacy("diffusion", year)
            self.assertEqual(command_for("diffusion", year), expected)
            treatment = command_for("crisis", year)
            if year == 1:
                self.assertIs(treatment.pop("crisis"), True)
            self.assertEqual(treatment, expected)

    def test_pair_uses_difference_of_world_ratios(self):
        first = dict(seed=27, year=200, arm="diffusion", food=100, unmet=1, need=100,
                     support_points=100, members=2)
        second = dict(first, arm="crisis", food=98, unmet=3, need=50, support_points=180, members=3)
        paired, = paired_worlds([first, second], metrics=["food"])
        self.assertAlmostEqual(paired["shortage_rate_delta"], .05)
        self.assertEqual((paired["support_delta"], paired["food"], paired["cohort"]), (10, -2, "validation"))
        with self.assertRaises(ValueError):
            paired_worlds([first, first], metrics=["food"])
