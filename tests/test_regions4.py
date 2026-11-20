import unittest
from copy import deepcopy
from dataclasses import replace

from civsim.investment import prepare
from civsim.model import GOODS, generate_world
from civsim.regions import audit_geography, audit_regions, regionalize, sync_nations


class RegionalAccountsTests(unittest.TestCase):
    def test_cold_start_exact_national_counts_assets_and_independent_accounts(self):
        original = generate_world(42)
        old = deepcopy(original)
        world = regionalize(original)
        self.assertEqual(len(world.regions), 32)
        self.assertEqual(regionalize(original), world)
        self.assertEqual(original, old)
        for nation, prior in zip(world.nations, original.nations):
            regions = [r for r in world.regions if r.owner == nation.id]
            self.assertEqual(len(regions), 4)
            for field in ("cash", "population", "land", "deposit"):
                self.assertEqual(sum(getattr(r, field) for r in regions), getattr(prior, field))
            self.assertEqual(nation.stock, prior.stock)
            self.assertEqual(nation.farmland, sum(r.farmland for r in regions))
            for good in GOODS:
                self.assertEqual(sum(r.stock[good] for r in regions), prior.stock[good])
            self.assertEqual((nation.fertility, nation.ore_grade), (prior.fertility, prior.ore_grade))
            for r in regions:
                self.assertEqual(r.deposit, sum(world.tiles[t].deposit for t in r.members))
                self.assertTrue(0 < r.farmland <= r.land)
            self.assertGreater(regions[0].population/regions[0].land,
                               min(r.population/r.land for r in regions[1:]))
        world.regions[0].stock["food"] += 1
        self.assertEqual(original, old)
        self.assertEqual(world.nations[0].stock, original.nations[0].stock)
        with self.assertRaises(ValueError):
            audit_regions(world)
        sync_nations(world)
        audit_regions(world)
        world.nations[0].fertility += 1
        with self.assertRaises(ValueError):
            audit_regions(world)

    def test_each_edge_uses_country_appropriate_adjacent_regions_and_physical_path(self):
        w = regionalize(generate_world(7))
        self.assertTrue(w.roads)
        self.assertTrue(w.borders)
        tile_region = {t: r.id for r in w.regions for t in r.members}
        self.assertEqual(sorted(tile_region), list(range(w.width*w.height)))
        for cross_border, edges in ((False,w.roads),(True,w.borders)):
            for edge in edges:
                a,b = w.regions[edge.a], w.regions[edge.b]
                self.assertEqual(a.owner != b.owner, cross_border)
                self.assertEqual((edge.path[0],edge.path[-1]), (a.seat,b.seat))
                self.assertEqual(len(edge.path)-1, edge.distance)
                self.assertGreater(edge.capacity,0)
                labels = [tile_region[t] for t in edge.path]
                self.assertEqual(set(labels),{a.id,b.id})
                self.assertEqual(sum(x != y for x,y in zip(labels,labels[1:])), 1)
                for x,y in zip(edge.path, edge.path[1:]):
                    self.assertEqual(abs(x%w.width-y%w.width)+abs(x//w.width-y//w.width),1)

    def test_geographic_tampering_is_detected(self):
        base = regionalize(generate_world(17,12,8,2), regions_per_nation=2)
        for mode in ("duplicate_tile","missing_tile","invalid_seat","reversed_road","broken_distance",
                     "jump","foreign_as_domestic","missing_border","capacity"):
            with self.subTest(mode=mode):
                w=deepcopy(base)
                r,road=w.regions[0],w.roads[0]
                if mode=="duplicate_tile":
                    r.members=(*r.members,r.members[0])
                elif mode=="missing_tile":
                    r.members=r.members[1:]
                elif mode=="invalid_seat":
                    r.seat=-1
                elif mode=="reversed_road":
                    w.roads[0]=replace(road,path=tuple(reversed(road.path)))
                elif mode=="broken_distance":
                    w.roads[0]=replace(road,distance=road.distance+1)
                elif mode=="jump":
                    w.roads[0]=replace(road,path=(road.path[0],road.path[-1]),distance=1)
                elif mode=="foreign_as_domestic":
                    w.roads.append(w.borders.pop())
                elif mode=="missing_border":
                    w.borders.pop()
                else:
                    w.roads[0]=replace(road,capacity=0)
                with self.assertRaises(ValueError):
                    audit_geography(w)

    def test_mature_reserves_and_capital_keep_exact_totals(self):
        original=generate_world(9,8,4,1)
        n=prepare(original.nations[0])
        n.deposit=13
        n.capital["industry"][4]=3
        original.nations=[n]
        original.year=11
        w=regionalize(original)
        self.assertEqual(w.year,11)
        self.assertEqual(sum(r.deposit for r in w.regions),13)
        self.assertEqual(sum(r.capital["industry"][4] for r in w.regions),3)
        self.assertEqual(w.nations[0].capital,n.capital)
        w.regions[0].capital["farm"][0]=1
        with self.assertRaises(ValueError):
            audit_regions(w)
        sync_nations(w)
        self.assertEqual(w.nations[0].capital["farm"][0],1)
        self.assertEqual(n.capital["farm"][0],0)

    def test_small_maps_and_invalid_quantities(self):
        for width,height,nations,subregions in [(1,1,1,4),(2,7,7,9),(1,19,1,4),(9,3,4,1)]:
            w=regionalize(generate_world(-2,width,height,nations),subregions)
            audit_regions(w)
            audit_geography(w)
        for mode in ("cash","density","negative","capacity","region_id","nation_id"):
            w=regionalize(generate_world(4,8,8,2))
            if mode=="cash":
                w.nations[0].cash+=1
            elif mode=="density":
                w.regions[0].farmland=w.regions[0].land+1
            elif mode=="negative":
                w.regions[0].stock["food"]=-1
            elif mode=="capacity":
                w.regions[0].capital["farm"][0]=True
            elif mode=="region_id":
                w.regions[0].id=w.regions[1].id
            else:
                w.regions[0].owner=200
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                audit_regions(w)
