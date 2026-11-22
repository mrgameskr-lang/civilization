import unittest

from civsim.collective_rules import empty_memory, mobilize_region


def observations(demand="soil", discontent=280, fiscal=0):
    return {"id": 0, "population": 600, "owner": 0, "evidence": {"shortage_permille": 120},
            "groups": {name: {"members": size, "support": 405, "discontent": discontent, "demand": demand,
                              "age": 8, "pressure": 350, "fiscal_burden": fiscal, "levy_value": fiscal}
                       for name, size in (("farm", 130), ("industry", 100), ("consumer", 370))}}


class CollectiveRuleTests(unittest.TestCase):
    def test_high_discontent_without_a_persistent_demand_is_insufficient(self):
        obs = observations("none", discontent=980)
        region = mobilize_region(0, 600, obs, empty_memory())
        self.assertTrue(all(g["action"] == "none" for g in region["groups"].values()))

    def test_escalation_requires_history_and_feasible_work_or_tax(self):
        obs = observations()
        prior = empty_memory()
        first = mobilize_region(0, 600, obs, prior)["groups"]
        self.assertEqual(first["farm"]["action"], "petition")
        prior["farm"].update(action="petition", demand="soil", duration=1, campaign=1)
        self.assertEqual(mobilize_region(0, 600, obs, prior)["groups"]["farm"]["action"], "protest")
        for m in prior.values():
            m.update(action="protest", demand="soil", duration=1, campaign=2)
        groups = mobilize_region(0, 110, obs, prior)["groups"]
        self.assertEqual(groups["farm"]["action"], "strike")
        self.assertGreater(groups["farm"]["withheld_workers"], 0)
        self.assertEqual(groups["consumer"]["withheld_workers"], 0)
        self.assertLessEqual(sum(g["members"] for g in groups.values()), 110)
        self.assertLessEqual(sum(g["withheld_workers"] for g in groups.values()), 55)
        self.assertEqual(mobilize_region(0, 600, observations(fiscal=80), prior)["groups"]["industry"]["action"], "refusal")

    def test_delivered_answer_and_recovery_allow_acceptance_and_campaign_exhausts(self):
        obs = observations()
        prior = empty_memory()
        prior["industry"].update(action="petition", demand="soil", duration=1, campaign=1, answered=True,
                                 opening_discontent=300)
        self.assertEqual(mobilize_region(0, 600, obs, prior)["groups"]["industry"]["action"], "accept")
        prior["industry"].update(answered=False, campaign=6)
        g = mobilize_region(0, 600, obs, prior)["groups"]["industry"]
        self.assertEqual((g["action"], g["participants"]), ("none", 0))

    def test_suppression_changes_only_the_selected_group_at_opening(self):
        obs = observations()
        normal = mobilize_region(0, 600, obs, empty_memory())["groups"]
        trial = mobilize_region(0, 600, obs, empty_memory(), suppress="industry")["groups"]
        self.assertEqual(trial["farm"], normal["farm"])
        self.assertEqual(trial["industry"]["action"], "none")
        self.assertEqual(trial["consumer"], normal["consumer"])
