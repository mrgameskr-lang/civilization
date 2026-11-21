import tempfile
import unittest
from pathlib import Path

from experiments.unit_board_trials import sample_board, play_move, production_pool, restored_next_turn, zero_maximum


class TwoSpaceGameTests(unittest.TestCase):
    def test_move_changes_only_the_location_of_the_selected_tokens(self):
        b=sample_board()
        before=(b.population,b.roster)
        workers=production_pool(b.snapshot())
        outcome=play_move(b,2)
        self.assertTrue(outcome["ok"])
        self.assertEqual(before,(b.population,b.roster))
        self.assertEqual(workers,production_pool(b.snapshot()))
        self.assertEqual((b.positions[0,1,0],b.positions[0,1,1]),(1,2))

    def test_charge_and_shared_turn_limit_are_exactly_once_per_moved_token(self):
        b=sample_board()
        points=b.food.copy()
        capacity=b.remaining
        receipt=play_move(b,2)
        self.assertEqual((receipt["food_spent"],receipt["road_used"]),(2,2))
        self.assertEqual((points[0]-b.food[0],capacity-b.remaining),(2,2))
        self.assertEqual(b.food[1],points[1])
        self.assertEqual(len(b.snapshot()["moves"]),1)

    def test_next_turn_retains_the_destination_and_resets_only_the_turn_limit(self):
        b=sample_board()
        play_move(b,2)
        end=b.snapshot()
        b.next_turn()
        self.assertEqual(b.turn,end["turn"]+1)
        self.assertEqual(b.positions[0,1,1],2)
        self.assertEqual(b.remaining,b.capacity)
        again=b.snapshot()
        self.assertEqual(again["nodes"],end["nodes"])
        self.assertEqual(again["moves"],end["moves"])

    def test_zero_source_points_rejects_the_whole_move(self):
        b=sample_board(food=0)
        before=b.snapshot()
        receipt=play_move(b,2)
        self.assertEqual((receipt["ok"],receipt["reason"]),(False,"insufficient_food"))
        self.assertEqual(b.snapshot(),before)

    def test_zero_turn_capacity_rejects_the_whole_move(self):
        b=sample_board(remaining=0)
        before=b.snapshot()
        receipt=play_move(b,2)
        self.assertEqual((receipt["ok"],receipt["reason"]),(False,"insufficient_capacity"))
        self.assertEqual(b.snapshot(),before)
        absolute=zero_maximum()
        self.assertEqual(absolute["opening"]["capacity"],0)
        self.assertEqual(absolute["after"],absolute["opening"])
        self.assertEqual(absolute["next_turn"]["remaining"],0)

    def test_saved_board_loads_in_a_fresh_python_process_with_the_same_next_turn(self):
        b=sample_board()
        play_move(b,2)
        before=b.snapshot()
        with tempfile.TemporaryDirectory() as t:
            fresh=restored_next_turn(before,Path(t))
        self.assertEqual(fresh["loaded"],before)
        b.next_turn()
        self.assertEqual(fresh["next_turn"],b.snapshot())
