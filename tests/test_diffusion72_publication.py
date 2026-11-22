import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from experiments.check_diffusion72 import check_pairs, verify


ROOT = Path(__file__).resolve().parents[1] / "studies"


class PublishedFarmExchangeTests(unittest.TestCase):
    def test_raw_tables_journals_and_checkpoints_agree(self):
        result = verify(ROOT / "diffusion72/long", ROOT / "research71/long")
        self.assertEqual(result["trajectories"], 80)
        self.assertEqual(result["annual_digest_entries"], 16_000)
        self.assertEqual(result["paired_world_checkpoints"], 120)
        self.assertEqual(result["regional_checkpoints"], 7_680)

    def test_missing_indicator_is_rejected_even_if_other_deltas_are_zero(self):
        pairs = json.loads((ROOT / "diffusion72/long/paired.json").read_bytes())
        del pairs[0]["population"]
        with TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / "paired.json").write_text(json.dumps(pairs), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing or unexpected paired indicator"):
                check_pairs(directory, {})
