from pathlib import Path
import unittest
from experiments.annual_unit_case import verify
from experiments.annual_unit_study import run_seed


class AnnualEvidenceTests(unittest.TestCase):
    def test_published_case_replays_with_all_denials_and_next_year(self):
        path = Path(__file__).resolve().parents[1]/"examples"/"annual-unit-v1"/"case"
        self.assertEqual(len(verify(path)),8)

    def test_short_study_records_two_paths_from_a_single_opening(self):
        sample = run_seed(0,3,(2,3))
        move,hold = sample["paths"]
        self.assertTrue(move["receipt"]["ok"])
        self.assertIsNone(hold["receipt"])
        for a,b in zip(move["checkpoints"],hold["checkpoints"],strict=True):
            self.assertEqual(a["year"],b["year"])
            self.assertEqual(a["closing_away"],[[5,4,1]])
            self.assertEqual(b["closing_away"],[])
            self.assertNotEqual(a["annual_chain_sha256"],b["annual_chain_sha256"])
