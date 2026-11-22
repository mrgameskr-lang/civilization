from hashlib import sha256
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from civsim.annual_game import create, load, play
from civsim.chronicle import Chronicle, render_highlights, render_markdown
from civsim.chronicle_event import Candidate, resolve
from civsim.storage import canonical_line


class ResearchChronicleTests(unittest.TestCase):
    def test_seed_zero_real_project_and_first_harvest_are_separate_verified_records(self):
        observer = Chronicle(seed=0)
        game = create(0)
        rows = []
        for year in range(1, 5):
            row = play(game, {"move": None, "research": True} if year == 1 else None)
            observer.observe(row)
            rows.append(row)
        event, = [e for e in observer.report()["events"]
                  if e["kind"] == "farm_tech_adoption" and e["region"] == 20]
        self.assertEqual((event["year"], event["country"], event["application"]["year"]), (3, 5, 4))
        self.assertEqual([event["evidence"]["cumulative_" + k]["value"] for k in ("workers", "ore", "tools")],
                         [4, 2, 2])
        for ledger in (event, event["application"]):
            actual = rows[ledger["year"] - 1]
            self.assertEqual(ledger["record_sha256"], sha256(canonical_line(actual)).hexdigest())
            for fact in ledger["evidence"].values():
                self.assertEqual(fact["value"], resolve(actual, fact["pointer"]))
        food = event["application"]["evidence"]
        self.assertEqual((food["food_produced"]["value"], food["food_without_tech"]["value"]), (5024, 4878))

    def test_disabled_research_replays_both_published_six_year_chronicles(self):
        archive = Path(__file__).resolve().parents[1] / "studies/chronicle7/small"
        expected = json.loads((archive / "verification.json").read_bytes())
        for world in expected["worlds"]:
            seed = world["seed"]
            with self.subTest(seed=seed):
                directory = archive / f"seed-{seed}"
                observer = Chronicle(seed=seed)
                load(directory / "save.json", observer=observer)
                report = observer.report()
                self.assertEqual(sha256(canonical_line(report)).hexdigest(), world["chronicle_sha256"])
                self.assertEqual(report, json.loads((directory / "chronicle.json").read_bytes()))
                self.assertEqual(render_markdown(report).encode(), (directory / "chronicle.md").read_bytes())
                self.assertEqual(render_highlights(report).encode(), (directory / "highlights.md").read_bytes())

    def research_row(self, year, previous, closing, paid, mastered, applying=False):
        trial = {"id": 12, "owner": 3, "level_before": previous, "level_after": closing,
                 "trial_workers": 2 * paid, "trial_ore": int(paid), "trial_tools": int(paid),
                 "cumulative_workers": 4 if mastered else 2, "cumulative_ore": 2 if mastered else 1,
                 "cumulative_tools": 2 if mastered else 1, "adoption_year": mastered,
                 "project_id": 0 if paid else None,
                 "first_application": applying}
        return {"year": year, "research": {"regions": [trial]},
                "government": {"works": {"projects": [
                    {"project_id": 0, "owner": 3, "target": 12, "field_trial": True,
                     "workers": 4, "used": {"ore": 2, "tools": 2}}
                ] if paid else []}},
                "regions": [{"id": 12, "owner": 3, "opening": {"name": "다르온 1"},
                             "production": {"farm_tech_level": int(applying), "produced": {"food": 108},
                                            "food_without_tech": 105}}]}

    def test_completion_is_visible_immediately_and_applied_production_cites_next_year(self):
        observer = Chronicle()
        trial = self.research_row(1, 0, 0, True, None)
        mastery = self.research_row(2, 0, 1, True, 2)
        application = self.research_row(3, 1, 1, False, 2, True)
        with patch("civsim.chronicle.annual_candidates", return_value=[]):
            observer.observe(trial)
            self.assertEqual(observer.report()["events"], [])
            observer.observe(mastery)
            completed, = observer.report()["events"]
            self.assertEqual((completed["year"], completed["country"], completed["region"]), (2,3,12))
            self.assertEqual(completed["evidence"]["cumulative_workers"]["value"], 4)
            self.assertEqual(completed["evidence"]["project_workers_total"]["value"], 4)
            self.assertIsNone(completed["application"])
            observer.observe(application)
            observer.observe(self.research_row(4, 1, 1, False, 2))
        entry, = observer.report()["events"]
        self.assertEqual(entry["kind"], "farm_tech_adoption")
        self.assertIsNone(completed["application"])
        self.assertEqual(entry["application"]["year"], 3)
        self.assertEqual(entry["application"]["evidence"]["food_produced"]["value"], 108)
        self.assertEqual(entry["application"]["evidence"]["food_without_tech"]["value"], 105)
        for source, year_row in [(entry, mastery), (entry["application"], application)]:
            self.assertEqual(source["record_sha256"], sha256(canonical_line(year_row)).hexdigest())
            for fact in source["evidence"].values():
                self.assertEqual(resolve(year_row, fact["pointer"]), fact["value"])
        self.assertIn("108", render_markdown(observer.report()))

    def test_all_adoptions_are_recorded_without_displacing_ordinary_history(self):
        row = {"year": 1, "q": 4}
        ordinary = [Candidate("collective_action", i, None, 70, "주민들이 청원했다.", {"count": "/q"})
                    for i in range(8)]
        adoptions = [Candidate("farm_tech_adoption", i, i+10, 90, "새 농법을 적용했다.", {"count": "/q"})
                     for i in range(6)]
        observer = Chronicle(seed=1)
        with patch("civsim.chronicle.annual_candidates", return_value=ordinary), \
                patch("civsim.chronicle.farm_adoptions", return_value=adoptions):
            observer.observe(row)
        report = observer.report()
        self.assertEqual(report["candidates"], 14)
        self.assertEqual(report["excluded_by_year_limit"], 4)
        self.assertEqual([e["country"] for e in report["events"] if e["kind"] == "farm_tech_adoption"],
                         list(range(6)))
        self.assertEqual([e["country"] for e in report["events"] if e["kind"] == "collective_action"],
                         list(range(4)))
        self.assertEqual(render_markdown(report).count("새 농법을 적용했다."), 6)
        self.assertTrue(all(e["record_sha256"] == sha256(canonical_line(row)).hexdigest()
                            for e in report["events"]))
