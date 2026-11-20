import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from civsim.engine import step
from civsim.model import generate_world
from experiments.decision31 import CONTROL, first_choice, eligible_actions, run
from experiments.publication import publish_file


class ForkedChoiceTests(unittest.TestCase):
    def test_failed_write_leaves_no_partial_csv(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp, "branches.csv")
            with patch("experiments.decision31._case", return_value=None), \
                    patch("csv.DictWriter.writerows", side_effect=OSError("full disk")):
                with self.assertRaises(OSError):
                    run(target)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_publication_cannot_replace_a_concurrently_created_csv(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp, "branches.csv")

            def concurrent_writer(source, destination):
                target.write_bytes(b"winner")
                publish_file(source, destination)

            with patch("experiments.decision31._case", return_value=None), \
                    patch("experiments.decision31.publish_file", side_effect=concurrent_writer):
                with self.assertRaises(FileExistsError):
                    run(target)
            self.assertEqual(target.read_bytes(), b"winner")
            self.assertEqual(list(Path(tmp).iterdir()), [target])

    def test_defer_and_real_project_pay_exactly_their_own_costs(self):
        source = generate_world(3, 5, 1, 1)
        n = source.nations[0]
        n.population, n.soil, n.productivity, n.technology = 1000, 1000, 1000, 1000
        n.fertility, n.stock = 1000, {"food": 0, "ore": 80, "tools": 100}
        natural = step(replace(source), 1, CONTROL)
        plan = natural["countries"][0]["production"]["investment"]
        self.assertIn("land", eligible_actions(plan))
        self.assertNotIn("industry", eligible_actions(plan))
        with self.assertRaisesRegex(ValueError, "ineligible"):
            first_choice(replace(source), 0, "industry", plan)
        deferred = first_choice(replace(source), 0, "defer", plan)
        reclaimed = first_choice(replace(source), 0, "land", plan)
        for record, used in [(deferred, (0, 0, 0)), (reclaimed, (10, 6, 12))]:
            trial = record["countries"][0]["production"]["investment"]
            self.assertEqual((trial["build_used"]["tools"], trial["build_used"]["ore"],
                              trial["construction_labor"]), used)
        self.assertEqual(source.year, 0)
        self.assertEqual(n.stock["ore"], 80)
