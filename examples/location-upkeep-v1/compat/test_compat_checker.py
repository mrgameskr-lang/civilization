"""A wrong digest, a missing year and pre-existing evidence must fail closed."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from experiments import verify_annual21 as check


class CompatibilityCheckerTests(unittest.TestCase):
    def test_rejects_changed_chain_and_truncated_checkpoints(self):
        name = f'{check.EXAMPLE}/study/seed-00.json'
        original = json.loads(check.archived(name))
        for corruption in ('changed_hash', 'missing_year'):
            with self.subTest(corruption=corruption):
                altered = deepcopy(original)
                points = altered['paths'][0]['checkpoints']
                if corruption == 'changed_hash':
                    points[0]['annual_chain_sha256'] = '0' * 64
                else:
                    points.pop()
                with patch.object(check.annual_unit_study, 'run_seed', return_value=altered):
                    with self.assertRaisesRegex(ValueError, 'Replay differs'):
                        check.compare_seed((0, check.HORIZONS))

    def test_preserves_existing_receipt(self):
        with TemporaryDirectory() as folder:
            receipt = Path(folder) / 'receipt.json'
            receipt.write_bytes(b'previous evidence')
            with self.assertRaises(FileExistsError):
                check.verify(receipt, 'smoke', 1)
            self.assertEqual(receipt.read_bytes(), b'previous evidence')
