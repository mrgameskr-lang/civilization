from pathlib import Path
import unittest

from civsim.storage import canonical_line
from experiments.region_custody_case import run_case, shrinking_home, stocked_destination


class RecordedCustodyCases(unittest.TestCase):
    def test_all_three_official_cases_replay_exactly(self):
        root=Path(__file__).resolve().parents[1]/"examples"/"location-upkeep-v1"
        for filename, run in (("custody-case",run_case),("shrinking-home",shrinking_home),
                              ("stocked-destination",stocked_destination)):
            with self.subTest(filename=filename):
                self.assertEqual(canonical_line(run()),(root/(filename+".json")).read_bytes())
