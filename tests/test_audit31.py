"""Fail a year before publishing mispriced or unfunded investment decisions."""
from copy import deepcopy
import unittest

from civsim.audit import BalanceError, audit
from civsim.engine import step
from civsim.rules import Rules
from tests.test_investment_audit import operating_world


class Audit31Tests(unittest.TestCase):
    def test_rejects_fabricated_round_budgets_rankings_and_class_postings(self):
        record = step(operating_world(), 1, Rules("reallocate", investment="capital", policy31="scaled-multi"))
        for field in ("upkeep", "state", "valuation", "constraints", "cap", "effect", "round"):
            with self.subTest(field=field):
                altered = deepcopy(record)
                inv = altered["countries"][0]["production"]["investment"]
                rnd = inv["selection_rounds"][0]
                if field == "upkeep":
                    inv["class_accounts"]["industry"]["upkeep_used"]["tools"] += 1
                elif field == "state":
                    rnd["stock"]["tools"] += 1
                elif field == "valuation":
                    rnd["candidates"]["land"]["net_value"] += 1
                elif field == "constraints":
                    rnd["candidates"]["land"]["constraints"].append("fake")
                elif field == "cap":
                    inv["class_limit"] += 1
                elif field == "effect":
                    inv["farm_multiplier"] += 1
                else:
                    rnd["selected"] = "not-a-project"
                with self.assertRaises(BalanceError):
                    audit(altered)
