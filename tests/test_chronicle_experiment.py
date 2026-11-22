import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from experiments.chronicle7 import CitationCheck, digest, write_report


class IndependentCitationTest(unittest.TestCase):
    def test_check_rejects_wrong_year_hash_amount_and_type(self):
        row = {"year": 8, "entries": [{"a/b~c": 1}]}
        source = "/entries/0/a~1b~0c"
        for value, checksum in ((2, digest(row)), (True, digest(row)), (1, "0" * 64)):
            with self.subTest(value=value, checksum=checksum):
                event = {"year": 8, "record_sha256": checksum,
                         "evidence": {"received": {"pointer": source, "value": value}}}
                with self.assertRaises(ValueError):
                    CitationCheck([event]).observe(row)

    def test_report_round_trip_with_zero_one_or_many_events(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "chronicle.json"
            for size in (0, 1, 3):
                report = {"events": [{"description": "기록", "year": y} for y in range(size)],
                          "seed": 20, "years": size}
                write_report(path, report)
                self.assertEqual(json.loads(path.read_bytes()), report)
