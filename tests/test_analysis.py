import csv
import json
import tempfile
import unittest
from pathlib import Path

from civsim.analysis import summary, write_panel


def country_record(nation_id, opening, closing, births, deaths, incoming, outgoing, eaten):
    def state(population):
        return {"id": nation_id, "name": ("아르덴", "벨로라")[nation_id],
                "population": population, "stock": {"food": 13, "ore": 7, "tools": 2},
                "cash": 140, "soil": 987, "deposit": 456}

    return {
        "id": nation_id, "opening": state(opening), "closing": state(closing),
        "production": {"produced": {"food": 102, "ore": 8, "tools": 4}},
        "consumption": {"food_need": opening, "food_eaten": eaten, "food_spoiled": 1},
        "demography": {"births": births, "deaths": deaths,
                       "immigrants": incoming, "emigrants": outgoing},
    }


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        manifest = {"schema": 1, "model_version": "1", "years": 2, "seed": 8,
                    "width": 2, "height": 1, "nations": 2}
        (self.directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        prices = {0: {"food": 7, "ore": 5, "tools": 8}, 1: {"food": 12, "ore": 3, "tools": 9}}
        trades = [{"seller": 0, "buyer": 1, "good": "food", "quantity": 3, "unit_price": 9},
                  {"seller": 1, "buyer": 0, "good": "ore", "quantity": 2, "unit_price": 4}]
        records = [
            {"year": 1, "countries": [country_record(0, 100, 98, 1, 2, 0, 1, 100),
                                      country_record(1, 80, 83, 2, 0, 1, 0, 70)],
             "market": {"trades": trades, "prices": prices},
             "moves": [{"source": 0, "target": 1, "people": 1}], "events": []},
            {"year": 2, "countries": [country_record(0, 98, 99, 2, 1, 0, 0, 98),
                                      country_record(1, 83, 84, 2, 1, 0, 0, 83)],
             "market": {"trades": [], "prices": prices}, "moves": [], "events": []},
        ]
        self.ledger = self.directory / "years.jsonl"
        self.ledger.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")

    def test_summary_uses_first_open_last_close_and_counts_each_transfer_once(self):
        result = summary(self.directory)
        expected = {"initial_population": 180, "final_population": 183,
                    "total_births": 7, "total_deaths": 4, "total_migrants": 1,
                    "total_food_traded": 3, "shortage_country_years": 1,
                    "total_food_need": 361, "total_food_eaten": 351}
        self.assertEqual({key: result[key] for key in expected}, expected)

    def test_panel_preserves_units_country_names_and_transfer_direction(self):
        output = self.directory / "panel.csv"
        write_panel(self.directory, output)
        with output.open(encoding="utf-8-sig", newline="") as stream:
            panel = list(csv.DictReader(stream))
        self.assertEqual([(r["year"], r["nation_id"]) for r in panel],
                         [("1", "0"), ("1", "1"), ("2", "0"), ("2", "1")])
        seller, buyer = panel[:2]
        self.assertEqual(seller["name"], "아르덴")
        expected_seller = {"food_exports": 3, "food_imports": 0, "ore_imports": 2,
                           "export_value": 27, "import_value": 8, "cash": 140,
                           "food_price": 7, "population_open": 100, "population_close": 98}
        expected_buyer = {"food_produced": 102, "food_need": 80, "food_eaten": 70,
                          "food_shortfall": 10, "food_spoiled": 1, "food_stock": 13,
                          "ore_stock": 7, "tools_stock": 2, "soil": 987, "deposit": 456,
                          "immigrants": 1, "emigrants": 0, "births": 2, "deaths": 0}
        for row, expected in [(seller, expected_seller), (buyer, expected_buyer)]:
            self.assertEqual({k: int(row[k]) for k in expected}, expected)

    def test_raw_ledger_and_existing_exports_are_preserved(self):
        for path in [self.ledger, self.directory / "manifest.json"]:
            original = path.read_bytes()
            with self.assertRaises(FileExistsError):
                write_panel(self.directory, path)
            self.assertEqual(path.read_bytes(), original)
        exported = self.directory / "existing.csv"
        exported.write_bytes(b"existing export")
        with self.assertRaises(FileExistsError):
            write_panel(self.directory, exported)
        self.assertEqual(exported.read_bytes(), b"existing export")

    def test_truncated_input_has_no_partial_export(self):
        output = self.directory / "panel.csv"
        self.ledger.write_text(self.ledger.read_text(encoding="utf-8").splitlines()[0] + "\n",
                               encoding="utf-8")
        with self.assertRaises(ValueError):
            write_panel(self.directory, output)
        self.assertFalse(output.exists())
