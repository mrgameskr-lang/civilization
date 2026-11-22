from unittest import TestCase
from pathlib import Path

from experiments.check_research71 import check, check_country, check_adoption


class PublishedStudyAuditTests(TestCase):
    def test_shipped_experiment_tables_and_journals_reconcile(self):
        directory = Path(__file__).resolve().parents[1] / "studies/research71/long"
        result = check(directory)
        self.assertEqual((result["trajectories"], result["country_checkpoints"]), (80, 1920))
        self.assertEqual((result["regenerated_opening_worlds"], result["research_journals"],
                          result["annual_digest_entries"], result["paired_world_checkpoints"]), (40, 40, 8000, 120))
        self.assertEqual(result["controls_with_published_pr28_hashes"], [0, 20])
        self.assertTrue(all(20 <= case["seed"] <= 39 for case in result["selected_cases"]))

    def test_both_cost_and_progress_identities_are_independent(self):
        row = dict(arm="research", year=50, regions=2, trials=3, trial_workers=6,
                   trial_ore=3, trial_tools=3, advanced_regions=1, first_adoption=5,
                   paid_trial=3, already_learned=45, other_fiscal_choice=52,
                   insufficient_expected_return=0, urgent_hunger=0, project_unfunded=0,
                   fixed_inputs_food_gain=6, food=100, annual_food=2, need=100,
                   unmet=10, support_points=4000, represented_members=8)
        check_country(row, [5])
        for field, value in [("trial_ore", 2), ("trial_workers", 5), ("advanced_regions", 0),
                             ("first_adoption", 6), ("other_fiscal_choice", 51)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                check_country({**row, field: value}, [5])

    def test_adoption_binds_owner_application_year_and_real_journal_hash(self):
        journal = [{"year": i, "record_sha256": str(i) * 64} for i in (1, 2, 3)]
        event = dict(owner=2, region=1, year=2, application_year=3, record_sha256="2"*64)
        check_adoption(event, journal, {1: 2})
        for key, value in [("owner", 1), ("record_sha256", "1"*64), ("application_year", 0), ("year", 0)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                check_adoption({**event, key: value}, journal, {1: 2})
