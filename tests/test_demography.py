import unittest
from dataclasses import asdict

from civsim.demography import develop
from civsim.model import Nation


def country(identifier, population, land=100, food_reserve=0):
    return Nation(
        id=identifier, name=f"N{identifier}", population=population,
        stock={"food": food_reserve, "ore": 10, "tools": 5}, cash=500,
        productivity=1000, technology=1000, land=land, fertility=1000,
        ore_grade=1000, deposit=500, soil=1000,
    )


def rations(need, eaten):
    return {"food_need": need, "food_eaten": eaten}


class DemographyTests(unittest.TestCase):
    def test_rationing_changes_births_and_deaths(self):
        for eaten, births, deaths, closing in [(1000, 28, 12, 1016),
                                               (500, 14, 67, 947),
                                               (0, 0, 122, 878)]:
            with self.subTest(eaten=eaten):
                nation = country(1, 1000)
                row = develop([nation], {1: rations(1000, eaten)})["countries"][1]
                self.assertEqual((row["births"], row["deaths"]), (births, deaths))
                self.assertEqual(nation.population, closing)
                self.assertEqual(row["closing_population"], closing)

    def test_crowding_triggers_moves_capped_by_host_land(self):
        source = country(3, 400, land=1)
        host = country(9, 61, land=1, food_reserve=10)
        result = develop([source, host], {3: rations(400, 400), 9: rations(61, 61)})
        self.assertEqual(result["moves"], [{"source": 3, "target": 9, "people": 3}])
        self.assertEqual((source.population, host.population), (404, 65))

    def test_several_donors_cannot_spend_one_hosts_food_twice(self):
        def run(order):
            countries = {0: country(0, 600), 1: country(1, 600),
                         2: country(2, 10, food_reserve=55)}
            meals = {0: rations(600, 0), 1: rations(600, 0), 2: rations(10, 10)}
            before = {key: asdict(n) for key, n in countries.items()}
            outcome = develop([countries[key] for key in order], meals)
            for key, nation in countries.items():
                row = outcome["countries"][key]
                expected = before[key]["population"] + row["births"] - row["deaths"]
                expected += row["immigrants"] - row["emigrants"]
                self.assertEqual(nation.population, expected)
                self.assertEqual(asdict(nation), {**before[key], "population": expected})
            self.assertEqual(countries[2].population, 65)
            return outcome

        forward = run([0, 1, 2])
        self.assertEqual(forward, run([2, 1, 0]))
        self.assertEqual(forward["moves"], [
            {"source": 0, "target": 2, "people": 50},
            {"source": 1, "target": 2, "people": 5},
        ])

    def test_empty_settlement_accepts_arrivals_only_with_food_reserve(self):
        source = country(10, 120)
        empty = country(20, 0, food_reserve=4)
        unfunded = country(30, 0)
        result = develop([source, empty, unfunded], {
            10: rations(120, 0), 20: rations(0, 0), 30: rations(0, 0),
        })
        self.assertEqual(result["moves"], [{"source": 10, "target": 20, "people": 4}])
        self.assertEqual((empty.population, unfunded.population), (4, 0))
        self.assertEqual(result["countries"][20]["births"], 0)

    def test_one_source_can_fill_multiple_hosts_without_chained_migration(self):
        countries = [country(0, 120), country(1, 5, food_reserve=6),
                     country(2, 5, food_reserve=4)]
        rows = develop(countries, {0: rations(120, 0), 1: rations(5, 5), 2: rations(5, 5)})
        self.assertEqual(rows["moves"], [
            {"source": 0, "target": 1, "people": 6},
            {"source": 0, "target": 2, "people": 4},
        ])

    def test_invalid_inputs_cannot_partially_advance_population(self):
        for invalid in (rations(99, 99), rations(100, -1), rations(100, 101)):
            with self.subTest(invalid=invalid):
                countries = [country(0, 1000), country(1, 100)]
                with self.assertRaises(ValueError):
                    develop(countries, {0: rations(1000, 1000), 1: invalid})
                self.assertEqual([nation.population for nation in countries], [1000, 100])
