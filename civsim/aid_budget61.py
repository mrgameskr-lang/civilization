"""6.0A.1 settles each aid invoice against physical stocks and optionally a national gross budget."""
from collections import Counter, defaultdict

from .diplomatic_flows import ForeignFlows, _check, _freight, _handling


def _budgets(context,owners):
    amounts={}
    for pair in context["pairs"]:
        for d in pair["policy"]["directions"]:
            donor,q=d["source"],d["aid_budget"]
            _check(type(q) is int and q>=0 and amounts.setdefault(donor,q)==q,"inconsistent donor planning budget")
    for c in context.get("countries",()):
        p=c["population"]
        protected=p//64+c["prior_unmet"]//2+p*c["groups"]["consumer"]["signals"]["reserve"]//8000
        expected=min(p//48,max(0,c["depot"]["food"]-protected))
        _check(amounts.setdefault(c["id"],expected)==expected,"donor budget differs from opening evidence")
    return {n:amounts.get(n,0) for n in sorted(owners)}


def _terminal(remaining,attempts,skipped):
    if not remaining:
        return []
    if skipped:
        return ["suppressed"]
    if remaining<2:
        return ["minimum_lot"]
    if not attempts:
        return ["no_border_route"]
    return sorted({k for t in attempts for k in t["binding"] if k!="authorized"} |
                  ({"minimum_lot"} if any(t["pre_lot_quantity"]==1 for t in attempts) else set()))


class BudgetFlows(ForeignFlows):
    def __init__(self,context,regions,borders,width):
        super().__init__(context,regions,borders,width)
        self.flags=context["phase61"]
        self.budgets=_budgets(context,{r.owner for r in regions})

    def send_aid(self,depots):
        """One national account per donor. Debit real freight for each individual partial shipment."""
        capped=self.flags["capped"]
        credit={i:d["food"] for i,d in depots.items()}
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


def _maximum(upper,feasible):
    """Largest feasible integer for an independent audit of the integer/ceiling inverses."""
    low,high=0,upper
    while low<high:
        middle=(low+high+1)//2
        if feasible(middle):
            low=middle
        else:
            high=middle-1
    return low


def audit_budget_payments(context,aid):
    """Replay appropriation, marginal constraints, and actual invoices independent of dispatch."""
    flags=context["phase61"]
    owners={r["id"] for r in context.get("countries",())} | {
        d["source"] for p in context["pairs"] for d in p["policy"]["directions"]}
    initial=_budgets(context,owners)
    spent=Counter()
    invoices=iter(aid["shipments"])
    attempts=defaultdict(list)
    for t in aid["attempts"]:
        attempts[t["donor"],t["recipient"]].append(t)
    expected={(d["source"],d["target"]):d["aid_quantity"] for p in context["pairs"]
              for d in p["policy"]["directions"] if d["aid_quantity"]}
    _check([(d["source"],d["target"]) for d in aid["directions"]]==sorted(expected),"unapproved direction or order")
    _check(set(attempts)<=expected.keys(),"attempt on unauthorized direction")
    for entry in aid["directions"]:
        pair=entry["source"],entry["target"]
        n=pair[0]
        qty_left=expected[pair]
        withheld=flags["suppress_aid"]==list(pair)
        _check(flags["aid"] and entry["authorized"]==qty_left and not (withheld and attempts[pair]),
               "wrong authorization or suppression")
        paid=Counter()
        for t in attempts[pair]:
            q,left,dist,space,cap,stock=(t[k] for k in
                ("quantity","before_budget","distance","storage_space","capacity_before","available_food"))
            _check(all(type(v) is int and v>=0 for v in (q,left,dist,space,cap,stock)) and dist>0 and
                   t["request_remaining"]==qty_left>=2 and left==max(0,initial[n]-spent[n]),"invalid opening balance")
            def gross(v):
                return v-(-v*dist//100)
            bounds={"authorized":qty_left,"road":cap,"stock":_maximum(stock,lambda v:gross(v)<=stock),
                    "storage":_maximum(2*space+2,lambda v:v+(-v//32)<=space),
                    "budget":_maximum(left,lambda v:gross(v)<=left) if flags["capped"] else None}
            local=min(v for k,v in bounds.items() if k!="budget")
            best=min(v for v in bounds.values() if v is not None)
            untapered=local if local>=2 else 0
            _check(t["limits"]==bounds and t["binding"]==[k for k,v in bounds.items() if v==best]
                   and t["pre_lot_quantity"]==best and q==(best if best>=2 else 0)
                   and t["uncapped_quantity"]==untapered and t["budget_displaced"]==untapered-q,
                   "false budget, limiting factor, feasible quantity, or tie")
            charge=gross(q)
            _check(t["after_budget"]==max(0,left-charge),"wrong remaining budget")
            if q:
                invoice=next(invoices,None)
                _check(invoice is not None and
                       (invoice["donor"],invoice["recipient"],invoice["source"],invoice["target"],invoice["distance"])==
                       (*pair,t["source"],t["target"],dist) and
                       (invoice["quantity"],invoice["cost_food"],invoice["received"],invoice["handling_food"])==
                       (q,charge-q,q+(-q//32),-(-q//32)),"incorrect staged invoice")
                spent[n]+=charge
                paid.update(dispatched=q,received=invoice["received"],cost_food=charge-q,
                            handling_food=invoice["handling_food"],actual_debit=charge)
                qty_left-=q
        _check(entry["unshipped"]==qty_left and all(entry[k]==paid[k] for k in
               ("dispatched","received","cost_food","handling_food","actual_debit")) and
               entry["shortfall_reasons"]==_terminal(qty_left,attempts[pair],withheld),
               "direction totals or shortfall explanation")
    _check(next(invoices,None) is None,"extra invoice")
    _check(aid["donors"]==[dict(donor=n,planned_budget=q,actual_debit=spent[n],
        remaining_budget=max(0,q-spent[n]),overrun=max(0,spent[n]-q),capped=flags["capped"])
        for n,q in initial.items()] and (not flags["capped"] or all(spent[n]<=q for n,q in initial.items())),
        "incorrect consolidated national budget or uncapped debit")


def _audit_foreign61(record, previous_record=None, *, geography=None):
    """Reconstruct international offers and moves, then cross-post bilateral receipts at physical endpoints."""
    from types import SimpleNamespace
    from .border import border_market, move_people
    from .diplomatic_flows import _audit_aid, _network
    from .model import GOODS
    from .regions import Road
    from .regional_engine import audit_borders
    ctx = record["diplomacy"]
    physical = ctx["physical"]
    rows = {r["id"]:r for r in record["regions"]}
    local = [SimpleNamespace(**r["opening"]) for r in rows.values()]
    nodes = {r.id:r for r in local}
    borders = _network(physical,nodes)
    if geography is not None:
        _check(physical["width"]==geography.width and borders==sorted(geography.borders,key=lambda e:(e.a,e.b)),
               "crossing differs from the initial world")
    if previous_record is not None:
        prior=previous_record["diplomacy"]["physical"]
        keys=("a","b","distance","capacity","path")
        _check(prior["width"]==physical["width"] and
               [tuple(e[k] for k in keys) for e in prior["roads"]]==
               [tuple(e[k] for k in keys) for e in physical["roads"]], "physical crossing changed mid-run")
    audit_budget_payments(ctx,physical["aid"])
    expected = BudgetFlows(ctx,local,borders,physical["width"])
    depots={r["id"]:r["depot_close"].copy() for r in record["government"]["works"]["nodes"]}
    _audit_aid(record,nodes,borders,depots)
    expected.send_aid(depots)
    for r in local:
        row=rows[r.id]
        p=row["production"]
        r.stock={g:r.stock[g]+p["produced"][g]-p["used"][g] for g in GOODS}
    produced={r.id:{"stock":r.stock.copy(),"cash":r.cash} for r in local}
    market=border_market(local,borders,access=expected)
    _check(market==record["border_market"],"international offer order or settlement")
    taxes={r["region"]:r for r in record["government"]["levies"]}
    audit_borders(local,borders,market,produced,{i:(taxes[i]["private_open"],r["closing"]["cash"])
                                               for i,r in rows.items()})
    for r in local:
        r.stock=rows[r.id]["closing"]["stock"].copy()
    domestic=[Road(e["a"],e["b"],e["distance"],0,()) for e in record["domestic"]["roads"]]
    vital,moves=move_people(local,{i:r["consumption"] for i,r in rows.items()},[*domestic,*borders],access=expected)
    _check(moves==record["moves"] and all(vital[i]==r["demography"] and nodes[i].population==r["closing"]["population"]
                                          for i,r in rows.items()), "admission or residence account")
    _check(expected.trace()==physical, "bilateral cargo, aid, denial or people ledger differs")


def audit_fiscal61(record, geography=None, previous_record=None):
    """Verify the posted economy, bilateral legal decisions, and each budget-limited payment."""
    from .diplomacy61 import audit_rules61
    from .fiscal_audit61 import audit_accounts61
    from .government_audit import audit_fiscal_year

    if "phase61" not in record["diplomacy"]:
        return audit_fiscal_year(record,geography=geography,previous_record=previous_record)

    audit_accounts61(record,previous_record)
    _audit_foreign61(record,previous_record,geography=geography)
    audit_rules61(record,previous_record)
