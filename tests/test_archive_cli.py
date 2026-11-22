"""End-to-end coverage for the versioned manifest directories shipped in samples/."""
from hashlib import sha256
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from civsim.analysis import summary, write_panel
from tests.test_cli import PACKAGE_ROOT, call_cli


SAMPLES = (
    ("6.0A.1", "samples/phase6a1/seed0-capped", "civsim.aid61"),
    ("6.0B1", "samples/phase6b1/seed0-warehouse", "civsim.depot62_cli"),
    ("6.0B2", "samples/phase6b2/seed0-service", "civsim.peace62_cli"),
)


class ArchiveCommandTests(unittest.TestCase):
    def test_verify_replays_shipped_archives(self):
        for version, path, _ in SAMPLES:
            with self.subTest(version=version):
                result = call_cli("verify", path)
                expected = sha256((PACKAGE_ROOT / path / "years.jsonl").read_bytes()).hexdigest()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), expected)

    def test_verify_rejects_changed_archive(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "변경한 장부"
            shutil.copytree(PACKAGE_ROOT / SAMPLES[0][1], target)
            annual = target / "years.jsonl"
            with annual.open("r+b") as f:
                original = f.readline()
                changed = original.replace(b'"year":1', b'"year":9', 1)
                self.assertNotEqual(original, changed)
                f.seek(0)
                f.write(changed)
            result = call_cli("verify", target)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("year 1", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_analyze_reports_version_and_real_alternatives_before_export(self):
        with tempfile.TemporaryDirectory() as d:
            export = Path(d) / "unused.csv"
            for version, path, module in SAMPLES:
                with self.subTest(version=version):
                    result = call_cli("analyze", path, "--csv", export)
                    self.assertNotEqual(result.returncode, 0)
                    for text in (version, module + " verify", "json.tool --json-lines", "years.jsonl"):
                        self.assertIn(text, result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    with self.assertRaisesRegex(ValueError, module.replace(".", r"\.")):
                        write_panel(PACKAGE_ROOT / path, export)
                    self.assertFalse(export.exists())

    def test_single_file_formats_name_their_own_reader(self):
        for path, module, action in (
            ("examples/annual-unit-v1/saves/year1.json", "civsim.annual_game", "show"),
            ("examples/annual-unit-v1/position-saves/next.json", "civsim.annual_game", "show"),
            ("examples/unit-board-checks/turn-2.json", "civsim.unit_game", "show"),
            ("examples/phase6c1-m1/seed0-eight-years.jsonl", "civsim.posting_archive65", "verify"),
        ):
            with self.subTest(path=path):
                result = call_cli("analyze", path)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"python -m {module} {action}", result.stderr)
                self.assertIn(Path(path).name, result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_raw_rows_and_unrecognized_files_have_directory_guidance(self):
        with tempfile.TemporaryDirectory() as d:
            unknown = Path(d) / "many-rows.jsonl"
            unknown.write_bytes(b'{"year":1}\n' * 100_000)
            for path in ("examples/seed-42/years.jsonl", unknown):
                with self.subTest(path=path):
                    result = call_cli("analyze", path)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("manifest.json", result.stderr)
                    self.assertIn("python -m civsim", result.stderr)
                    self.assertNotIn("Errno", result.stderr)

    def test_missing_unknown_and_nonstring_versions_are_value_errors(self):
        with tempfile.TemporaryDirectory() as d:
            for version in (None, [], {}, "99.7"):
                with self.subTest(version=version):
                    meta = {"schema": 1, "years": 2, "model_version": version}
                    (Path(d) / "manifest.json").write_text(json.dumps(meta), encoding="utf8")
                    with self.assertRaisesRegex(ValueError, "model_version"):
                        summary(Path(d))
