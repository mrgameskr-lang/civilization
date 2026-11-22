from contextlib import redirect_stdout
from copy import deepcopy
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from civsim import annual_game
from civsim.relief_benefits import VERSION, ReliefBenefitsObserver, audit_relief_benefits, relief_benefits
from civsim.storage import canonical_line
from experiments.reserve_relief_study import advance


def call(*args):
    out = StringIO()
    with redirect_stdout(out):
        annual_game.main(list(map(str, args)))
    return json.loads(out.getvalue())


class ReliefBenefitsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        game = annual_game.create(0)
        cls.first = advance(game, 1, "E")
        cls.second = advance(game, 2, "E")

    def test_direct_benefits_include_all_receipts_but_actual_meals_stay_separate(self):
        r = self.second
        frozen = canonical_line(r)
        report = relief_benefits(r)
        self.assertEqual(canonical_line(r), frozen)
        self.assertEqual((report["version"], report["year"], report["emergency_active"]), (VERSION, 2, True))
        self.assertEqual([x["region"] for x in report["regions"]], list(range(32)))
        local = report["regions"][0]
        self.assertEqual((local["ordinary_received"], local["emergency_received"], local["relief_received"],
                          local["legacy_relief_food"], local["food_eaten"], local["food_unmet"]),
                         (0,358,358,0,5205,3230))
        expected = sum(row["consumption"]["food_eaten"] for row in r["regions"])
        self.assertEqual(report["totals"]["food_eaten"], expected)
        self.assertEqual(report["totals"]["emergency_received"], 1972)
        audit_relief_benefits(r, json.loads(json.dumps(report)))
        # Canonical public CLI representation of the pinned seed-0 E turn at 58f852e.
        public_row = json.loads(frozen)
        self.assertEqual(sha256(canonical_line(public_row)).hexdigest(),
                         "ee4f348cc5df1155cc16d21945d19dec0174f7d676b0a940b44f3fbb63db0bc0")

    def test_stage_is_absent_in_historical_rows_and_empty_observer_output(self):
        observer = ReliefBenefitsObserver()
        self.assertEqual(observer.report(), {"version": VERSION, "years": []})
        with self.assertRaises(ValueError): observer.observe(self.second)
        observer.observe(self.first)
        result = observer.report()
        self.assertFalse(result["years"][0]["emergency_active"])
        self.assertEqual(result["years"][0]["totals"]["emergency_received"], 0)
        with self.assertRaises(ValueError): observer.observe(self.first)
        self.assertEqual(len(observer.report()["years"]), 1)

    def test_replay_dispatches_every_year_to_an_iterator_of_observers(self):
        slot = Path(__file__).resolve().parents[1] / "examples/annual-unit-v1/position-saves/next.json"
        first, second = ReliefBenefitsObserver(), ReliefBenefitsObserver()
        journal, _ = annual_game.load(slot, observers=iter((first, second)))
        years = [turn["year"] for turn in journal["turns"]]
        self.assertEqual(years, [1,2,3])
        for obs in (first, second):
            self.assertEqual([row["year"] for row in obs.report()["years"]], years)

    def test_missing_or_altered_receipt_or_inconsistent_destination_rejected(self):
        for damage in ("mismatch", "source", "target", "identity", "duplicate", "meals", "missing_stage", "malformed_quantity"):
            r = deepcopy(self.second)
            e = r["emergency_relief"]
            trip = e["shipments"][0]
            rows = {n["id"]: n for n in e["nodes"]}
            if damage == "mismatch": trip["quantity"] -= 1
            elif damage == "source": rows[trip["source"]]["depot_close"]["food"] += 1
            elif damage == "target": rows[trip["target"]]["private_food_close"] -= 1
            elif damage == "identity": trip["owner"] += 1
            elif damage == "duplicate": e["nodes"].append(deepcopy(e["nodes"][0]))
            elif damage == "meals": r["regions"][0]["consumption"]["food_eaten"] += 1
            elif damage == "missing_stage": del r["emergency_relief"]
            else: trip["quantity"] = True
            with self.subTest(damage=damage), self.assertRaises(ValueError): relief_benefits(r)

    def test_derived_altered_totals_fields_or_attribution_are_rejected_by_separate_audit(self):
        for key in ("relief_received", "food_eaten", "ordinary_received", "emergency_received", "legacy_relief_food"):
            report = relief_benefits(self.second)
            report["regions"][0][key] += 1
            report["totals"][key] += 1
            with self.subTest(key=key), self.assertRaises(ValueError): audit_relief_benefits(self.second, report)

    def test_remote_cargo_is_credited_to_receiving_households_and_freight_stays_with_sender(self):
        from civsim.public_works import execute_relief
        from tests.test_public_works5 import fixture, order
        areas, roads, depots = fixture()
        depots[0]["food"] = 15
        stage, _ = execute_relief(areas, roads, depots, order("relief",2,4),
                                  {(0,1):5,(1,2):5}, {0:10}, width=3)
        record = {"year":1, "public_policy":{}, "government":{"relief":stage, "levies":[]},
                  "politics":{"regions":[]}, "regions":[], "domestic":{"nodes":[]}}
        for r in areas:
            q = r.stock["food"]
            meal = {"opening_food":q, "food_need":r.population, "food_eaten":q, "food_unmet":r.population-q}
            evidence = {"food_eaten":q, "food_unmet":r.population-q, "relief_food":q}
            record["regions"].append({"id":r.id, "owner":0, "consumption":meal})
            record["politics"]["regions"].append({"id":r.id, "owner":0, "closing":{"evidence":evidence}})
            record["government"]["levies"].append({"region":r.id, "private_close":{"food":0}})
            record["domestic"]["nodes"].append({"id":r.id, "opening":{"food":q}})
        report = relief_benefits(record)
        self.assertEqual((stage["shipments"][0]["source"], stage["shipments"][0]["path"], stage["cost_food"]),
                         (0,[0,1,2],2))
        self.assertEqual([r["relief_received"] for r in report["regions"]], [0,0,4])
        self.assertEqual(report["totals"]["food_eaten"], 4)

    def test_cli_optional_new_and_replayed_observation_preserve_save_and_engine_results(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            start,first,second,plain=(base/name for name in ("start","first","second","plain"))
            call("new", "--seed", 0, "--out", start)
            self.assertEqual(call("show", start, "--relief-benefits")["relief_benefits"]["years"], [])
            call("step", start, "--out", first)
            live = call("step", first, "--out", second, "--reserve-policy","emergency", "--relief-benefits")
            old = call("step", first, "--out", plain, "--reserve-policy","emergency")
            self.assertNotIn("relief_benefits", old)
            self.assertEqual(second.read_bytes(), plain.read_bytes())
            observed = call("show", second, "--relief-benefits", "--custody")
            self.assertIn("custody", observed)
            years = observed["relief_benefits"]["years"]
            self.assertEqual([y["year"] for y in years], [1,2])
            self.assertEqual(live["relief_benefits"]["years"], [years[1]])
            self.assertTrue(years[1]["emergency_active"])
            self.assertNotIn("relief_benefits", call("show", second))
