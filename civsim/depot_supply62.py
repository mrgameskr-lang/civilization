"""Domestic public-depot transfers for approved food aid and lagged civilian reserves."""
from collections import Counter, defaultdict

from . import logistics
from .aid_budget61 import _budgets
from .border import validate_border_paths
from .fiscal_policy import _bounds
from .model import GOODS
from .public_works import _opening, _audit_trip, _relief_open


def _check(value, message):
    if not value:
        raise ValueError("depot supply: " + message)


def _zero():
    return dict.fromkeys(GOODS, 0)


def _maximum(high, valid):
    low = 0
    while low < high:
        mid = (low + high + 1) // 2
        if valid(mid):
            low = mid
        else:
            high = mid - 1
    return low


def _network(regions, roads, borders, depots, capacity, width):
    nodes, edges, adj, paths = _opening(regions, roads, depots, width)
    _relief_open(nodes, edges, capacity, {r.owner:0 for r in regions})
    validate_border_paths(regions, borders, width)
    links = defaultdict(list)
    for road in sorted(borders, key=lambda e:(e.distance, e.a, e.b)):
        for a,b in ((road.a, road.b), (road.b, road.a)):
            links[nodes[a].owner, nodes[b].owner].append((a, b, road))
    return nodes, edges, adj, paths, links


def _policy(ctx, nodes):
    budgets = _budgets(ctx, {r.owner for r in nodes.values()})
    laws = {}
    history = {}
    for pair in ctx['pairs']:
        for d in pair['policy']['directions']:
            key = d['source'], d['target']
            _check(key not in laws and key[0] != key[1] and all(n in budgets for n in key),
                   "duplicate or unknown direction")
            q = d['aid_quantity']
            _check(type(q) is int and q >= 0 and (q == 0 or d['aid_accepted']), "unapproved aid")
            if ctx.get('phase61', {}).get('suppress_aid') == list(key):
                q = 0
            laws[key] = q
        for old in pair['opening']['last']:
            key = old['source'], old['target']
            history[key] = max(old['aid_request'], old['aid_quantity'] - old['aid_sent'], 0)
    return budgets, {k:q for k,q in sorted(laws.items()) if q}, history


def _preview(nodes, links, laws, food, budgets):
    """Read-only forecast in the external dispatcher's order. Incoming foreign aid cannot finance exports."""
    stock = food.copy()
    credit = food.copy()
    remaining = budgets.copy()
    sent, held, crossing = Counter(), Counter(), Counter()
    for pair, authorized in laws.items():
        donor, _ = pair
        for a,b,e in links.get(pair, ()):
            if authorized - sent[pair] < 2:
                break
            qty = min(authorized - sent[pair], e.capacity - crossing[e.a,e.b],
                      100 * min(credit[a], remaining[donor]) // (100 + e.distance),
                      (32 * max(0, nodes[b].population // 4 - stock[b]) + 31) // 31)
            if qty >= 2:
                debit = qty + logistics._cost(qty, e.distance)
                credit[a] -= debit
                stock[a] -= debit
                stock[b] += qty - (qty + 31) // 32
                held[a] += debit
                remaining[donor] -= debit
                crossing[e.a,e.b] += qty
                sent[pair] += qty
    return sent, held, remaining


def _local_targets(nodes, adj, previous):
    targets = {}
    for i,r in nodes.items():
        obs = previous.get(i, {})
        unmet = obs.get('unmet', 0)
        need = obs.get('food_need', 0)
        _check(type(unmet) is int and type(need) is int and 0 <= unmet <= need
               and type(obs.get('soil_delta', 0)) is int, "invalid prior local evidence")
        # Local reserve for one soil treatment and/or one road kit supporting repeated ration deliveries.
        soil = int(obs.get('soil_delta', 0) < 0)
        road = int(bool(adj[i]) and unmet > 0 and 20 * unmet >= need)
        cap = _bounds(r.population)[1]
        targets[i] = {'food':min(cap['food']//2, unmet),
                      'ore':min(cap['ore'], 2*soil + 6*road),
                      'tools':min(cap['tools'], 2*soil + 4*road)}
    return targets


def _ledger(nodes, depots, capacity, edges, trips, requests, balances, budgets):
    incoming, outgoing = defaultdict(_zero), defaultdict(_zero)
    fees, aid, local = Counter(), Counter(), Counter()
    for s in trips:
        incoming[s['target']][s['good']] += s['quantity']
        outgoing[s['source']][s['good']] += s['quantity']
        fees[s['source']] += s['cost_food']
        bucket = local if s['purpose'] == 'domestic_reserve' else aid
        bucket[s['owner']] += s['cost_food']
    return {
        'nodes':[dict(id=i,owner=r.owner,opening=depots[i].copy(),closing=balances[i].copy(),
                      imports=incoming[i],exports=outgoing[i],cost_food=fees[i]) for i,r in sorted(nodes.items())],
        'roads':[dict(a=a,b=b,capacity_before=q,used=q-edges[a,b]['remaining'],remaining=edges[a,b]['remaining'])
                 for (a,b),q in sorted(capacity.items())],
        'countries':[dict(owner=n,aid_budget=q,aid_freight_food=aid[n],domestic_freight_food=local[n])
                     for n,q in sorted(budgets.items())],
        'requests':requests, 'shipments':trips, 'cost_food':sum(fees.values())}


class _Transfers:
    def __init__(self, nodes, edges, adj, paths, links, depots, ctx, previous):
        self.nodes, self.edges, self.adj, self.paths, self.links = nodes,edges,adj,paths,links
        self.stock = {i:g.copy() for i,g in depots.items()}
        self.credit = {i:g.copy() for i,g in depots.items()}
        self.budgets, self.laws, self.history = _policy(ctx, nodes)
        self.left = self.budgets.copy()
        self.targets = _local_targets(nodes, adj, previous)
        self.previous = previous
        self.trips, self.requests = [], []
        self.food = {i:g['food'] for i,g in depots.items()}
        self.forecast = _preview(nodes, links, self.laws, self.food, self.left)

    def project(self, a, b, qty, fee):
        food = self.food.copy()
        food[a] -= qty + fee
        food[b] += qty
        return _preview(self.nodes, self.links, self.laws, food, self.left)

    def quantity(self, path, good, deficit, purpose, recipient, reasons):
        a,b = path[0],path[-1]
        owner = self.nodes[a].owner
        route = [self.edges[logistics._edge(x,y)] for x,y in zip(path,path[1:])]
        def charge(q):
            return sum(logistics._cost(q,e['distance']) for e in route)
        sent, held, uncommitted = self.forecast
        protected = self.targets[a]
        available_food = self.credit[a]['food'] - max(protected['food'], held[a])
        available_good = self.credit[a][good] - protected[good]
        limit = min(deficit,available_good,*(e['remaining'] for e in route))
        if limit <= 0 or available_food <= 0:
            reasons.add('source_reserve_or_stock')
            return 0
        limit = _maximum(limit,lambda q: charge(q) + (q if good=='food' else 0) <= available_food)
        if not limit:
            reasons.add('source_freight')
            return 0
        if purpose == 'domestic_reserve':
            return limit
        # Leave existing border invoices payable. Only freight is appropriated in domestic custody.
        limit = _maximum(limit, lambda q:charge(q) <= uncommitted[owner])
        if not limit:
            reasons.add('aid_budget')
            return 0
        if purpose == 'forward_aid':
            return limit
        pair = owner,recipient
        # New border invoice + real internal fees must fit Q. Never reposition more meals than
        # needed for the marginal dispatch, including the border's own integer freight.
        def funded(q):
            return charge(q) <= self.project(a,b,q,charge(q))[2][owner]
        limit = _maximum(limit, funded)
        if not limit:
            reasons.add('aid_budget')
            return 0
        max_sent = self.project(a,b,limit,charge(limit))[0][pair]
        if max_sent <= sent[pair]:
            reasons.add('no_additional_border_dispatch')
            return 0
        unused = _maximum(limit, lambda q:self.project(a,b,q,charge(q))[0][pair] < max_sent)
        return min(unused+1,limit)

    def request(self, target, good, level, purpose, recipient, evidence):
        owner = self.nodes[target].owner
        opening = self.stock[target][good]
        reasons = set()
        level = min(level,_bounds(self.nodes[target].population)[1][good])
        while self.stock[target][good] < level:
            found_path = False
            for path in logistics._routes(target,self.adj,self.edges):
                found_path = True
                qty = self.quantity(path,good,level-self.stock[target][good],purpose,recipient,reasons)
                if not qty:
                    continue
                a = path[0]
                trip = logistics._shipment(path,good,qty,self.edges,self.paths)
                fee = trip['cost_food']
                aid_fee = fee if purpose != 'domestic_reserve' else 0
                self.trips.append(dict(**trip,owner=owner,purpose=purpose,recipient=recipient,
                    request_id=len(self.requests),source_before=self.stock[a].copy(),
                    source_credit_before=self.credit[a].copy(),target_before=self.stock[target].copy(),
                    aid_freight_allowance_before=self.left[owner],
                    aid_freight_allowance_after=self.left[owner]-aid_fee))
                self.stock[a][good] -= qty
                self.credit[a][good] -= qty
                self.stock[target][good] += qty
                self.stock[a]['food'] -= fee
                self.credit[a]['food'] -= fee
                for x,y in zip(path,path[1:]):
                    self.edges[logistics._edge(x,y)]['remaining'] -= qty
                if purpose != 'domestic_reserve':
                    self.left[owner] -= fee
                self.food[a] = self.stock[a]['food']
                self.food[target] = self.stock[target]['food']
                self.forecast = _preview(self.nodes,self.links,self.laws,self.food,self.left)
                break
            else:
                if not found_path:
                    reasons.add('no_residual_route')
                break
        close = self.stock[target][good]
        self.requests.append(dict(request_id=len(self.requests),owner=owner,region=target,good=good,
                                  purpose=purpose,recipient=recipient,evidence=evidence,
                                  target=level,opening=opening,closing=close,unfilled=max(0,level-close),
                                  observed_limits=sorted(reasons) if close<level else []))

    def run(self, emergency, forward):
        if emergency:
            for pair,authorized in self.laws.items():
                for a,b,e in self.links.get(pair, ()):
                    sent,held,_ = self.forecast
                    gap = authorized - sent[pair]
                    if gap <= 0:
                        break
                    space = max(0,self.nodes[b].population//4-self.food[b])
                    potential = min(gap,e.capacity,(32*space+31)//31)
                    if potential:
                        level = held[a] + potential + logistics._cost(potential,e.distance)
                        self.request(a,'food',level,'emergency_aid',pair[1],dict(
                            approved=authorized,forecast_sent=sent[pair],forecast_gross_held=held[a],
                            foreign_region=b,foreign_open_space=space,crossing_capacity=e.capacity))
        if forward:
            for pair,signal in sorted(self.history.items()):
                if not signal:
                    continue
                routes = self.links.get(pair, ())
                if routes:
                    a,_,edge = routes[0]
                    # One reserve per foreign partner. Half of last observed request/undelivered aid.
                    amount = min(signal//2,edge.capacity,self.nodes[a].population//16,self.budgets[pair[0]])
                    if amount >= 2:
                        self.request(a,'food',amount,'forward_aid',pair[1],dict(
                            prior_signal=signal,planning_budget=self.budgets[pair[0]],crossing_capacity=edge.capacity))
            for good in GOODS:
                sites = sorted(self.nodes,key=lambda i:(self.stock[i][good]-self.targets[i][good],i))
                for i in sites:
                    if self.stock[i][good] < self.targets[i][good]:
                        old = self.previous.get(i,{})
                        self.request(i,good,self.targets[i][good],'domestic_reserve',None,dict(
                            prior_unmet=old.get('unmet',0),prior_food_need=old.get('food_need',0),
                            prior_soil_delta=old.get('soil_delta',0),has_domestic_road=bool(self.adj[i])))


def _plan(regions,roads,borders,depots,capacity,ctx,previous,width,emergency,forward):
    _check(type(emergency) is bool and type(forward) is bool, "invalid domestic transport switches")
    network = _network(regions,roads,borders,depots,capacity,width)
    planner = _Transfers(*network,depots,ctx,previous)
    planner.run(emergency,forward)
    nodes, edges, *_ = network
    return _ledger(nodes,depots,capacity,edges,planner.trips,planner.requests,planner.stock,planner.budgets)


def _audit(regions,roads,borders,depots,capacity,ctx,previous,trace,width,emergency,forward):
    nodes,edges,adj,paths,links = _network(regions,roads,borders,depots,capacity,width)
    budgets,laws,history = _policy(ctx,nodes)
    targets = _local_targets(nodes,adj,previous)
    balances = {i:g.copy() for i,g in depots.items()}
    source_credit = {i:g.copy() for i,g in depots.items()}
    allowance = budgets.copy()
    stage = -1
    for trip in trace['shipments']:
        a,b,good,q = (trip[k] for k in ('source','target','good','quantity'))
        purpose,recipient = trip['purpose'],trip['recipient']
        _check(good in GOODS and a in nodes and b in nodes and a!=b and purpose in
               ('emergency_aid','forward_aid','domestic_reserve'), "unknown public cargo or endpoint")
        index = ('emergency_aid','forward_aid','domestic_reserve').index(purpose)
        _check(index >= stage, "misordered domestic dispatch")
        stage = index
        owner = nodes[a].owner
        pair = owner,recipient
        if index<2:
            _check(good=='food' and any(s==b for s,_,_ in links.get(pair, ()))
                   and ((emergency and index==0 and laws.get(pair,0)>0)
                        or (forward and index==1 and history.get(pair,0)>0)), "unjustified foreign aid positioning")
        else:
            _check(forward and recipient is None and balances[b][good]+q<=targets[b][good],
                   "unjustified domestic reserve shipment")
        fee = _audit_trip(trip,nodes,edges,paths)
        rid = trip['request_id']
        _check(type(rid) is int and 0<=rid<len(trace['requests']), "unlinked shipment")
        request = trace['requests'][rid]
        _check((request['request_id'],request['purpose'],request['region'],request['owner'],request['good'],
                request['recipient'])==(rid,purpose,b,owner,good,recipient), "false request reference")
        _check(trip['source_before']==balances[a] and trip['target_before']==balances[b]
               and trip['source_credit_before']==source_credit[a], "false local funding evidence")
        _check(trip['aid_freight_allowance_before']==allowance[owner], "incorrect opening aid budget")
        if index < 2:
            allowance[owner] -= fee
        _check(trip['aid_freight_allowance_after']==allowance[owner]>=0, "incorrect closing aid budget")
        source_credit[a][good] -= q
        source_credit[a]['food'] -= fee
        balances[a][good] -= q
        balances[a]['food'] -= fee
        balances[b][good] += q
        _check(min(source_credit[a].values())>=0 and balances[b][good]<=_bounds(nodes[b].population)[1][good],
               "re-export, unfunded shipment or warehouse overflow")
    expected = _ledger(nodes,depots,capacity,edges,trace['shipments'],trace['requests'],balances,budgets)
    _check(trace==expected, "inventory, freight, national or road posting mismatch")
    _check(all(r['aid_freight_food']<=r['aid_budget'] for r in trace['countries']), "national aid overrun")


def audit_depot_supply(regions, roads, borders, opening_depots, remaining_capacity, context, previous,
                       trace, *, width, emergency, forward):
    """Rewalk tile geometry and funding, then verify the recorded choices against opening evidence."""
    _audit(regions,roads,borders,opening_depots,remaining_capacity,context,previous,trace,width,emergency,forward)
    expected = _plan(regions,roads,borders,opening_depots,remaining_capacity,context,previous,width,emergency,forward)
    _check(expected==trace, "request evidence or dispatch differs from deterministic ordering")


def execute_depot_supply(regions, roads, borders, depots, remaining_capacity, context, previous, *,
                         width, emergency, forward):
    """Deliver real warehouse goods and return the residual shared with relief and private freight."""
    trace = _plan(regions,roads,borders,depots,remaining_capacity,context,previous,width,emergency,forward)
    _audit(regions,roads,borders,depots,remaining_capacity,context,previous,trace,width,emergency,forward)
    for row in trace['nodes']:
        depots[row['id']] = row['closing'].copy()
    return trace, {(r['a'],r['b']):r['remaining'] for r in trace['roads']}
