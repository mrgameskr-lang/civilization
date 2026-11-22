from unittest import TestCase

from experiments.diffusion72 import command_for, worlds_paired
from experiments.diffusion72_fork import smoke
from experiments.diffusion72_results import contact_stats


class DiffusionStudyTests(TestCase):
    def test_high_traffic_and_observed_contact_do_not_count_as_mastery(self):
        sites = [{"domestic_arrivals": "0", "first_contact": "0", "method": "independent"},
                 {"domestic_arrivals": "1030", "first_contact": "9", "method": ""},
                 {"domestic_arrivals": "1000", "first_contact": "3", "method": "transfer"}]
        quiet, _, _, busy = contact_stats(sites)
        self.assertEqual((quiet["contact"], quiet["independent"]), (0, 1))
        self.assertEqual((busy["regions"], busy["contact"], busy["transfer"], busy["pending"]), (2, 2, 1, 1))
        self.assertEqual(busy["median_first_contact"], 6)

    def test_same_opening_road_closure_delays_contact_and_separates_adoption_from_costs(self):
        paths = smoke()["paths"]
        migration = paths["open"][0]
        closed = paths["until_trial"][0]
        self.assertEqual(migration["receipt"], dict(source=16, target=19, distance=10, people=23))
        self.assertIsNone(closed["receipt"])
        self.assertEqual((closed["domestic_quantity"], closed["border_quantity"]),
                         (migration["domestic_quantity"], migration["border_quantity"]))
        before, reopened, blocked = (paths[k][-1] for k in ("open", "one_year", "until_trial"))
        self.assertEqual((before["applied_level"], reopened["applied_level"], blocked["applied_level"]), (1, 1, 0))
        self.assertEqual(before["food"] - before["food_without_tech"], 46)
        self.assertEqual(before["food"] - blocked["food"], 45)

    def test_pair_has_same_policies_except_diffusion(self):
        for year in (1, 2, 3, 50, 200):
            baseline = command_for("research", year)
            enabled = command_for("diffusion", year)
            if year == 1:
                self.assertIs(enabled.pop("diffusion"), True)
            self.assertEqual(baseline, enabled)

    def test_between_arm_aggregates_use_common_seed_and_weighted_rates(self):
        rows = []
        for arm, unmet, support in (("diffusion", 2, 90), ("research", 1, 60)):
            for owner, need in ((0, 10), (1, 90)):
                rows.append(dict(seed=20, year=50, arm=arm, owner=owner, unmet=unmet,
                                 need=need, represented_members=need, support_points=support,
                                 population=100))
        paired = worlds_paired(rows, ("population", "unmet", "need"))
        self.assertEqual(len(paired), 1)
        self.assertAlmostEqual(paired[0]["shortage_rate_delta"], .02)
        self.assertAlmostEqual(paired[0]["support_delta"], .6)
        self.assertEqual(paired[0]["population"], 0)
