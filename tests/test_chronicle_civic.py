from copy import deepcopy
import unittest

from civsim.annual_game import create, play
from civsim.chronicle_civic import candidates


def cabinet():
    return {
        "id": 4, "governing_faction": "mutualists",
        "election": {"election": True, "installation": False, "turnover": True,
                     "previous_incumbent": "builders", "incumbent": "mutualists",
                     "participation_points": 1234, "seats": {"mutualists": 12}},
    }


def disputed_trade(kind):
    return {"kind": kind, "a": 1, "b": 6, "source": 1, "target": 6, "quantity": 1}


class CivicChronicleTests(unittest.TestCase):
    def test_actual_turnover_records_the_winner_seats_and_the_acting_government(self):
        country = cabinet()
        event, = candidates({"competition": {"countries": [country]}})
        self.assertEqual((event.country, event.region, event.kind), (4, None, "government_turnover"))
        self.assertEqual(event.evidence["seats"], "/competition/countries/0/election/seats/mutualists")
        self.assertIn("12석", event.description)
        self.assertIn("건설", event.description)
        self.assertIn("상호부조", event.description)

    def test_initial_installation_retention_and_intervention_are_not_turnovers(self):
        installation, retained, override = (deepcopy(cabinet()) for _ in range(3))
        installation["election"].update(previous_incumbent="caretaker", installation=True, turnover=False)
        retained["election"].update(previous_incumbent="mutualists", turnover=False)
        override["governing_faction"] = "builders"
        disabled = {"id": 3, "election": None}
        self.assertEqual(list(candidates({"competition": {"countries": [installation, retained, override, disabled]}})), [])

    def test_collective_action_uses_a_real_onset_and_both_size_thresholds(self):
        def actions(q, members, duration=1, action="protest"):
            record = {"collective": {"regions": [
                {"id": 10, "owner": 3, "groups": {"industry": {
                    "action": action, "participants": q, "members": members, "duration": duration,
                }}}
            ]}}
            return list(candidates(record))

        event, = actions(16, 200)
        self.assertEqual((event.kind, event.country, event.region), ("collective_action", 3, 10))
        self.assertIn("16명", event.description)
        self.assertEqual(event.evidence["participants"], "/collective/regions/0/groups/industry/participants")
        for args in [(14, 100), (15, 200), (16, 200, 2), (0, 200), (16, 200, 1, "accept")]:
            with self.subTest(args=args):
                self.assertEqual(actions(*args), [])

    def test_bilateral_receipts_skip_proposals_rejections_and_expiries(self):
        kinds = ("pact_proposed", "pact_rejected", "pact_started", "pact_expired", "pact_terminated")
        record = {"diplomacy": {"events": [disputed_trade(kind) for kind in kinds]}}
        started, terminated = candidates(record)
        self.assertEqual((started.country, started.counterparty, started.region), (1, 6, None))
        self.assertEqual([started.kind, terminated.kind], ["trade_pact_started", "trade_pact_terminated"])
        self.assertEqual(started.evidence["quantity"], "/diplomacy/events/2/quantity")
        self.assertEqual(terminated.evidence["event"], "/diplomacy/events/4/kind")

    def test_absent_optional_subledgers_have_no_events(self):
        self.assertEqual(list(candidates({"year": 1})), [])

    def test_generated_seed_zero_receipts_resolve_across_nine_years(self):
        world = create(0)
        observations = {}
        for year in range(1, 10):
            record = play(world, None)
            for event in candidates(record):
                values = {}
                for key, pointer in event.evidence.items():
                    source = record
                    for part in pointer[1:].split("/"):
                        source = source[int(part)] if isinstance(source, list) else source[part]
                    values[key] = source
                self.assertEqual(values["country"], event.country)
                if event.region is not None:
                    self.assertEqual(values["region"], event.region)
                if event.counterparty is not None:
                    self.assertEqual(values["counterparty"], event.counterparty)
                observations.setdefault(event.kind, (year, values))

        year, pact = observations["trade_pact_started"]
        self.assertEqual((year, pact["country"], pact["counterparty"], pact["quantity"]), (2, 0, 2, 1))
        year, action = observations["collective_action"]
        self.assertEqual((year, action["action"], action["members"], action["participants"]),
                         (3, "petition", 4098, 655))
        year, cabinet = observations["government_turnover"]
        self.assertEqual((year, cabinet["country"], cabinet["former"], cabinet["winner"], cabinet["seats"]),
                         (9, 0, "mutualists", "stewards", 14))
        self.assertEqual(observations["trade_pact_terminated"][0], 5)
