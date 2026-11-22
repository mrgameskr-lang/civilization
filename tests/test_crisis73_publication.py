from pathlib import Path
import unittest

from experiments.check_crisis73 import verify
from experiments.check_diffusion72 import read_json
from experiments.crisis73_receipts import inspect_save


ROOT = Path(__file__).resolve().parents[1]


class BorderCrisisEvidenceTests(unittest.TestCase):
    def test_sample_costs_and_chronicle_links_match_physical_ledgers(self):
        folder = ROOT/"examples/crisis73"
        checked = inspect_save(folder/"seed0-year12.json")
        self.assertEqual(checked, read_json(folder/"receipt-check.json"))
        self.assertEqual((checked["years"], checked["worker_years"], checked["goods_released"],
                          checked["people_released"]), (12, 18, 0, 3))

    def test_published_tables_match_pair_transitions_and_archived_controls(self):
        result = verify(ROOT/"studies/crisis73/long", ROOT/"studies/diffusion72/long")
        self.assertEqual((result["journal_years"], result["worlds"], result["paired_checkpoints"]),
                         (16_000, 40, 120))
        self.assertGreater(result["verified_transition_events"], 0)
