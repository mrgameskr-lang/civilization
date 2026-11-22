import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from experiments.relief_forks import _count_obstructions, _natural_case, make_case, publish, transport_control


class ReliefForkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = make_case(0, 3)

    def test_shared_opening_and_policy_on_both_followup_branches(self):
        case = self.case
        first, second = case["years"]
        self.assertEqual(first["held"]["opening_sha256"], first["early"]["opening_sha256"])
        self.assertEqual(first["early"]["regular"], first["held"]["regular"])
        self.assertIsNone(first["held"]["emergency"])
        self.assertGreater(first["early"]["world"]["emergency_received"], 0)
        for branch in ("held", "early"):
            self.assertEqual(first[branch]["closing_sha256"], second[branch]["opening_sha256"])
            self.assertEqual(second[branch]["emergency"]["version"], "emergency-relief/1")
            self.assertEqual(len(first[branch]["regions"]), 32)
            first_closes = {r["region"]: r for r in first[branch]["regions"]}
            for r in second[branch]["regions"]:
                for k in ("population", "private", "public"):
                    self.assertEqual(r[k+"_open"], first_closes[r["region"]][k+"_close"])
        for y in case["years"]:
            for k in y["delta_early_minus_held"]:
                self.assertEqual(y["delta_early_minus_held"][k], y["early"]["world"][k]-y["held"]["world"][k])

    def test_real_geography_control_can_separate_road_and_freight_failure(self):
        test = transport_control(self.case)
        self.assertTrue(test["synthetic_stage_inputs"])
        ok, road, fee = (test["variants"][key] for key in ("open", "blocked", "no_freight"))
        self.assertGreater(ok["application"]["received"], 0)
        self.assertTrue(any(len(s["path"]) > 1 for s in ok["target_shipments"]))
        self.assertGreater(road["application"]["unfilled"]["road"],0)
        self.assertGreater(fee["application"]["unfilled"]["freight"],0)
        self.assertEqual(ok["depot_food_open"],road["depot_food_open"])

    def test_copy_of_published_archive_is_immutable_and_matches_hash(self):
        from hashlib import sha256
        with TemporaryDirectory() as d:
            target = Path(d) / "forks"
            result = publish(target, [(0,3)])
            entry = result["cases"][0]
            path = target / entry["file"]
            self.assertEqual(sha256(path.read_bytes()).hexdigest(),entry["file_sha256"])
            self.assertEqual(json.loads(gzip.decompress(path.read_bytes())),self.case)
            with self.assertRaises(FileExistsError):
                publish(target, [(0,3)])

    def test_terminal_obstacle_census_counts_one_world_year_even_with_both_reasons(self):
        rows = [{"year": y, "world":{"emergency_unfilled_road": 2 if y in (4,9) else 0,
                                     "emergency_unfilled_freight":3 if y==4 else 0}} for y in range(1,201)]
        self.assertEqual(_count_obstructions(rows), ({"road":4,"freight":3},2,4))
        for invalid in (rows[1:], rows[:-1], rows+[rows[-1]]):
            with self.subTest(first=invalid[0]["year"], length=len(invalid)), self.assertRaises(ValueError):
                _count_obstructions(invalid)

    def test_optional_natural_fork_requires_a_real_transport_obstruction(self):
        # Exercise the documented one-year hold on an actual pre-existing E path.
        with self.assertRaisesRegex(ValueError, "no natural constraints"):
            _natural_case(0, 3)
