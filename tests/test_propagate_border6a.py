from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from civsim.diplomacy import diplomacy_snapshot, start_diplomacy, step_diplomacy
from civsim.model import generate_world
from civsim.regions import regionalize
from experiments.phase5a import _sha
from experiments.propagate_border6a import follow_case, run_followups


class TradeFollowupTests(unittest.TestCase):
    def test_only_one_year_is_intervened_and_branch_state_carries(self):
        sim = start_diplomacy(regionalize(generate_world(0)))
        for year in range(1,12):
            preview = deepcopy(sim)
            row = step_diplomacy(preview, year, "D")
            directions = [d for p in row["diplomacy"]["pairs"] for d in p["policy"]["directions"]
                          if d["trade_limit_permille"]<1000]
            if directions:
                break
            sim = preview
        self.assertTrue(directions)
        d = directions[0]
        setting = {"kind":"open_trade","source":d["source"],"target":d["target"]}
        case = {"seed":0,"arm":"D","year":year,"a":min(d["source"],d["target"]),"b":max(d["source"],d["target"]),
                "selection":"earliest","exposure":0,"intervention":setting}
        before = _sha(diplomacy_snapshot(sim))
        report = follow_case(sim, case)
        self.assertEqual(_sha(diplomacy_snapshot(sim)),before)
        self.assertEqual(report["t"]["actual_annual_sha256"],_sha(row))
        self.assertEqual(report["t"]["actual_annual_sha256"],report["t"]["actual_fork_sha256"])
        self.assertEqual(report["t"]["opened_annual_sha256"],report["t"]["opened_fork_sha256"])
        self.assertTrue(report["t"]["all_production_records_identical"])
        self.assertTrue(report["t_plus_1"]["both_use_ordinary_D"])
        next_row = step_diplomacy(preview,year+1,"D")
        self.assertEqual(report["t_plus_1"]["actual_annual_sha256"],_sha(next_row))
        for frame in (report["t"],report["t_plus_1"]):
            self.assertEqual(len(frame["regions"]),32)
            for key,value in frame["world"]["opened_minus_actual"].items():
                self.assertEqual(value,sum(r["opened_minus_actual"][key] for r in frame["regions"]))

    def test_existing_destination_is_preserved(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp,"kept")
            out.write_text("unaltered",encoding="utf8")
            with self.assertRaises(FileExistsError):
                run_followups(Path(tmp,"missing"),out)
            self.assertEqual(out.read_text(encoding="utf8"),"unaltered")
