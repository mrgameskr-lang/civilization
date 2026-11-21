from copy import deepcopy
from types import SimpleNamespace
import unittest

from civsim.fiscal_policy import collect
from civsim.tax_policy5c import audit_collection_with_rates, collect_with_rates, standing_schedule


class StandingLevyTests(unittest.TestCase):
    def opening(self, ids=(0,), action="defer"):
        regions = [SimpleNamespace(id=i, owner=i, population=2048, stock={"food":2544,"ore":152,"tools":152})
                   for i in ids]
        depots = {i:dict.fromkeys(("food","ore","tools"),0) for i in ids}
        plans = {i:{"owner":i, "action":action, "mode":"integrated", "quantity":100, "target_region":i} for i in ids}
        return regions, depots, plans

    def test_every_platform_rate_and_caretaker_equality(self):
        amounts = {"caretaker":(15,24), "stewards":(10,30), "builders":(20,17),
                   "mutualists":(20,30), "restraint":(10,17)}
        for platform, (food, material) in amounts.items():
            with self.subTest(platform=platform):
                regions, depots, plans = self.opening()
                ordinary = collect(deepcopy(regions), deepcopy(depots), plans, "integrated")[0]
                receipt, = collect_with_rates(regions, depots, plans, "integrated", {0:platform})
                self.assertEqual(receipt["standing_levy"], {"food":food,"ore":material,"tools":material})
                self.assertEqual(receipt["deposited"], receipt["levied"])
                self.assertEqual(receipt["standing_schedule"], standing_schedule(platform))
                self.assertEqual(receipt["standing_schedule"]["food_population_divisor"], 64)
                self.assertTrue(all(receipt["private_close"][g]+depots[0][g] == receipt["private_open"][g]
                                    for g in depots[0]))
                if platform == "caretaker":
                    self.assertEqual(ordinary, {k:v for k,v in receipt.items() if k != "standing_schedule"})

    def test_protected_space_and_population_limits_and_gross_reserve_cost(self):
        rs, vault, plans = self.opening(action="reserve")
        rs[0].stock.update(food=8000, ore=31)
        vault[0]["tools"] = 63
        receipt, = collect_with_rates(rs,vault,plans,"integrated",{0:"mutualists"})
        self.assertEqual(receipt["standing_levy"], {"food":32,"ore":0,"tools":1})
        self.assertEqual(receipt["extra_levy"]["food"], 100)
        self.assertEqual(receipt["handling_used"]["food"], 4)
        self.assertEqual(receipt["deposited"]["food"], 128)
        rs, vault, plans = self.opening(action="reserve")
        vault[0]["food"]=510
        receipt, = collect_with_rates(rs,vault,plans,"integrated",{0:"restraint"})
        self.assertEqual((receipt["standing_levy"]["food"], receipt["extra_levy"]["food"]), (2,0))

    def test_rejects_wrong_schedule_unknown_cabinet_and_mislabeled_receipt_atomically(self):
        rs,vault,plans=self.opening((0,1))
        before=deepcopy((rs,vault))
        for rates in ({0:"stewards"}, {0:"builders",1:"imaginary"}, {0:"restraint",1:"builders",2:"caretaker"},
                      {False:"builders",1:"stewards"}):
            with self.assertRaises(ValueError):
                collect_with_rates(rs,vault,plans,"integrated",rates)
            self.assertEqual((rs,vault),before)
        rates={0:"builders",1:"restraint"}
        rows=collect_with_rates(rs,vault,plans,"integrated",rates)
        for key, field, value in (("standing_levy","food",15),("standing_schedule","platform","caretaker"),
                                  ("standing_schedule","food_population_divisor",32)):
            bad=deepcopy(rows)
            bad[0][key][field]=value
            with self.assertRaises(ValueError):
                audit_collection_with_rates(rs,plans,"integrated",bad,rates)
        with self.assertRaises(ValueError):
            audit_collection_with_rates(rs,plans,"integrated",rows,{0:"caretaker",1:"restraint"})
