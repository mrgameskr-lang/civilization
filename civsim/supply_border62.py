"""Settle and audit the national aid envelope after domestic positioning freight."""
from collections import Counter, defaultdict

from .aid_budget61 import BudgetFlows, _budgets, _terminal, audit_budget_payments
from .diplomatic_flows import _check, _freight, _handling


class DepotBorderFlows(BudgetFlows):
    """Ordinary same-year inland restocking remains eligible for domestic uses."""
    def __init__(self, context, regions, borders, width, supply):
        super().__init__(context,regions,borders,width)
        self.domestic_reserve = Counter()
        for trip in supply["shipments"]:
            if trip["purpose"] == "domestic_reserve" and trip["good"] == "food":
                self.domestic_reserve[trip["target"]] += trip["quantity"]

    def send_aid(self,depots):
        """One national account per donor. Debit real freight for each individual partial shipment."""
        capped=self.flags["capped"]
        credit={i:max(0,d["food"]-self.domestic_reserve[i]) for i,d in depots.items()}
        spent=Counter()
        routes=defaultdict(list)
        for road in sorted(self.borders.values(),key=lambda r:(r.distance,r.a,r.b)):
            for a,b in ((road.a,road.b),(road.b,road.a)):
                routes[self.countries(a,b)].append((a,b,road))
        for (donor,recipient),d in sorted(self.directions.items()):
            remaining=authorized=d["aid_quantity"]
            if not authorized:
                continue
            _check(self.flags["aid"],"aid formula disabled but an appropriation was issued")
            skipped=self.flags["suppress_aid"]==[donor,recipient]
            attempts=[]
            totals=Counter()
            for a,b,road in routes[donor,recipient]:
                if skipped or remaining<2:
                    break
                free=road.capacity-self.aid_used[road.a,road.b]
                space=max(0,self.nodes[b].population//4-depots[b]["food"])
                budget=max(0,self.budgets[donor]-spent[donor])
                limits={"authorized":remaining,"road":free,"stock":100*credit[a]//(100+road.distance),
                        "storage":(32*space+31)//31,"budget":100*budget//(100+road.distance) if capped else None}
                physical=min(v for k,v in limits.items() if k!="budget")
                uncapped=physical if physical>=2 else 0
                raw=min(v for v in limits.values() if v is not None)
                qty=raw if raw>=2 else 0
                fee,loss=_freight(qty,road.distance),_handling(qty)
                debit=qty+fee
                attempt={"donor":donor,"recipient":recipient,"source":a,"target":b,"distance":road.distance,
                         "available_food":credit[a],"capacity_before":free,"storage_space":space,
                         "request_remaining":remaining,"limits":limits,"binding":[k for k,v in limits.items() if v==raw],
                         "pre_lot_quantity":raw,"uncapped_quantity":uncapped,"budget_displaced":uncapped-qty,
                         "before_budget":budget,"after_budget":max(0,budget-debit),"quantity":qty}
                attempts.append(attempt)
                if not qty:
                    continue
                net=qty-loss
                path=road.path if a==road.a else road.path[::-1]
                self.aid["shipments"].append(dict(source=a,target=b,donor=donor,recipient=recipient,quantity=qty,
                    received=net,cost_food=fee,handling_food=loss,distance=road.distance,path=list(path)))
                depots[a]["food"]-=debit
                credit[a]-=debit
                depots[b]["food"]+=net
                self.aid_used[road.a,road.b]+=qty
                remaining-=qty
                spent[donor]+=debit
                totals.update(received=net,cost_food=fee,handling_food=loss)
            self.aid["attempts"].extend(attempts)
            dispatched=authorized-remaining
            self.aid["directions"].append(dict(source=donor,target=recipient,authorized=authorized,
                dispatched=dispatched,received=totals["received"],cost_food=totals["cost_food"],
                handling_food=totals["handling_food"],actual_debit=dispatched+totals["cost_food"],unshipped=remaining,
                shortfall_reasons=_terminal(remaining,attempts,skipped)))
        self.aid["donors"]=[dict(donor=n,planned_budget=q,actual_debit=spent[n],remaining_budget=max(0,q-spent[n]),
                                  overrun=max(0,spent[n]-q),capped=capped) for n,q in self.budgets.items()]


def charge_border(context, regions, borders, width, depots, supply):
    flows = DepotBorderFlows(context, regions, borders, width, supply)
    prepaid = {c["owner"]: c["aid_freight_food"] for c in supply["countries"]}
    total = flows.budgets.copy()
    _check(total.keys() == prepaid.keys(), "missing domestic freight account")
    for owner, budget in total.items():
        _check(0 <= prepaid[owner] <= budget, "domestic aid freight exceeds appropriation")
        flows.budgets[owner] -= prepaid[owner]
    flows.send_aid(depots)
    for d in flows.aid["donors"]:
        owner = d["donor"]
        d.update(planned_budget=total[owner], border_debit=d["actual_debit"],
                 internal_freight=prepaid[owner], actual_debit=d["actual_debit"] + prepaid[owner])
    return flows


def audit_envelope(context, supply):
    aid = context["physical"]["aid"]
    pre = {c["owner"]: c["aid_freight_food"] for c in supply["countries"]}
    budget = _budgets(context, pre)
    _check(len(pre) == len(supply["countries"]) and len(aid["donors"]) == len(pre),
           "invalid donor coverage")
    net = {n: q - pre[n] for n, q in budget.items()}
    _check(all(0 <= net[n] <= budget[n] for n in budget), "unfunded domestic aid freight")
    border_only = []
    for d in aid["donors"]:
        n = d["donor"]
        paid = sum(s["quantity"] + s["cost_food"] for s in aid["shipments"] if s["donor"] == n)
        _check(d == dict(donor=n, planned_budget=budget[n], actual_debit=paid + pre[n],
                         border_debit=paid, internal_freight=pre[n], remaining_budget=net[n]-paid,
                         overrun=0, capped=True) and net[n] >= paid, "national aid budget mismatch")
        border_only.append(dict(donor=n, planned_budget=net[n], actual_debit=paid,
                                remaining_budget=net[n]-paid, overrun=0, capped=True))
    _check([d["donor"] for d in border_only] == sorted(pre), "duplicate or missing donor")
    # Re-use the independent per-invoice integer search with the verified remainder.
    pairs = [{"policy":{"directions":[{**d, "aid_budget": net[d["source"]]}
                                     for d in p["policy"]["directions"]]}} for p in context["pairs"]]
    if pairs:
        audit_budget_payments({"phase61":context["phase61"], "pairs":pairs}, {**aid, "donors":border_only})
    else:
        _check(not any(aid[k] for k in ("shipments","attempts","directions")), "foreign transfer without a pair")
