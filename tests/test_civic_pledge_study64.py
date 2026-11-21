from copy import deepcopy
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments.civic_pledge_study64 import (
    ACTION_FIELDS, ECONOMIC, MODES, PRIOR, check_source_pair, seed_paths, summarize_settlement, run_study,
)


class PledgeStudyTests(unittest.TestCase):
    def test_holding_consultation_cannot_replace_an_economic_observation(self):
        a = {"seed": 9, "year": 3, "a": 0, "b": 1, "evidence_year": 2,
             "observed": True, "evidence": [{"trade_value": 2}], "signal": {}, "event": "start",
             "closing": {"active": True, "quiet_years": 0, "consulting": False}}
        b = deepcopy(a)
        b["closing"]["consulting"] = True
        check_source_pair(a, b)
        b["evidence"][0]["trade_value"] = 0
        with self.assertRaises(ValueError):
            check_source_pair(a, b)

    def test_missing_review_and_right_censoring_have_separate_denominators(self):
        counts = summarize_settlement(signed=4, assessed=3, kept=2, broken=1, unknown=3)
        self.assertEqual(counts, {"pending": 1, "pending_party_judgments": 2})
        with self.assertRaises(ValueError):
            summarize_settlement(signed=4, assessed=3, kept=2, broken=1, unknown=2)

    def test_existing_output_never_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            where = Path(folder)
            (where/"keep").write_bytes(b"evidence")
            with self.assertRaises(FileExistsError):
                run_study(where, "dev")
            self.assertEqual((where/"keep").read_bytes(), b"evidence")

    def test_short_archived_path_replays_off_bytes_and_balances_individual_promises(self):
        with gzip.open(PRIOR/"diplomacy/dev/annual.jsonl.gz", "rb") as f:
            source_bytes = [f.readline() for _ in range(12)]
        historic = {}
        for i, mode in enumerate(MODES):
            historic[0,mode,6] = {"initial_sha256": "fixture", "economic_years_sha256": "fixture",
                                 "civic_years_sha256": hashlib.sha256(b"".join(source_bytes[i::2])).hexdigest(),
                                 **dict.fromkeys(ECONOMIC, 0)}
        tables = {k: [] for k in ("runs","countries","pairs","cases","forks")}
        raw = io.StringIO()
        events = io.StringIO()
        with patch("experiments.civic_pledge_study64.HORIZONS", (6,)):
            seed_paths(0,6,io.BytesIO(b"".join(source_bytes)),historic,
                       {"annual":raw,"actions":csv.DictWriter(events,ACTION_FIELDS)},tables)
        rows = raw.getvalue().splitlines(keepends=True)
        self.assertEqual("".join(rows[::2]).encode(), b"".join(source_bytes))
        states = {(r["mode"],r["pledges"]):r for r in tables["runs"]}
        self.assertGreater(states["consult","on"]["signed"], 0)
        self.assertEqual(states["observe","on"]["signed"], 0)
        self.assertEqual(tables["forks"][0]["pair_years"], 28*6)
        state = states["consult","on"]
        countries = [r for r in tables["countries"] if (r["mode"],r["pledges"]) == ("consult","on")]
        self.assertEqual(2*state["signed"], sum(c["jointly_committed"] for c in countries))
        self.assertEqual(2*state["assessed"], sum(c["assessed"] for c in countries))
        self.assertEqual(json.loads(rows[0])["mode"], "observe")
