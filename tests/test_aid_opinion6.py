import unittest

from civsim.aid_opinion import observe_aid


def region(population=100):
    group = {"members": population//3, "signals": {"relief": 400, "reserve": 200, "defer": 50},
             "support": 450, "discontent": 100, "demand": "reserve", "age": 2}
    return {"population": population, "groups": {k: dict(group) for k in ("farm", "industry", "consumer")},
            "evidence": {}}


class AidOpinionTests(unittest.TestCase):
    def test_political_incidence_uses_actual_receipts_and_preexisting_preferences(self):
        before = {0: region(), 1: region(), 2: region()}
        after = {i: region() for i in before}
        before[1]["groups"]["farm"]["signals"] = {"relief": 1000, "reserve": 0, "defer": 0}
        loads = [{"source": 0, "target": 1, "quantity": 16, "cost_food": 1, "received": 15}]
        observe_aid(after, before, loads)
        self.assertEqual(after[0]["groups"]["industry"]["support"], 438)
        self.assertEqual(after[1]["groups"]["farm"]["support"], 450)
        self.assertEqual(after[1]["groups"]["consumer"]["support"], 457)
        self.assertEqual(after[0]["evidence"]["foreign_aid"]["released_food"], 17)
        self.assertEqual(after[1]["evidence"]["foreign_aid"]["received_food"], 15)
        self.assertEqual(after[2], before[2])
        self.assertEqual(before[0]["groups"]["industry"]["support"], 450)

    def test_a_promise_with_no_settled_cargo_has_no_effect(self):
        old, new = {0: region()}, {0: region()}
        observe_aid(new, old, [])
        self.assertEqual(new, old)
