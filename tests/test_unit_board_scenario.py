"""The two-village festival starts with pre-registered resident volunteers."""
import json
import unittest

from civsim.unit_board_scenario import demo_board, production_pool


class FestivalScenarioTests(unittest.TestCase):
    def test_volunteering_is_counted_once_per_home_after_move_and_reload(self):
        board = demo_board()
        resident_totals = {0: 12, 1: 10}
        self.assertEqual(board.population, resident_totals)
        self.assertEqual(board.positions, {(0, 0, 0): 1, (0, 1, 0): 2,
                                           (1, 0, 1): 1, (1, 1, 1): 1})
        self.assertEqual(production_pool(board), {0: 9, 1: 8})
        self.assertEqual(board.food, {0: 2, 1: 2})
        receipt = board.move(0, 1, 0, 1, 1)
        self.assertTrue(receipt['ok'])
        self.assertEqual((receipt['food_spent'], receipt['road_used']), (1, 1))
        self.assertEqual((board.food, board.remaining), ({0: 1, 1: 2}, 1))
        board.next_turn()
        restored = type(board).restore(json.loads(json.dumps(board.snapshot())))
        self.assertEqual(restored.positions[0, 1, 1], 1)
        self.assertEqual(restored.population, resident_totals)
        self.assertEqual(production_pool(restored), {0: 9, 1: 8})
        self.assertEqual(sum(restored.positions.values()) + sum(production_pool(restored).values()), 22)

    def test_all_forty_layouts_replay_without_sharing_changed_food_or_positions(self):
        layouts = set()
        for seed in range(40):
            with self.subTest(seed=seed):
                first, replay = demo_board(seed), demo_board(seed)
                opening = first.snapshot()
                layouts.add(tuple(first.food[home] for home in (0, 1)))
                self.assertEqual(replay.snapshot(), opening)
                self.assertTrue(first.move(0, 1, 0, 1, 1)['ok'])
                self.assertEqual(replay.snapshot(), opening)
        self.assertEqual(len(layouts), 40)

    def test_seed_is_a_nonnegative_integer(self):
        for seed in (True, 0.5, '0', -1):
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                demo_board(seed)
