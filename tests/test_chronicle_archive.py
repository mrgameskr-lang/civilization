from hashlib import sha256
import json
from pathlib import Path
from shutil import copytree
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from civsim.chronicle import Chronicle
from civsim.chronicle_archive import observe_archive
from civsim.chronicle_event import resolve
from civsim.storage import verify_run


ROOT = Path(__file__).resolve().parents[1]
SHIPPED = (
    "examples/phase4/seed7-two-years", "examples/phase5/seed7-integrated",
    "examples/phase5b/seed0-feedback", "examples/phase5c/seed0-elections",
    "examples/phase5d/seed0-actions", "examples/phase6a/seed0-diplomacy",
    "samples/phase6a1/seed0-capped", "samples/phase6b1/seed0-warehouse",
    "samples/phase6b2/seed0-service",
)


class ChronicleArchiveTests(unittest.TestCase):
    def test_replay_shipped_regional_formats_and_crosscheck_raw_line_evidence(self):
        kinds = set()
        for relative in SHIPPED:
            with self.subTest(archive=relative):
                path = ROOT / relative
                meta = json.loads((path / "manifest.json").read_bytes())
                observer = Chronicle()
                self.assertEqual(observe_archive(path, observer), meta["seed"])
                report = observer.report()
                self.assertEqual(report["years"], meta["years"])
                self.assertTrue(report["events"])
                with (path / "years.jsonl").open("rb") as stream:
                    for year, line in enumerate(stream, 1):
                        row = json.loads(line)
                        for event in (e for e in report["events"] if e["year"] == year):
                            kinds.add(event["kind"])
                            self.assertEqual(event["record_sha256"], sha256(line).hexdigest())
                            for fact in event["evidence"].values():
                                self.assertEqual(resolve(row, fact["pointer"]), fact["value"])
        self.assertTrue({"food_crisis", "government_turnover", "collective_action", "trade_pact_started"} <= kinds)

    def test_national_only_archive_fails_with_supported_format_guidance(self):
        observer = Chronicle()
        with self.assertRaisesRegex(ValueError, "1.0.*지역"):
            observe_archive(ROOT / "examples/seed-42", observer)
        self.assertEqual(observer.report()["years"], 0)

    def test_changed_bytes_rejected_without_observing_a_partial_chronicle(self):
        with TemporaryDirectory() as tmp:
            path = copytree(ROOT / SHIPPED[0], Path(tmp) / "archive")
            years = path / "years.jsonl"
            with years.open("ab") as stream:
                stream.write(b"\n")
            observer = Chronicle()
            with self.assertRaises(ValueError):
                observe_archive(path, observer)
            self.assertEqual(observer.report()["years"], 0)

    def test_replacement_between_replay_and_observation_is_detected(self):
        with TemporaryDirectory() as tmp:
            path = copytree(ROOT / SHIPPED[0], Path(tmp) / "archive")
            def replace_after_replay(directory):
                digest = verify_run(directory)
                with (path / "years.jsonl").open("ab") as stream:
                    stream.write(b"\n")
                return digest
            observer = Chronicle()
            with patch("civsim.chronicle_archive.verify_run", side_effect=replace_after_replay):
                with self.assertRaisesRegex(ValueError, "변경"):
                    observe_archive(path, observer)
            self.assertEqual(observer.report()["years"], 0)
