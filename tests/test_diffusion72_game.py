from contextlib import redirect_stdout
import io
import json
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from civsim.annual_game import create, load, main, play
from civsim.analysis import summary
from civsim.chronicle import Chronicle
from civsim.chronicle_event import resolve
from civsim.storage import canonical_line


class FarmKnowledgeGameTests(unittest.TestCase):
    def test_shipped_transfer_resolves_to_three_real_annual_ledgers(self):
        sample = Path(__file__).resolve().parents[1] / "examples/diffusion72"
        with self.assertRaisesRegex(ValueError, "civsim.annual_game show"):
            summary(sample / "seed2-year17.json")
        event = json.loads((sample / "seed2-region19.json").read_bytes())
        stages = {e["year"]: e for e in (event["contact"], event, event["application"])}

        class ReceiptCheck:
            def observe(observer, row):
                stage = stages.get(row["year"])
                if stage is None:
                    return
                self.assertEqual(sha256(canonical_line(row)).hexdigest(), stage["record_sha256"])
                for fact in stage["evidence"].values():
                    self.assertEqual(resolve(row, fact["pointer"]), fact["value"])

        book = Chronicle(2)
        _, game = load(sample / "seed2-year17.json", observers=(book, ReceiptCheck()))
        learned, = [e for e in book.report()["events"] if e["kind"] == "farm_tech_transfer"]
        self.assertEqual(event, learned)
        self.assertEqual(sorted(stages), [5, 16, 17])
        self.assertEqual(game.economy.world.year, 17)

    def test_cli_save_and_continue_with_existing_policies(self):
        with TemporaryDirectory() as directory, redirect_stdout(io.StringIO()) as out:
            start, first, second = [Path(directory) / name for name in ("start", "first", "second")]
            main(["new", "--seed", "0", "--out", str(start)])
            main(["step", str(start), "--research", "--diffusion", "--upkeep", "0", "1",
                  "--reserve-policy", "7-day", "--out", str(first)])
            main(["step", str(first), "--out", str(second)])
            main(["show", str(second)])
            state = json.loads(out.getvalue().splitlines()[-1])
            slot = json.loads(second.read_bytes())
            self.assertEqual((slot["schema"], state["year"]), ("annual-game/6", 2))
            self.assertEqual(state["diffusion"], slot["diffusion"])
            self.assertTrue(slot["diffusion"])
            self.assertEqual(state["reserve_policy"], "7-day")
            self.assertIsNotNone(state["game_upkeep"])
            for forged in ({**slot, "diffusion": None}, {**slot, "diffusion": []},
                           {k: v for k, v in slot.items() if k != "diffusion"},
                           {k: ("annual-game/5" if k == "schema" else v)
                            for k, v in slot.items() if k != "diffusion"}):
                second.write_text(json.dumps(forged), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load(second)

    def test_explicit_off_is_identical_to_previous_rules_with_or_without_research(self):
        for research in (False, True):
            order = {"move": None, "research": research}
            self.assertEqual(canonical_line(play(create(20), order)),
                             canonical_line(play(create(20), {**order, "diffusion": False})))

    def test_invalid_commands_have_no_side_effects(self):
        game = create(0)
        orders = [{"diffusion": value} for value in (None, 0, 1, "yes", True)]
        orders += [{"research": True, "diffusion": True, "blocked_migration": edge}
                   for edge in (None, [True, 1], [1], [3, 3], [2, 1], [0, 999999])]
        for order in orders:
            with self.subTest(order=order), self.assertRaises(ValueError):
                play(game, {"move": None, **order})
            self.assertEqual(game.economy.world.year, 0)
            self.assertIsNone(game.economy.research)
            self.assertIsNone(game.economy.diffusion)
