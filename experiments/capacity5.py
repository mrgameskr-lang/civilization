"""Reconstruct annual road capacity from the physical map, work receipts and manifests."""
from collections import Counter

from civsim.public_works import ROAD_BONUS, ROAD_LIMIT


def _require(ok, message):
    if not ok:
        raise ValueError("physical road audit: " + message)


class RoadCapacityAudit:
    """Begin with the unchanged map and no upgrades. Failed observations do not advance it."""

    def __init__(self, world):
        _require(world.year == 0, "start with the initial world")
        self.roads = {(r.a, r.b): r for r in world.roads}
        self.seats = {r.id: r.seat for r in world.regions}
        self.owners = {r.id: r.owner for r in world.regions}
        self.nations = tuple(n.id for n in world.nations)
        self.units = dict.fromkeys(self.roads, 0)
        self.year = 0

    def _loads(self, shipments):
        loads = Counter()
        for s in shipments:
            path = s["path"]
            qty = s["quantity"]
            _require(type(qty) is int and qty > 0 and path and s["source"] == path[0]
                     and s["target"] == path[-1] and len(path) == len(set(path)), "invalid cargo or route")
            _require(len(s["legs"]) == len(path) - 1 and path[0] in self.seats, "missing leg or station")
            tiles = [self.seats[path[0]]]
            for a, b, leg in zip(path[:-1], path[1:], s["legs"], strict=True):
                key = tuple(sorted((a, b)))
                _require(key in self.roads, "a shipment left the domestic road network")
                road = self.roads[key]
                expected = road.path if a == road.a else tuple(reversed(road.path))
                _require((leg["a"], leg["b"], leg["distance"]) == (a, b, road.distance), "wrong haul segment")
                tiles.extend(expected[1:])
                loads[key] += qty
            _require(s["tile_path"] == tiles and s["distance"] == len(tiles) - 1, "wrong physical path")
        return loads

    def observe(self, record):
        _require(record["year"] == self.year + 1, "out-of-order year")
        gov = record["government"]
        booked = {(r["a"], r["b"]): r for r in gov["roads"]}
        _require(self.roads.keys() == booked.keys() and len(booked) == len(gov["roads"]), "wrong road set")
        totals = {n: Counter(year_base_capacity=0, year_effective_capacity=0, next_year_effective_capacity=0,
                             opening_road_units=0, closing_road_units=0) for n in self.nations}
        repairs, builds = Counter(), Counter()
        for project in gov["works"]["projects"]:
            if project["action"] in ("build", "service"):
                edge = tuple(project["edge"])
                _require(edge in self.roads and set(edge) == {project["source"], project["target"]},
                         "project has no corresponding physical road")
                (repairs if project["action"] == "service" else builds)[edge] += 1
        works, relief, private = (self._loads(stage["shipments"])
                                  for stage in (gov["works"], gov["relief"], record["domestic"]))
        closing_units = {}
        for edge, road in self.roads.items():
            opening = self.units[edge]
            closing = repairs[edge] + builds[edge]
            _require(repairs[edge] <= opening and closing <= ROAD_LIMIT, "infeasible number of upgrades")
            current = road.capacity + opening * ROAD_BONUS
            following = road.capacity + closing * ROAD_BONUS
            unused = current - works[edge] - relief[edge] - private[edge]
            owner = self.owners[road.a]
            entries = booked[edge]
            expected = {"owner": owner, "base": road.capacity, "opening_units": opening,
                        "closing_units": closing, "capacity": current, "next_capacity": following,
                        "works_use": works[edge], "relief_use": relief[edge],
                        "private_use": private[edge], "unused": unused}
            _require(unused >= 0 and all(entries[k] == v for k, v in expected.items()),
                     f"road {edge} differs from map, project receipts or shipment legs")
            totals[owner].update(year_base_capacity=road.capacity, year_effective_capacity=current,
                                 next_year_effective_capacity=following, opening_road_units=opening,
                                 closing_road_units=closing)
            closing_units[edge] = closing
        for a in gov["accounts"]:
            t, checked = a["totals"], totals[a["id"]]
            for account_key, field in (("base_capacity", "year_base_capacity"),
                                       ("effective_capacity", "year_effective_capacity"),
                                       ("next_capacity", "next_year_effective_capacity")):
                _require(t[account_key] == checked[field], "country capacity differs from its roads")
        self.units = closing_units
        self.year = record["year"]
        return totals
