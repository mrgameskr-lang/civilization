import unittest

from experiments.cash_history import cash_path, first_divergence
from tests.test_economy import country


def observation(year, wallets, deal):
    return {
        "year": year,
        "countries": [{"id": i, "closing": {"cash": cash}} for i, cash in enumerate(wallets)],
        "market": {"trades": [deal]},
    }


class CashHistoryTests(unittest.TestCase):
    def test_concentration_first_zero_and_recovery_from_signed_cash_flows(self):
        nations = [country(i, cash=100) for i in range(2)]
        first = observation(1, (0, 200), {
            "good": "food", "seller": 1, "buyer": 0, "quantity": 20, "unit_price": 5,
        })
        for receipt, expected_recovery in [(1, 0), (20, 1)]:
            with self.subTest(receipt=receipt):
                second = observation(2, (receipt, 200-receipt), {
                    "good": "ore", "seller": 0, "buyer": 1, "quantity": 1, "unit_price": receipt,
                })
                stats = cash_path(nations, [first, second], (0, 1, 2))
                self.assertEqual(stats["checkpoints"][0]["top1_share"], 0.5)
                self.assertEqual(stats["checkpoints"][1]["hhi"], 1.0)
                if receipt == 20:
                    self.assertEqual(stats["checkpoints"][2], {"top1_share": 0.9, "hhi": 0.82})
                expected = {"ever_zero_countries": 1, "zero_country_years": 1,
                            "recovered_above_one_percent_after_zero": expected_recovery,
                            "food_net_buyers_at_first_zero": 1, "food_only_net_cost_at_first_zero": 1,
                            "final_food_net_buyers": 1}
                self.assertEqual({k: stats[k] for k in expected}, expected)

    def test_first_divergence_shows_actual_food_and_industrial_settlements(self):
        result = first_divergence(6, 0)
        self.assertEqual((result["year"], result["opening_cash"]), (8, 1067))
        standard, alternate = result["food-ore-tools"], result["ore-tools-food"]
        self.assertEqual([t["quantity"] for t in standard["trades"]], [177])
        self.assertEqual([(t["good"], t["quantity"]) for t in alternate["trades"]],
                         [("tools", 25), ("food", 144)])
        self.assertEqual((standard["food_unmet"], alternate["food_unmet"]), (1595, 1628))
