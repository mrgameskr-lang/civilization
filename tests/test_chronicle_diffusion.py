"""Evidence chains for first contact, paid acquisition and subsequent farm output."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import unittest
from unittest.mock import patch

from civsim.annual_game import load
from civsim.chronicle import Chronicle, render_markdown
from civsim.chronicle_event import resolve
from civsim.storage import canonical_line


def exchange_years():
    move = {"source": 9, "target": 4, "people": 3, "distance": 7}
    contact = {**move, "year": 1, "move_index": 1}
    years = []
    for year in (1, 2, 3):
        paid = int(year == 2)
        recipient = {
            "id": 4, "owner": 0, "level_before": int(year == 3), "level_after": int(year >= 2),
            "adoption_year": 2 if year >= 2 else None, "first_application": year == 3,
            "trial_workers": 2*paid, "trial_ore": paid, "trial_tools": paid,
            "cumulative_workers": 2*int(year >= 2), "cumulative_ore": int(year >= 2),
            "cumulative_tools": int(year >= 2), "project_id": 0 if paid else None,
        }
        source = {"id": 9, "owner": 0, "level_before": 1, "level_after": 1,
                  "first_application": False}
        exchange = {"id": 4, "owner": 0, "new_contact": year == 1,
                    "opening_contact": deepcopy(contact) if year > 1 else None,
                    "closing_contact": deepcopy(contact), "opening_method": "transfer" if year == 3 else None,
                    "closing_method": "transfer" if year >= 2 else None}
        years.append({"year": year, "diffusion": {"regions": [exchange]},
                      "research": {"regions": [recipient, source]},
                      "moves": [{"source": 4, "target": 9, "people": 1, "distance": 7}, dict(move)] if year == 1 else [],
                      "government": {"works": {"projects": [
                          {"project_id": 0, "target": 4, "owner": 0, "workers": 4,
                           "used": {"ore": 2, "tools": 2}, "field_trial": True},
                      ] if paid else []}},
                      "regions": [{"id": 4, "owner": 0, "production": {
                          "farm_tech_level": int(year == 3),
                          "produced": {"food": 618}, "food_without_tech": 600}}]})
    return years


@patch("civsim.chronicle.annual_candidates", return_value=[])
class DiffusionChronicleTests(unittest.TestCase):
    def test_later_paid_application_refers_to_the_exact_original_migration_and_first_harvest(self, _):
        observer = Chronicle()
        years = exchange_years()
        observer.observe(years[0])
        contact, = observer.report()["events"]
        self.assertEqual(contact["kind"], "farm_knowledge_contact")
        self.assertEqual(contact["evidence"]["people"], {"pointer": "/moves/1/people", "value": 3})
        observer.observe(years[1])
        _, transfer = observer.report()["events"]
        self.assertEqual((transfer["kind"], transfer["region"]), ("farm_tech_transfer", 4))
        self.assertIsNone(transfer["application"])
        self.assertEqual(transfer["evidence"]["method"]["value"], "transfer")
        self.assertEqual(transfer["evidence"]["trial_workers"]["value"], 2)
        observer.observe(years[2])
        _, transfer = observer.report()["events"]
        self.assertEqual(transfer["contact"]["year"], 1)
        self.assertEqual(transfer["application"]["year"], 3)
        self.assertIn("600", render_markdown(observer.report()))
        for ledger in (contact, transfer["contact"], transfer, transfer["application"]):
            row = years[ledger["year"]-1]
            self.assertEqual(ledger["record_sha256"], sha256(canonical_line(row)).hexdigest())
            for fact in ledger["evidence"].values():
                self.assertEqual(resolve(row, fact["pointer"]), fact["value"])

    def test_two_paid_independent_trials_keep_their_origin_even_after_contact(self, _):
        years = exchange_years()
        years[1]["diffusion"]["regions"][0]["closing_method"] = "independent"
        years[1]["research"]["regions"][0].update(cumulative_workers=4, cumulative_tools=2, cumulative_ore=2)
        observer = Chronicle()
        for year in years[:2]:
            observer.observe(year)
        contact, advance = observer.report()["events"]
        self.assertEqual((contact["kind"], advance["kind"]), ("farm_knowledge_contact", "farm_tech_adoption"))
        self.assertEqual(advance["evidence"]["method"]["value"], "independent")
        self.assertNotIn("contact", advance)

    def test_rejects_wrong_migrant_receipt_or_invented_prior_contact(self, _):
        for field in ("people", "source", "target", "distance", "move_index"):
            with self.subTest(field=field):
                year = exchange_years()[0]
                year["diffusion"]["regions"][0]["closing_contact"][field] += 1
                with self.assertRaises(ValueError):
                    Chronicle().observe(year)
        years = exchange_years()
        observer = Chronicle()
        observer.observe(years[0])
        years[1]["diffusion"]["regions"][0]["opening_contact"]["people"] = 2
        with self.assertRaises(ValueError):
            observer.observe(years[1])


class ReplayedDiffusionChronicleTests(unittest.TestCase):
    def test_seed_two_contact_at_year_five_is_realized_locally_eleven_years_later(self):
        save = Path(__file__).resolve().parents[1] / "examples/diffusion72/seed2-year17.json"
        chronicle = Chronicle(seed=2)
        journal, _ = load(save, observer=chronicle)
        events = [e for e in chronicle.report()["events"]
                  if e["region"] == 19 and e["kind"].startswith("farm_")]
        self.assertEqual([e["kind"] for e in events], ["farm_knowledge_contact", "farm_tech_transfer"])
        contact, transfer = events
        self.assertEqual((contact["year"], transfer["year"], transfer["application"]["year"]), (5, 16, 17))
        self.assertEqual([contact["evidence"][k]["value"] for k in ("source", "target", "people", "distance")],
                         [16, 19, 23, 10])
        self.assertEqual(contact["evidence"]["people"]["pointer"], "/moves/10/people")
        self.assertEqual([transfer["evidence"]["trial_" + k]["value"] for k in ("workers", "ore", "tools")],
                         [2, 1, 1])
        harvest = transfer["application"]["evidence"]
        self.assertEqual((harvest["food_produced"]["value"], harvest["food_without_tech"]["value"]), (1589, 1543))
        for ledger in (transfer["contact"], transfer, transfer["application"]):
            self.assertEqual(ledger["record_sha256"], journal["turns"][ledger["year"]-1]["record_sha256"])
