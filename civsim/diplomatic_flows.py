"""Foreign access to existing roads, public food and settlement places."""
from collections import Counter, defaultdict
from types import SimpleNamespace

from .audit import BalanceError
from .border import border_market, move_people
from .model import GOODS
from .regions import Road


def _check(value, message):
    if not value:
        raise BalanceError("foreign flows: "+message)


def _handling(quantity):
    return (quantity+31)//32


def _freight(quantity,distance):
    return (quantity*distance+99)//100


class ForeignFlows:
    """One year's bilateral permissions and physical receipts. Cargo and people use separate limits."""
    def __init__(self, context, regions, borders, width):
        self.nodes = {r.id:r for r in regions}
        self.width = width
        self.borders = {(e.a,e.b):e for e in borders}
        self.arm = context["arm"]
        _check(self.arm in ("B","C","D"), "unknown arm")
        self.directions = {}
        self.partners = set()
        for pair in context["pairs"]:
            policy = pair["policy"]
            for d in policy["directions"]:
                key = d["source"],d["target"]
                _check(key[0]!=key[1] and key not in self.directions, "duplicate or domestic direction")
                _check(all(type(d[k]) is int and 0<=d[k]<=1000 for k in
                           ("trade_limit_permille","migration_limit_permille","migration_accept_permille")),
                       "invalid directional rate")
                _check(type(d["aid_quantity"]) is int and d["aid_quantity"]>=0
                       and (not d["aid_quantity"] or d["aid_accepted"]), "unapproved cargo")
                self.directions[key] = d
                if self.arm in ("C","D") and policy["agreement_active"]:
                    self.partners.add(key)
        self.aid_used = Counter()
        self.private_used = Counter()
        self.direction_used = Counter()
        self.exits = Counter()
        self.entries = Counter()
        self.trade_attempts = []
        self.migration_attempts = []
        self.aid = {"directions":[], "attempts":[], "shipments":[]}

    def countries(self, a, b):
        return self.nodes[a].owner, self.nodes[b].owner

    def preferred(self, seller, buyer):
        return self.countries(seller,buyer) in self.partners

    def trade(self, seller, buyer, good, road, feasible):
        if feasible <= 0:
            return 0
        direction = self.directions[self.countries(seller,buyer)]
        limit = road.capacity*direction["trade_limit_permille"]//1000 if self.arm=="D" else road.capacity
        already = self.direction_used[seller,buyer]
        qty = min(feasible, max(0,limit-already))
        self.trade_attempts.append({"source":seller,"target":buyer,"good":good,"feasible":feasible,"quantity":qty,
                                    "denied":feasible-qty,"preferred":self.preferred(seller,buyer),
                                    "direction_limit":limit,"direction_used_before":already})
        self.direction_used[seller,buyer] += qty
        self.private_used[road.a,road.b] += qty
        return qty

    def migrate(self, source, target, feasible, donor, host):
        owners = self.countries(source,target)
        if owners[0]==owners[1] or not feasible:
            return feasible
        direction = self.directions[owners]
        exit_rate = direction["migration_limit_permille"] if self.arm=="D" else 1000
        entry_rate = direction["migration_accept_permille"] if self.arm=="D" else 1000
        exit_cap = donor["requested_departures"]*exit_rate//1000
        entry_cap = host["host_capacity"]*entry_rate//1000
        out_key, in_key = (source,owners[1]),(owners[0],target)
        after_exit = min(feasible, max(0,exit_cap-self.exits[out_key]))
        qty = min(after_exit, max(0,entry_cap-self.entries[in_key]))
        self.migration_attempts.append({"source":source,"target":target,"feasible":feasible,"people":qty,
                                       "denied_exit":feasible-after_exit,"denied_entry":after_exit-qty,
                                       "exit_limit":exit_cap,"entry_limit":entry_cap,
                                       "exit_used_before":self.exits[out_key],"entry_used_before":self.entries[in_key]})
        self.exits[out_key] += qty
        self.entries[in_key] += qty
        return qty

    def send_aid(self, depots):
        """Allocate authorized food from post-works, pre-tax depots, without re-exporting incoming aid."""
        if self.arm!="D":
            return
        source_credit = {i:d["food"] for i,d in depots.items()}
        routes = defaultdict(list)
        for road in sorted(self.borders.values(),key=lambda e:(e.distance,e.a,e.b)):
            for a,b in ((road.a,road.b),(road.b,road.a)):
                routes[self.countries(a,b)].append((a,b,road))
        for owners,d in sorted(self.directions.items()):
            remaining = d["aid_quantity"]
            if not remaining:
                continue
            summary = {"source":owners[0],"target":owners[1],"authorized":remaining,"dispatched":0,
                       "received":0,"cost_food":0,"handling_food":0}
            for a,b,road in routes[owners]:
                if remaining < 2:
                    break
                key = road.a,road.b
                free = road.capacity-self.aid_used[key]
                stock,space = source_credit[a], max(0,self.nodes[b].population//4-depots[b]["food"])
                # ceil(q*d/100)+q <= stock; and q-ceil(q/32)=floor(31*q/32) <= space.
                qty = min(remaining,free,100*stock//(100+road.distance),(32*space+31)//31)
                qty = qty if qty>=2 else 0
                self.aid["attempts"].append({"source":a,"target":b,"available_food":stock,"storage_space":space,
                                             "capacity_before":free,"request_remaining":remaining,"quantity":qty})
                if not qty:
                    continue
                fee,loss = _freight(qty,road.distance),_handling(qty)
                received = qty-loss
                path = list(road.path if a==road.a else reversed(road.path))
                ticket = {"source":a,"target":b,"donor":owners[0],"recipient":owners[1],"quantity":qty,
                          "received":received,"cost_food":fee,"handling_food":loss,"distance":road.distance,"path":path}
                self.aid["shipments"].append(ticket)
                depots[a]["food"] -= qty+fee
                source_credit[a] -= qty+fee
                depots[b]["food"] += received
                self.aid_used[key] += qty
                remaining -= qty
                for k in ("received","cost_food","handling_food"):
                    summary[k] += ticket[k]
                summary["dispatched"] += qty
            self.aid["directions"].append({**summary,"unshipped":remaining})

    def trace(self):
        roads=[]
        for (a,b),e in sorted(self.borders.items()):
            aid,private = self.aid_used[a,b],self.private_used[a,b]
            roads.append({"a":a,"b":b,"distance":e.distance,"path":list(e.path),"capacity":e.capacity,
                          "aid_cargo":aid,"private_cargo":private,"unused":e.capacity-aid-private})
        return {"width":self.width,"roads":roads,"aid":self.aid,
                "trade_attempts":self.trade_attempts,"migration_attempts":self.migration_attempts}


def _network(physical, nodes):
    width = physical["width"]
    _check(type(width) is int and width>=1,"invalid width")
    borders = []
    for row in physical["roads"]:
        a,b = row["a"],row["b"]
        p = row["path"]
        _check(a in nodes and b in nodes and a<b and nodes[a].owner!=nodes[b].owner, "invalid crossing")
        _check(type(row["distance"]) is int and row["distance"]>0 and len(p)==row["distance"]+1 and
               all(type(tile) is int and tile>=0 for tile in p) and len(set(p))==len(p) and
               (p[0],p[-1])==(nodes[a].seat,nodes[b].seat), "invalid customs path or distance")
        _check(all(abs(x%width-y%width)+abs(x//width-y//width)==1 for x,y in zip(p,p[1:])),
               "nonadjacent customs tiles")
        _check(all(type(row[k]) is int and row[k]>=0 for k in ("capacity","aid_cargo","private_cargo","unused"))
               and row["capacity"]==row["aid_cargo"]+row["private_cargo"]+row["unused"], "shared crossing capacity")
        borders.append(Road(a,b,row["distance"],row["capacity"],tuple(p)))
    keys=[(e.a,e.b) for e in borders]
    _check(keys==sorted(set(keys)),"missing order or duplicate crossing")
    return borders


def _audit_aid(record,nodes,borders,balances):
    ctx = record["diplomacy"]
    laws = {(d["source"],d["target"]):d for p in ctx["pairs"] for d in p["policy"]["directions"]}
    routes = {(e.a,e.b):e for e in borders}
    initial = {i:d["food"] for i,d in balances.items()}
    public = initial.copy()
    debits,used,authorized = Counter(),Counter(),Counter()
    for ticket in ctx["physical"]["aid"]["shipments"]:
        a,b,qty = ticket["source"],ticket["target"],ticket["quantity"]
        pair = nodes[a].owner,nodes[b].owner
        key = tuple(sorted((a,b)))
        _check(key in routes and pair==(ticket["donor"],ticket["recipient"])
               and type(qty) is int and qty>=2 and ctx["arm"]=="D" and laws[pair]["aid_accepted"],
               "invalid or unapproved public transfer")
        edge = routes[key]
        path = edge.path if a==edge.a else edge.path[::-1]
        freight,handling = -(-qty*edge.distance//100),-(-qty//32)
        net = qty-handling
        _check((ticket["distance"],ticket["received"],ticket["cost_food"],ticket["handling_food"])
               ==(edge.distance,net,freight,handling) and tuple(ticket["path"])==path, "invalid aid delivery or fees")
        used[key] += qty
        authorized[pair] += qty
        debits[a] += qty+freight
        public[a] -= qty+freight
        public[b] += net
        _check(debits[a]<=initial[a] and public[a]>=0 and public[b]<=nodes[b].population//4
               and used[key]<=edge.capacity and authorized[pair]<=laws[pair]["aid_quantity"],
               "unfunded aid, exhausted crossing, storage, or excess appropriation")
    for tax in record["government"]["levies"]:
        _check(public[tax["region"]]==tax["depot_open"]["food"], "aid does not reach the next warehouse account")


def audit_foreign_flows(record, previous_record=None, *, geography=None):
    """Reconstruct international offers and moves, then cross-post bilateral receipts at physical endpoints."""
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
    expected = ForeignFlows(ctx,local,borders,physical["width"])
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
