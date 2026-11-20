import random
import unittest
from collections import deque
from dataclasses import asdict

from civsim.model import GOODS, climate_factor, generate_world


class WorldTests(unittest.TestCase):
    def test_default_map_aggregates_tile_resources_exactly(self):
        world = generate_world(17)
        self.assertEqual((world.width, world.height, len(world.nations)), (48, 32, 8))
        self.assertEqual([n.id for n in world.nations], list(range(8)))
        coordinates = [(t.x, t.y) for t in world.tiles]
        self.assertEqual(coordinates, [(x, y) for y in range(32) for x in range(48)])
        for n in world.nations:
            region = [tile for tile in world.tiles if tile.owner == n.id]
            self.assertEqual(n.land, len(region))
            self.assertEqual(n.fertility, sum(t.fertility for t in region) // n.land)
            self.assertEqual(n.ore_grade, sum(t.ore_grade for t in region) // n.land)
            self.assertEqual(n.deposit, sum(t.deposit for t in region))
            self.assertEqual(set(n.stock), set(GOODS))
            self.assertTrue(all(isinstance(q, int) and q >= 0 for q in n.stock.values()))
        for field in ("population", "productivity", "technology", "fertility", "ore_grade"):
            self.assertGreater(len({getattr(n, field) for n in world.nations}), 1)

    def test_partition_is_complete_and_each_territory_is_connected(self):
        for width, height, nations in [(1, 1, 1), (1, 7, 5), (3, 3, 8), (47, 31, 7),
                                       (96, 64, 32), (2, 13, 26)]:
            with self.subTest(width=width, height=height, nations=nations):
                world = generate_world(-8, width=width, height=height, nations=nations)
                regions = [set() for _ in range(nations)]
                for t in world.tiles:
                    regions[t.owner].add((t.x, t.y))
                self.assertEqual(sum(map(len, regions)), width * height)
                for region in regions:
                    self.assertTrue(region)
                    frontier = deque([next(iter(region))])
                    reached = set(frontier)
                    while frontier:
                        x, y = frontier.popleft()
                        for neighbor in ((x-1, y), (x+1, y), (x, y-1), (x, y+1)):
                            if neighbor in region and neighbor not in reached:
                                reached.add(neighbor)
                                frontier.append(neighbor)
                    self.assertEqual(reached, region)

    def test_replay_is_independent_of_global_random_state_and_mutations(self):
        state = random.getstate()
        try:
            random.seed(9)
            first = generate_world(38, 8, 6, 3)
            random.seed(299)
            second = generate_world(38, 8, 6, 3)
        finally:
            random.setstate(state)
        self.assertEqual(asdict(first), asdict(second))
        self.assertNotEqual(first.tiles, generate_world(39, 8, 6, 3).tiles)
        first.nations[0].stock["food"] += 1
        self.assertNotEqual(first.nations[0].stock, second.nations[0].stock)

    def test_invalid_map_sizes_are_rejected(self):
        for args in [(0, 2, 1), (3, -2, 1), (1, 1, 2), (3, 3, 0), (2.5, 1, 1)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                generate_world(1, *args)

    def test_rainfall_is_bounded_smooth_with_distinct_local_cycles(self):
        def series(seed, region):
            return [climate_factor(seed, year, region) for year in range(1, 201)]

        baseline = series(12, 0)
        self.assertEqual(baseline, series(12, 0))
        self.assertNotEqual(baseline, series(12, 1))
        self.assertNotEqual(baseline, series(13, 0))
        self.assertTrue(all(isinstance(q, int) and 800 <= q <= 1200 for q in baseline))
        self.assertTrue(all(abs(a-b) <= 65 for a, b in zip(baseline, baseline[1:])))
        self.assertGreater(max(baseline) - min(baseline), 150)
