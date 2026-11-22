import unittest

from civsim.annual_game import create, play
from civsim.chronicle_material import candidates


def region(number=37, name="가람", opening=1000, closing=1000, unmet=0):
    return {
        "id": number, "owner": 3,
        "opening": {"population": opening, "name": name},
        "closing": {"population": closing},
        "consumption": {"food_need": opening, "food_eaten": opening - unmet, "food_unmet": unmet},
        "demography": {"births": max(0, closing-opening), "deaths": max(0, opening-closing),
                       "immigrants": 0, "emigrants": 0},
    }


def turn(*areas, ordinary=(), emergency=()):
    return {
        "regions": list(areas),
        "government": {"relief": {"shipments": list(ordinary)}},
        "emergency_relief": {"shipments": list(emergency), "applications": [{"approved": 5000}]},
    }


def trip(target, quantity, fee):
    return {"target": target, "quantity": quantity, "cost_food": fee}


def lookup(root, path):
    for part in path.split("/")[1:]:
        root = root[int(part)] if isinstance(root, list) else root[part]
    return root


class MaterialChronicleTests(unittest.TestCase):
    def test_food_crisis_requires_both_thresholds_and_reports_actual_meal(self):
        record = turn(region(11, unmet=199), region(42, unmet=200), region(64, opening=90, closing=90, unmet=90))
        events = list(candidates(record))
        self.assertEqual([(e.kind, e.region, e.country) for e in events], [("food_crisis", 42, 3)])
        event = events[0]
        self.assertEqual(event.importance, 65)
        self.assertEqual(lookup(record, event.evidence["food_unmet"]), 200)
        self.assertEqual(lookup(record, event.evidence["food_eaten"]), 800)
        self.assertEqual(lookup(record, event.evidence["food_need"]), 1000)
        self.assertIn("200", event.description)

    def test_population_thresholds_and_direction_include_both_balances(self):
        record = turn(region(38, closing=1050), region(58, closing=950),
                      region(17, closing=951), region(11, opening=0, closing=1),
                      region(21, opening=90, closing=115))
        events = list(candidates(record))
        self.assertEqual([(e.kind, e.region, e.importance) for e in events],
                         [("population_rise", 38, 72), ("population_fall", 58, 72)])
        for event, expected in zip(events, (1050, 950), strict=True):
            self.assertEqual(lookup(record, event.evidence["opening_population"]), 1000)
            self.assertEqual(lookup(record, event.evidence["closing_population"]), expected)

    def test_relief_uses_received_quantities_by_destination_across_both_stages(self):
        record = turn(region(9), region(19), ordinary=[trip(9, 40, 27), trip(19, 60, 99)],
                      emergency=[trip(19, 50, 1), trip(9, 50, 80)])
        events = list(candidates(record))
        self.assertEqual([(e.kind, e.region, e.importance) for e in events], [("large_relief", 19, 76)])
        event = events[0]
        self.assertIn("110", event.description)
        self.assertIn("60", event.description)
        self.assertIn("50", event.description)
        amounts = [lookup(record, p) for p in event.evidence.values() if p.endswith("/quantity")]
        self.assertEqual(sorted(amounts), [50, 60])
        self.assertFalse(any("approved" in p or "cost_food" in p for p in event.evidence.values()))

    def test_relief_absolute_and_relative_thresholds_and_optional_emergency(self):
        record = turn(region(9, opening=3000, closing=3000), ordinary=[trip(9, 149, 1000)])
        del record["emergency_relief"]
        self.assertEqual(list(candidates(record)), [])
        record["government"]["relief"]["shipments"][0]["quantity"] = 150
        self.assertEqual([e.kind for e in candidates(record)], ["large_relief"])

    def test_actual_world_evidence_resolves_and_source_rows_match_reported_location(self):
        row = play(create(0), None)
        events = list(candidates(row))
        crisis, = [event for event in events if event.kind == "food_crisis"]
        self.assertEqual((crisis.region, lookup(row, crisis.evidence["food_need"]),
                          lookup(row, crisis.evidence["food_unmet"])), (12, 7783, 1756))
        for event in events:
            self.assertEqual(lookup(row, event.evidence["region_id"]), event.region)
            self.assertEqual(lookup(row, event.evidence["owner"]), event.country)
            for path in event.evidence.values():
                self.assertIsInstance(lookup(row, path), (int, str))
