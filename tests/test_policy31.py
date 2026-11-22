"""Opt-in policy identifiers, historical manifests and byte-exact replay."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from civsim.rules import POLICIES31, Rules
from civsim.storage import verify_run, write_run
from tests.test_cli import call_cli


class Policy31Tests(unittest.TestCase):
    def test_versions_and_invalid_combinations(self):
        self.assertEqual(len(POLICIES31), 7)
        self.assertEqual(Rules().version, "1.0")
        self.assertEqual(Rules("reallocate").version, "2.0")
        self.assertEqual(Rules("reallocate", investment="capital").version, "3.0")
        for name in POLICIES31:
            self.assertEqual(Rules("reallocate", investment="capital", policy31=name).version, "3.1")
            for incompatible in ("off", "inventory"):
                with self.assertRaises(ValueError):
                    Rules(investment=incompatible, policy31=name)
        with self.assertRaises(ValueError):
            Rules(investment="capital", policy31="unknown")

    def test_cli_persistence_and_manifest_version_boundary(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp, "trial")
            result = call_cli("run", "--out", out, "--years", 4, "--seed", 8, "--investment",
                              "capital", "--labor", "reallocate", "--policy31", "combined-multi")
            self.assertEqual(result.returncode, 0, result.stderr)
            path = out / "manifest.json"
            meta = json.loads(path.read_bytes())
            self.assertEqual(meta["model_version"], "3.1")
            self.assertEqual(meta["rules"]["policy31"], "combined-multi")
            replay = Path(tmp, "rerun")
            write_run(replay, seed=8, years=4, rules=Rules("reallocate", investment="capital",
                                                           policy31="combined-multi"))
            self.assertEqual(verify_run(out), verify_run(replay))
            for version, policy in (("3.1", None), ("3.1", "off"), ("3.0", "combined-multi")):
                altered = {**meta, "model_version": version, "rules": dict(meta["rules"])}
                if policy is None:
                    del altered["rules"]["policy31"]
                else:
                    altered["rules"]["policy31"] = policy
                path.write_text(json.dumps(altered), encoding="utf-8")
                with self.assertRaises(ValueError):
                    verify_run(out)
