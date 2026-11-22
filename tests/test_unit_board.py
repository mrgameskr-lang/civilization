"""Player moves on a two-square board, including exact restoration after play."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import unittest

from civsim.unit_board import UnitBoard


def game(**changes):
    options = dict(population={3:20, 7:8}, roster={(3,90):6, (3,7):2, (7,90):4},
                   food={3:6, 7:3}, edge=(7,3), capacity=5)
    options.update(changes)
    return UnitBoard.create(**options)


class BoardTests(unittest.TestCase):
    def test_flat_crossing_cost_and_rejection_order(self):
        from civsim.unit_board import assess_crossing

        cases = [
            (0, 0, 0, 0, ('invalid_count', 0, 0)),
            (True, 1, 1, 1, ('invalid_count', 0, 0)),
            (3, 2, 0, 0, ('insufficient_tokens', 0, 0)),
            (3, 3, 2, 1, ('insufficient_food', 0, 0)),
            (3, 3, 3, 2, ('insufficient_capacity', 0, 0)),
            (3, 3, 3, 3, ('moved', 3, 3)),
        ]
        for count,tokens,food,left,want in cases:
            with self.subTest(count=count,tokens=tokens,food=food,remaining=left):
                self.assertEqual(assess_crossing(count=count,tokens=tokens,food=food,remaining=left),want)
        for field in ('tokens','food','remaining'):
            values = dict(count=1,tokens=1,food=1,remaining=1)
            for invalid in (False,-1,2.0):
                with self.subTest(field=field,invalid=invalid), self.assertRaises(ValueError):
                    assess_crossing(**{**values,field:invalid})
        self.assertEqual(game().move(99,False,2,2,0)['reason'],'invalid_count')

    def test_published_idle_and_moved_snapshots_remain_compatible(self):
        from civsim.storage import canonical_line
        from civsim.unit_board_scenario import demo_board

        archived = Path(__file__).resolve().parents[1] / 'examples' / 'unit-board-checks'
        gold = {
            'start':'555e22eacfefe2eed4a02b7bbf48d6d5cf02b4a1607ad4198e9bcb40d5b93e9e',
            'moved':'fa7211993c1ca275643a625250f49b541c2a1d3ee267586aee6d1f43a75dcd2e',
            'turn-2':'e1dfd1eeb184c82ddba65583e9158d6986ffeb5923e7d0f4434347d6904cd9c9',
        }
        board = demo_board(0)
        for step,digest in gold.items():
            if step == 'moved':
                self.assertTrue(board.move(0,1,0,1,1)['ok'])
            elif step == 'turn-2':
                board.next_turn()
            original = json.loads((archived / (step + '.json')).read_bytes())
            reconstructed = UnitBoard.restore(original).snapshot()
            self.assertEqual(reconstructed,original)
            self.assertEqual(board.snapshot(),original)
            self.assertEqual(sha256(canonical_line(reconstructed)).hexdigest(),digest)

    def test_external_and_neighbor_affiliations_are_labels_and_start_at_home(self):
        b = game()
        self.assertEqual(b.edge, (3,7))
        self.assertEqual(b.population, {3:20,7:8})
        self.assertEqual(b.positions, {(3,90,3):6,(3,7,3):2,(7,90,7):4})
        self.assertEqual(sum(b.positions.values()), sum(b.roster.values()))
        self.assertEqual((b.turn,b.capacity,b.remaining), (1,5,5))

    def test_split_a_group_expense_at_source_only_and_one_charge_per_crossing(self):
        b = game()
        result = b.move(3,90,3,7,3)
        self.assertEqual(result, dict(ok=True, reason='moved',turn=1,home=3,affiliation=90,
                                     source=3,destination=7,count=3,food_spent=3,road_used=3))
        self.assertEqual(b.positions, {(3,90,3):3,(3,90,7):3,(3,7,3):2,(7,90,7):4})
        self.assertEqual((b.food,b.remaining),({3:3,7:3},2))
        self.assertTrue(b.move(3,90,7,3,2)['ok'])
        self.assertEqual((b.food,b.remaining),({3:3,7:1},0))
        self.assertEqual(b.positions[3,90,7],1)
        self.assertEqual((sum(b.population.values()),sum(b.positions.values())),(28,12))

    def test_failures_are_atomic_and_emit_stable_reasons(self):
        cases=[((3,90,3,7,0),'invalid_count'),((3,90,3,7,True),'invalid_count'),
               ((3,False,3,7,1),'invalid_key'),((3,50,3,7,1),'unknown_group'),
               ((3,90,3,3,1),'invalid_edge'),((3,90,3,90,1),'invalid_edge'),
               ((3,90,7,3,1),'insufficient_tokens'),((3,7,3,7,3),'insufficient_tokens')]
        for args,reason in cases:
            with self.subTest(reason=reason,args=args):
                b=game(); before=b.snapshot()
                receipt=b.move(*args)
                self.assertEqual((receipt['ok'],receipt['reason'],receipt['food_spent'],receipt['road_used']),
                                 (False,reason,0,0))
                self.assertEqual(b.snapshot(),before)
        for kw,reason in [(dict(food={3:1,7:5}),'insufficient_food'),
                          (dict(remaining=1),'insufficient_capacity')]:
            b=game(**kw); before=b.snapshot()
            self.assertEqual(b.move(3,90,3,7,2)['reason'],reason)
            self.assertEqual(b.snapshot(),before)

    def test_turns_refill_only_edge_capacity_no_auto_return_or_refund(self):
        b=game(remaining=1,turn=7)
        b.move(3,90,3,7,1)
        people,food=b.positions,b.food
        self.assertIs(b.next_turn(),b)
        self.assertEqual((b.turn,b.remaining,b.food,b.positions),(8,5,food,people))
        self.assertTrue(b.move(7,90,7,3,3)['ok'])
        b.next_turn()
        self.assertEqual((b.remaining,b.food),(5,{3:5,7:0}))
        self.assertEqual((b.positions[3,90,7],b.positions[7,90,3]),(1,3))

    def test_restore_checks_balances_positions_and_ordered_history(self):
        b=game(remaining=3)
        b.move(3,90,3,7,3)
        b.next_turn()
        b.move(3,90,7,3,1)
        s=json.loads(json.dumps(b.snapshot()))
        self.assertEqual(UnitBoard.restore(s).snapshot(),s)
        for change in ('food','food_spent','position','left','initial_remaining','turn',
                       'source','count','duplicate_position','duplicate_roster','foreign','bool','extra'):
            with self.subTest(change=change):
                bad=deepcopy(s)
                if change=='food': bad['nodes'][0]['food']+=1
                if change=='food_spent': bad['nodes'][0]['food_spent']-=1
                if change=='position': bad['positions'][0]['count']+=1
                if change=='left': bad['remaining']-=1
                if change=='initial_remaining': bad['initial_remaining']=2
                if change=='turn': bad['moves'][0]['turn']=3
                if change=='source': bad['moves'][0]['source']=7
                if change=='count': bad['moves'][0]['count']+=1
                if change=='duplicate_position': bad['positions'].append(bad['positions'][0])
                if change=='duplicate_roster': bad['roster'].append(bad['roster'][0])
                if change=='foreign': bad['positions'][0]['location']=90
                if change=='bool': bad['nodes'][1]['food_spent']=True
                if change=='extra': bad['income']=17
                with self.assertRaises(ValueError):
                    UnitBoard.restore(bad)

    def test_defensive_copies_and_create_preconditions(self):
        source={(3,90):2}
        funds={3:2,7:0}
        b=game(roster=source,food=funds)
        before=b.snapshot()
        funds[3]=999
        source.clear()
        b.positions.clear()
        b.roster.clear()
        b.food.clear()
        b.population.clear()
        copied=b.snapshot()
        copied['nodes'][0]['food']=999
        self.assertEqual(b.snapshot(),before)
        for kw in (dict(population={3:4}),dict(food={3:0,7:-1}),dict(roster={(3,90):21}),
                   dict(roster={(3,90):15,(3,4):6}),dict(roster={(90,3):1}),
                   dict(edge=(3,3)),dict(capacity=False),dict(remaining=6),dict(turn=0)):
            with self.subTest(kw=kw),self.assertRaises(ValueError):
                game(**kw)

    def test_empty_register_zero_food_and_zero_capacity_can_wait_indefinitely(self):
        b=game(roster={},food={3:0,7:0},capacity=0,turn=21)
        b.next_turn().next_turn()
        self.assertEqual((b.turn,b.food,b.remaining,b.positions),(23,{3:0,7:0},0,{}))
        self.assertEqual(UnitBoard.restore(b.snapshot()).snapshot(),b.snapshot())

    def test_received_tokens_do_not_change_residency_or_issue_new_food(self):
        b=game(population={3:2,7:0},roster={(3,41):2},food={3:2,7:0},capacity=2)
        receipt=b.move(3,41,3,7,2)
        self.assertEqual((b.population,b.positions,b.food),({3:2,7:0},{(3,41,7):2},{3:0,7:0}))
        receipt['count']=100
        snap=b.snapshot()
        clone=UnitBoard.restore(snap)
        snap['moves'][0]['count']=200
        self.assertEqual(clone.snapshot(),b.snapshot())
        clone.next_turn()
        self.assertEqual(clone.move(3,41,7,3,1)['reason'],'insufficient_food')
        self.assertEqual(b.turn,1)

    def test_shared_capacity_is_not_oversold_by_concurrent_opposite_moves(self):
        from concurrent.futures import ThreadPoolExecutor
        b=game(capacity=1)
        requests=[(3,90,3,7,1),(7,90,7,3,1)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda args:b.move(*args),requests))
        self.assertCountEqual([r['reason'] for r in results],['moved','insufficient_capacity'])
        self.assertEqual((b.remaining,sum(b.food.values()),sum(b.positions.values())),(0,8,12))
        self.assertEqual(UnitBoard.restore(b.snapshot()).snapshot(),b.snapshot())
