from unittest import TestCase

from experiments.research71 import command_for, choose_cases, support_counts
from experiments.research71_fork import smoke


class ResearchStudyTests(TestCase):
    def test_actual_seed_zero_fork_distinguishes_realized_and_fixed_input_food(self):
        result = smoke()
        self.assertEqual((result["year"], result["region"]), (5,28))
        now, held, after, held_after = (result[k] for k in ("invest","hold","invest_next","hold_next"))
        self.assertEqual(now["food"] - held["food"], -15)
        self.assertEqual(after["food"] - held_after["food"], 196)
        self.assertEqual(after["food"] - after["food_without_tech"], 211)
        self.assertEqual(now["works_node"]["depot_close"], held["works_node"]["depot_close"])

    def test_only_difference_in_commands_is_research_activation(self):
        for year in (1, 2, 3, 200):
            off, on = (command_for(mode, year) for mode in ("off", "research"))
            changed = dict(on or {})
            if year == 1:
                self.assertIs(changed.pop("research"), True)
                self.assertIsNone(changed.pop("move"))
            self.assertEqual(changed, dict(off or {}))

    def test_case_selection_uses_validation_countries_even_when_all_have_progress(self):
        def country(seed, owner, first, trials):
            return {"seed":seed, "owner":owner, "arm":"research", "year":200,
                    "first_adoption":first, "trials":trials}
        rows = [country(0, 3, 1, 8), country(20, 1, 8, 8), country(20, 0, 8, 8),
                country(21, 4, 15, 2), country(22, 2, 0, 1), country(22, 5, 0, 0)]
        fast, stalled = choose_cases(rows)
        self.assertEqual((fast["seed"], fast["owner"]), (20, 0))
        self.assertEqual((stalled["seed"], stalled["owner"]), (22, 2))
        _, slow = choose_cases(rows[:4])
        self.assertEqual((slow["seed"], slow["owner"]), (21, 4))

    def test_support_uses_members_as_weights_and_keeps_empty_denominator(self):
        groups = {"a":{"members":10,"support":200}, "b":{"members":2,"support":800}}
        self.assertEqual(support_counts(groups), (3600,12))
        self.assertEqual(support_counts({}), (0,0))
