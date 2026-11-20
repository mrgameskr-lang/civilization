import copy
import unittest

from civsim.audit import BalanceError, audit
from civsim.engine import step
from civsim.model import GOODS, generate_world


class AnnualEngineTests(unittest.TestCase):
    def test_fifty_year_runs_balance_independently(self):
        for seed in (0, 17, 42, -4):
            world = generate_world(seed)
            cash = sum(n.cash for n in world.nations)
            for year in range(1, 51):
                record = step(world, year)
                net_goods = {good: 0 for good in GOODS}
                for c in record["countries"]:
                    before, after = c["opening"], c["closing"]
                    p, u, d = c["production"], c["consumption"], c["demography"]
                    self.assertEqual(after["population"], before["population"] + d["births"]
                                     - d["deaths"] + d["immigrants"] - d["emigrants"])
                    for g in GOODS:
                        self.assertGreaterEqual(after["stock"][g], 0)
                        net_goods[g] += (after["stock"][g] - before["stock"][g]
                                         - p["produced"][g] + p["used"][g] + u["used"][g])
                self.assertEqual(net_goods, dict.fromkeys(GOODS, 0))
                self.assertEqual(sum(n.cash for n in world.nations), cash)
                self.assertEqual(sum(c["demography"]["immigrants"] for c in record["countries"]),
                                 sum(m["people"] for m in record["moves"]))

    def test_detects_tampered_stock_cash_population_deposit_and_movements(self):
        original = step(generate_world(42), 1)
        for key in ("population", "deposit", "cash", "stock", "migration", "negative", "events"):
            with self.subTest(key=key):
                record = copy.deepcopy(original)
                c = record["countries"][0]
                if key == "stock":
                    c["closing"]["stock"]["ore"] += 1
                elif key == "negative":
                    c["opening"]["stock"]["food"] = -1
                elif key == "migration":
                    record["moves"].append({"source": 0, "target": 1, "people": 1})
                elif key == "events":
                    record["events"].append({"kind": "fabricated"})
                else:
                    c["closing"][key] += 1
                with self.assertRaises(BalanceError):
                    audit(record)

    def test_events_follow_observed_shortfalls_and_flows(self):
        world = generate_world(42)
        shortages = moves = 0
        for y in range(1, 51):
            row = step(world, y)
            expected = {c["id"]: c["consumption"]["food_need"] - c["consumption"]["food_eaten"]
                        for c in row["countries"]}
            actual = {e["country"]: e["unmet"] for e in row["events"] if e["kind"] == "food_shortage"}
            self.assertEqual(actual, {k: v for k, v in expected.items() if v > 0})
            shortages += len(actual)
            moves += sum(m["people"] for m in row["moves"])
        self.assertGreater(shortages, 0)
        self.assertGreater(moves, 0)

