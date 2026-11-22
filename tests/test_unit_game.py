import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from civsim.unit_board import UnitBoard
from civsim.unit_game import load_board, save_board


def play(*args):
    return subprocess.run([sys.executable, "-B", "-X", "utf8", "-m", "civsim.unit_game", *map(str, args)],
                          capture_output=True, text=True, encoding="utf8")


class UnitGameCommandTests(unittest.TestCase):
    def test_published_saves_and_experiment_receipts_replay(self):
        examples = Path(__file__).resolve().parents[1] / "examples"
        slots = examples / "unit-board-checks"
        board = load_board(slots / "start.json")
        self.assertTrue(board.move(0, 1, 0, 1, 1)["ok"])
        self.assertEqual(board.snapshot(), load_board(slots / "moved.json").snapshot())
        board.next_turn()
        self.assertEqual(board.snapshot(), load_board(slots / "turn-2.json").snapshot())
        run = examples / "unit-board-v1"
        first = json.loads((run / "execution.json").read_bytes())
        replay = json.loads((run / "replay.json").read_bytes())
        self.assertEqual(first["science_sha256"], replay["science_sha256"])
        self.assertEqual(replay["byte_compared_files"], 4)
        for filename, expected in first["science_sha256"].items():
            self.assertEqual(hashlib.sha256((run / filename).read_bytes()).hexdigest(), expected, filename)

    def test_separate_processes_move_save_and_keep_the_destination_next_turn(self):
        with TemporaryDirectory() as root:
            initial, moved, next_turn = (Path(root) / name for name in ("1.json", "2.json", "3.json"))
            created = play("new", "--seed", 0, "--out", initial)
            self.assertEqual(created.returncode, 0, created.stderr)
            original = initial.read_bytes()
            command = play("move", initial, "--home", 0, "--affiliation", 1, "--from", 0,
                           "--to", 1, "--count", 1, "--out", moved)
            self.assertEqual(command.returncode, 0, command.stderr)
            receipt = json.loads(command.stdout)
            self.assertTrue(receipt["ok"])
            self.assertEqual((receipt["count"],receipt["food_spent"],receipt["road_used"]), (1,1,1))
            end = play("next", moved, "--out", next_turn)
            self.assertEqual(end.returncode, 0, end.stderr)
            shown = play("show", next_turn)
            self.assertEqual(shown.returncode, 0, shown.stderr)
            start, arrival, saved = (json.loads(p.read_bytes()) for p in (initial,moved,next_turn))
            self.assertEqual(json.loads(shown.stdout), saved)
            self.assertEqual(saved["positions"], arrival["positions"])
            self.assertNotEqual(saved["positions"], start["positions"])
            self.assertEqual(saved["turn"], start["turn"]+1)
            self.assertEqual(initial.read_bytes(), original)

    def test_rejected_action_cannot_write_a_child_save_or_replace_an_existing_save(self):
        with TemporaryDirectory() as root:
            path, child = Path(root)/"opening.json", Path(root)/"child.json"
            self.assertEqual(play("new", "--out", path).returncode, 0)
            before = path.read_bytes()
            rejected = play("move", path, "--home", 0, "--affiliation", 1, "--from", 0,
                            "--to", 1, "--count", 999999, "--out", child)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertFalse(json.loads(rejected.stdout)["ok"])
            self.assertFalse(child.exists())
            collision = play("next", path, "--out", path)
            self.assertNotEqual(collision.returncode, 0)
            self.assertEqual(path.read_bytes(), before)

    def test_one_token_cannot_move_on_an_empty_road_budget_or_empty_store(self):
        with TemporaryDirectory() as root:
            for food, remaining, reason in ((2, 0, "insufficient_capacity"), (0, 2, "insufficient_food")):
                with self.subTest(reason=reason):
                    path, child = Path(root)/f"{reason}.json", Path(root)/"after.json"
                    b = UnitBoard.create(population={0:12,1:10}, roster={(0,1):2},
                                         food={0:food,1:2}, edge=(0,1), capacity=2, remaining=remaining)
                    save_board(path, b)
                    before = path.read_bytes()
                    result = play("move", path, "--home", 0, "--affiliation", 1, "--from", 0,
                                  "--to", 1, "--count", 1, "--out", child)
                    receipt = json.loads(result.stdout)
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual((receipt["reason"], receipt["road_used"], receipt["food_spent"]), (reason,0,0))
                    self.assertFalse(child.exists())
                    self.assertEqual(path.read_bytes(), before)
