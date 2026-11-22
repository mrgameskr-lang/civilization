from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from civsim.annual_game import create, load, main, play, save
from civsim.chronicle import Chronicle
from civsim.game_journal import append_turn, new_journal
from civsim.storage import canonical_line


class ResearchSaveTests(unittest.TestCase):
    def test_shipped_save_links_the_paid_acquisition_to_next_years_actual_crop(self):
        path = Path(__file__).resolve().parents[1] / "examples/research71/seed0-year6.json"
        observer = Chronicle(0)
        journal, game = load(path, observer=observer)
        milestone, = [e for e in observer.report()["events"] if e["kind"] == "farm_tech_adoption"]
        self.assertEqual((milestone["year"], milestone["region"]), (5, 28))
        self.assertEqual(milestone["record_sha256"], journal["turns"][4]["record_sha256"])
        self.assertEqual([milestone["evidence"][k]["value"] for k in
                          ("cumulative_workers", "cumulative_ore", "cumulative_tools")], [4, 2, 2])
        proof = milestone["application"]
        self.assertEqual((proof["year"], proof["record_sha256"]), (6, journal["turns"][5]["record_sha256"]))
        self.assertEqual(proof["evidence"]["food_produced"]["value"], 7248)
        self.assertEqual(next(r for r in game.economy.research if r["id"] == 28)["trials"], 2)

    def test_opt_in_survives_save_and_replay_with_existing_food_policies(self):
        for extra in ({}, {"public_farm": True, "reserve_policy": "emergency"}):
            with self.subTest(extra=extra), TemporaryDirectory() as directory:
                game, journal = create(0), new_journal(0)
                for order in (None, {"move": None, "research": True, **extra}, None):
                    record = play(game, order)
                    journal = append_turn(journal, order, record)
                slot = Path(directory) / "turn3.json"
                save(slot, journal, game.away, public_farm=game.economy.public_farm,
                     reserve_policy=game.economy.reserve_policy, research=game.economy.research)
                content = json.loads(slot.read_bytes())
                self.assertEqual(content["schema"], "annual-game/5")
                self.assertEqual(content["research"], game.economy.research)
                self.assertIn("research", record)
                _, replay = load(slot)
                self.assertEqual(play(game, None), play(replay, None))
                for replacement in ([], None, 7):
                    with self.subTest(replacement=replacement):
                        slot.write_text(json.dumps({**content, "research": replacement}), encoding="utf-8")
                        with self.assertRaises(ValueError):
                            load(slot)

    def test_legacy_mode_and_rejected_orders_have_no_side_effects(self):
        control, game = create(20), create(20)
        self.assertEqual(canonical_line(play(control, None)),
                         canonical_line(play(game, {"move": None, "research": False})))
        for invalid in (0, 1, None, [], "on"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                play(game, {"move": None, "research": invalid})
        self.assertEqual(game.economy.world.year, 1)
        play(game, {"move": None, "research": True})
        before = deepcopy(game.economy.research)
        with self.assertRaises(ValueError):
            play(game, {"move": None, "research": False})
        self.assertEqual((game.economy.world.year, game.economy.research), (2, before))

    def test_cli_activation_composes_with_existing_options(self):
        with TemporaryDirectory() as directory, redirect_stdout(io.StringIO()) as out:
            a, b = (Path(directory) / name for name in ("initial.json", "next.json"))
            main(["new", "--seed", "0", "--out", str(a)])
            main(["step", str(a), "--research", "--reserve-policy", "7-day", "--out", str(b)])
            main(["show", str(b)])
            closed = json.loads(out.getvalue().splitlines()[-1])
            self.assertEqual(closed["year"], 1)
            self.assertEqual(closed["reserve_policy"], "7-day")
            self.assertEqual(closed["research"], json.loads(b.read_bytes())["research"])
