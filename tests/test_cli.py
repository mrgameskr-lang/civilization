"""Exercise the installed interpreter's real module entry point."""

import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def call_cli(*arguments):
    return subprocess.run(
        [sys.executable, "-B", "-m", "civsim", *map(str, arguments)],
        cwd=PACKAGE_ROOT, capture_output=True, encoding="utf-8", timeout=30,
    )


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.run_dir = self.root / "실험 기록"

    def test_run_analyze_export_and_replay(self):
        run = call_cli("run", "--out", self.run_dir, "--seed", 13,
                       "--years", 2, "--width", 6, "--height", 4, "--nations", 2)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn(str(self.run_dir.resolve()), run.stdout)
        manifest = json.loads((self.run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual([manifest[k] for k in ("seed", "years", "width", "height", "nations")],
                         [13, 2, 6, 4, 2])
        panel = self.root / "국가별 분석.csv"
        analyze = call_cli("analyze", self.run_dir, "--csv", panel)
        self.assertEqual(analyze.returncode, 0, analyze.stderr)
        self.assertGreater(json.loads(analyze.stdout)["final_population"], 0)
        with panel.open(encoding="utf-8-sig", newline="") as stream:
            self.assertEqual(len(list(csv.DictReader(stream))), 4)
        verify = call_cli("verify", self.run_dir)
        self.assertEqual(verify.returncode, 0, verify.stderr)
        digest = hashlib.sha256((self.run_dir / "years.jsonl").read_bytes()).hexdigest()
        self.assertIn(digest, verify.stdout)

    def test_existing_directory_survives_refused_run(self):
        self.run_dir.mkdir()
        original = self.run_dir / "manifest.json"
        original.write_bytes(b"original bytes")
        result = call_cli("run", "--out", self.run_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(original.read_bytes(), b"original bytes")
        self.assertEqual(list(self.run_dir.iterdir()), [original])

    def test_input_and_dataset_errors_return_diagnostics(self):
        for args in [("run", "--out", self.run_dir, "--seed", "abc"),
                     ("run", "--out", self.run_dir, "--years", "0"),
                     ("analyze", self.run_dir), ("verify", self.run_dir)]:
            with self.subTest(args=args):
                result = call_cli(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(result.stderr.strip())
                self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(self.run_dir.exists())
