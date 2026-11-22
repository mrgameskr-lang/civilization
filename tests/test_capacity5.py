from copy import deepcopy
import unittest

from civsim.government import start_government, step_government
from civsim.model import generate_world
from civsim.regions import regionalize
from experiments.capacity5 import RoadCapacityAudit
from experiments.phase5a import _seed


class CapacityReportTests(unittest.TestCase):
    def test_reported_opening_and_closing_are_distinct_on_actual_checkpoints(self):
        for seed, base, current, following in ((28, 10328, 10376, 10328), (30, 10070, 10070, 10118)):
            with self.subTest(seed=seed):
                runs, countries, *_ = _seed((seed, (50,)))
                world = next(r for r in runs if r["mode"] == "integrated")
                owners = [r for r in countries if r["mode"] == "integrated"]
                fields = {"year_base_capacity": base, "year_effective_capacity": current,
                          "final_effective_capacity": following, "next_year_effective_capacity": following}
                for k, value in fields.items():
                    self.assertEqual(world[k], value)
                    self.assertEqual(sum(r[k] for r in owners), value)
                self.assertEqual(world["base_capacity"], 50 * base)
                self.assertEqual(world["next_capacity"] - world["effective_capacity"], following - base)

    def test_lapsed_and_new_improvements_carry_to_year_51_on_the_same_physical_road(self):
        for seed, pair, start, end in ((28, (24, 25), 1, 0), (30, (16, 17), 0, 1)):
            with self.subTest(seed=seed):
                sim = start_government(regionalize(generate_world(seed)))
                check = RoadCapacityAudit(sim.world)
                for year in range(1, 51):
                    rec = step_government(sim, year, "integrated")
                    check.observe(rec)
                edge = next(e for e in rec["government"]["roads"] if (e["a"], e["b"]) == pair)
                self.assertEqual((edge["opening_units"], edge["closing_units"]), (start, end))
                following = step_government(sim, 51, "integrated")
                check.observe(following)
                carried = next(e for e in following["government"]["roads"] if (e["a"], e["b"]) == pair)
                self.assertEqual(carried["capacity"], edge["next_capacity"])
                self.assertEqual(carried["opening_units"], end)

    def test_checks_trusted_map_project_timing_and_per_edge_loads(self):
        sim = start_government(regionalize(generate_world(14)))
        check = RoadCapacityAudit(sim.world)
        first = step_government(sim, 1, "integrated")
        check.observe(first)
        second = step_government(sim, 2, "integrated")
        for name in ("base", "opening_units", "closing_units", "capacity", "next_capacity", "private_use"):
            with self.subTest(field=name):
                bad = deepcopy(second)
                bad["government"]["roads"][0][name] += 1
                with self.assertRaises(ValueError):
                    check.observe(bad)
        bad = deepcopy(second)
        bad["government"]["roads"].append(bad["government"]["roads"][0])
        with self.assertRaises(ValueError):
            check.observe(bad)
        bad = deepcopy(second)
        bad["domestic"]["shipments"][0]["tile_path"][0] += 1
        with self.assertRaises(ValueError):
            check.observe(bad)
        check.observe(second)
        with self.assertRaises(ValueError):
            check.observe(second)
