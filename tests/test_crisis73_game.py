from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from civsim.analysis import summary
from civsim.annual_game import create, load, main, play
from civsim.storage import canonical_line


class BorderCrisisGameTests(unittest.TestCase):
    def test_new_save_replays_and_checks_memory_with_or_without_other_options(self):
        for extra in ([], ["--research", "--diffusion", "--reserve-policy", "emergency", "--upkeep", "0", "1"]):
            with self.subTest(extra=extra), TemporaryDirectory() as folder, redirect_stdout(io.StringIO()) as out:
                start, first, held = [Path(folder) / name for name in ("start", "first", "held")]
                main(["new", "--seed", "0", "--out", str(start)])
                main(["step", str(start), "--crisis", *extra, "--out", str(first)])
                main(["step", str(first), "--hold-response", "--out", str(held)])
                main(["show", str(held)])
                shown = json.loads(out.getvalue().splitlines()[-1])
                slot = json.loads(held.read_bytes())
                self.assertEqual(slot["schema"], "annual-game/7")
                self.assertIsNotNone(slot["crisis"])
                self.assertEqual(shown["crisis"], slot["crisis"])
                self.assertEqual(slot["journal"]["turns"][1]["command"], {"move": None, "hold_response": True})
                with self.assertRaisesRegex(ValueError, "civsim.annual_game show"):
                    summary(held)
                old_version = "annual-game/6" if extra else "annual-game/1"
                incomplete = {k:v for k,v in slot.items() if k != "crisis"}
                for forged in (incomplete, {**slot, "crisis": None}, {**incomplete, "schema": old_version}):
                    held.write_text(json.dumps(forged), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        load(held)

    def test_explicit_opt_out_keeps_original_annual_ledger(self):
        legacy, off = create(20), create(20)
        for command in ({"move": None, "research": True, "diffusion": True},
                        {"move": None, "reserve_policy": "emergency", "public_farm": True}):
            self.assertEqual(canonical_line(play(legacy, command)),
                             canonical_line(play(off, {**command, "crisis": False})))

    def test_invalid_or_inactive_diagnostics_cannot_advance_year(self):
        game = create(1)
        for invalid in ({"crisis": 0}, {"crisis": None}, {"hold_response": 1},
                        {"crisis": "yes"}, {"hold_response": True}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                play(game, {"move": None, **invalid})
            self.assertEqual(game.economy.world.year, 0)
        play(game, {"move": None, "crisis": True})
        with self.assertRaises(ValueError):
            play(game, {"move": None, "crisis": False})
        self.assertEqual(game.economy.world.year, 1)
