import json
import unittest
from copy import deepcopy
from types import SimpleNamespace

from civsim.logistics import audit_logistics, ship


def node(i, population, food, *, ore=0, tools=0, owner=0, seat=None, members=None):
    seat = i if seat is None else seat
    return SimpleNamespace(id=i, population=population, owner=owner, cash=8,
                           stock={"food": food, "ore": ore, "tools": tools},
                           seat=seat, members=(seat,) if members is None else tuple(members))


def road(a, b, capacity, *tiles):
    return SimpleNamespace(a=a, b=b, capacity=capacity, distance=len(tiles) - 1, path=tiles)


class DomesticLogisticsTests(unittest.TestCase):
    def test_real_seeded_map_respects_ownership_geometry_and_input_order(self):
        from civsim.model import generate_world
        from civsim.regions import regionalize

        world = regionalize(generate_world(42))
        forward = deepcopy(world.regions)
        backward = list(reversed(deepcopy(world.regions)))
        for r in forward + backward:
            r.stock["food"] = r.population
        edge = next(e for e in world.roads if e.capacity > 0)
        for regions in (forward, backward):
            by_id = {r.id: r for r in regions}
            by_id[edge.a].stock["food"] += 200
            by_id[edge.b].stock["food"] -= 100
        opening = deepcopy(forward)
        trace = ship(forward, world.roads, width=world.width)
        self.assertGreater(trace["delivered"]["food"], 0)
        self.assertEqual(trace, ship(backward, reversed(world.roads), width=world.width))
        audit_logistics(opening, world.roads, trace, width=world.width)
        self.assertEqual([r.cash for r in opening], [r.cash for r in forward])

    def test_multihop_bottleneck_charges_each_leg_and_leaves_no_goods_at_transit(self):
        regions = [node(0, 10, 30), node(1, 0, 0), node(2, 10, 0)]
        roads = [road(0, 1, 10, 0, 1), road(1, 2, 5, 1, 2)]
        opening = deepcopy(regions)
        t = ship(regions, roads, width=3)
        audit_logistics(opening, roads, json.loads(json.dumps(t)), width=3)
        self.assertEqual([r.stock["food"] for r in regions], [23, 0, 5])
        self.assertEqual(t["shipments"][0]["path"], [0, 1, 2])
        self.assertEqual(t["shipments"][0]["tile_path"], [0, 1, 2])
        self.assertEqual(t["nodes"][1]["transit"]["food"], 5)
        self.assertEqual(t["cost_food"], 2)
        self.assertEqual([r["remaining"] for r in t["roads"]], [5, 0])

    def test_closed_or_missing_bridge_blocks_cargo(self):
        for roads in [[road(0, 1, 0, 0, 1)], []]:
            regions = [node(0, 10, 30), node(1, 10, 0)]
            t = ship(regions, roads, width=2)
            self.assertEqual(t["shipments"], [])
            self.assertEqual(t["nodes"][1]["unmet_after"]["food"], 10)

    def test_food_gets_first_claim_then_other_goods_share_capacity_in_both_directions(self):
        regions = [node(0, 100, 125, ore=30), node(1, 100, 97)]
        t = ship(regions, [road(0, 1, 5, 0, 1)], width=2)
        self.assertEqual([(s["good"], s["quantity"]) for s in t["shipments"]], [("food", 3), ("ore", 2)])
        regions = [node(0, 80, 100, ore=20), node(1, 80, 100, tools=20)]
        t = ship(regions, [road(0, 1, 5, 0, 1)], width=2)
        self.assertEqual([(s["source"], s["target"], s["good"], s["quantity"]) for s in t["shipments"]],
                         [(0, 1, "ore", 4), (1, 0, "tools", 1)])
        self.assertEqual(t["roads"][0]["used"], 5)

    def test_saturated_short_path_is_rerouted_through_second_physical_route(self):
        regions = [node(0, 20, 70), node(1, 0, 0), node(2, 0, 0), node(3, 20, 0)]
        roads = [road(0, 1, 4, 0, 1), road(1, 3, 4, 1, 3),
                 road(0, 2, 20, 0, 2), road(2, 3, 20, 2, 3)]
        t = ship(regions, roads, width=2)
        self.assertEqual([(s["path"], s["quantity"]) for s in t["shipments"]],
                         [([0, 1, 3], 4), ([0, 2, 3], 16)])
        self.assertEqual(regions[3].stock["food"], 20)

    def test_freight_respects_sender_meals_and_large_capacity_matches_unlimited(self):
        initial = [node(0, 10, 16, ore=90), node(1, 100, 90)]
        outcomes = []
        for mode in ("limited", "unlimited"):
            regions = deepcopy(initial)
            t = ship(regions, [road(0, 1, 5000, 0, 1)], mode, width=2)
            self.assertEqual(regions[0].stock, {"food": 10, "ore": 90, "tools": 0})
            self.assertEqual(regions[1].stock["food"], 95)
            outcomes.append(t["shipments"])
        self.assertEqual(*outcomes)

    def test_extra_capacity_can_increase_shortfall_when_first_buyer_is_farther(self):
        # Same initial shortfall in both markets. Region 0 wins the ID tiebreak.
        initial = [node(0, 100, 0, seat=0, members=range(100)),
                   node(1, 100, 0, seat=101), node(2, 1, 102, seat=100)]
        totals = []
        for cap in (1, 100):
            roads = [road(0, 2, cap, *range(101)), road(1, 2, 100, 101, 100)]
            t = ship(deepcopy(initial), roads, width=102)
            totals.append((t["delivered"]["food"], t["cost_food"]))
        self.assertEqual(totals, [(99, 2), (50, 50)])

    def test_invalid_geometry_foreign_road_and_tampered_postings_are_rejected(self):
        regions = [node(0, 10, 30), node(1, 10, 0)]
        roads = [road(0, 1, 10, 0, 1)]
        original = deepcopy(regions)
        for bad in (road(0, 1, 3, 0, 2), road(0, 1, 3, 0, 1, 0, 1)):
            with self.assertRaises(ValueError):
                ship(regions, [bad], width=2)
            self.assertEqual(regions, original)
        foreign = deepcopy(regions)
        foreign[1].owner = 1
        with self.assertRaises(ValueError):
            ship(foreign, roads, width=2)
        t = ship(regions, roads, width=2)
        for field in ("cost_food", "distance", "tile_path", "quantity", "leg_cost", "capacity", "node"):
            altered = deepcopy(t)
            s = altered["shipments"][0]
            if field == "tile_path":
                s[field] = [0, 3]
            elif field == "leg_cost":
                s["legs"][0]["cost_food"] = 0
            elif field == "capacity":
                altered["roads"][0]["remaining"] += 1
            elif field == "node":
                altered["nodes"][0]["closing"]["food"] += 1
            else:
                s[field] += 1
            with self.subTest(field=field), self.assertRaises(ValueError):
                audit_logistics(original, roads, altered, width=2)
