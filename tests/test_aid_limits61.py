from itertools import product
from types import SimpleNamespace
import unittest

from civsim.aid_budget61 import BudgetFlows, audit_budget_payments
from civsim.border import validate_border_paths
from civsim.regions import Road


class AidLimits61Tests(unittest.TestCase):
    def test_integer_search_over_stock_warehouse_budget_and_per_ticket_rounding(self):
        checked=0
        for distance in (1,2,13,32,50,100):
            road=Road(0,1,distance,80,tuple(range(distance+1)))
            cut=(distance+1)//2
            nodes=[SimpleNamespace(id=0,owner=0,seat=0,members=tuple(range(cut)),population=400),
                   SimpleNamespace(id=1,owner=1,seat=distance,members=tuple(range(cut,distance+1)),population=0)]
            validate_border_paths(nodes,[road],101)
            for food,budget,space in product((0,1,2,3,31,32,33,63,64,65),(0,1,2,3,20,33),(0,1,2,31,32,33)):
                with self.subTest(distance=distance,food=food,budget=budget,space=space):
                    nodes[1].population=space*4
                    flags={"source":0,"target":1,"trade_limit_permille":1000,"migration_limit_permille":1000,
                           "migration_accept_permille":1000,"aid_accepted":True,"aid_quantity":80,"aid_budget":budget}
                    reverse={**flags,"source":1,"target":0,"aid_accepted":False,"aid_quantity":0,"aid_budget":0}
                    ctx={"arm":"D","phase61":{"arm":"F","aid":True,"export":True,"migration":True,"capped":True,
                                              "suppress_aid":None},
                         "pairs":[{"policy":{"agreement_active":False,"directions":[flags,reverse]}}]}
                    # Build the reference set by pricing each positive whole lot separately.
                    feasible=[0]
                    for q in range(2,81):
                        freight,remainder=divmod(q*distance,100)
                        cost=q+freight+int(bool(remainder))
                        loss,remainder=divmod(q,32)
                        delivered=q-loss-int(bool(remainder))
                        if cost<=budget and cost<=food and delivered<=space:
                            feasible.append(q)
                    depots={0:{"food":food,"ore":0,"tools":0},1:{"food":0,"ore":0,"tools":0}}
                    flows=BudgetFlows(ctx,nodes,[road],101)
                    flows.send_aid(depots)
                    self.assertEqual(flows.aid["directions"][0]["dispatched"],max(feasible))
                    audit_budget_payments(ctx,flows.aid)
                    checked+=1
        self.assertEqual(checked,2160)
