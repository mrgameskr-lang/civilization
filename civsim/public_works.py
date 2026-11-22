"""In-kind road service, construction, soil work and ration deliveries on domestic roads."""

from dataclasses import replace

from . import logistics
from .model import GOODS


ROAD_BONUS = 48
ROAD_LIMIT = 3
# Material carts travel as separate loads. Labor is reserved at the work site.
RECIPES = {"service": (1, 1, 1), "build": (6, 4, 6), "soil": (2, 2, 4)}


def _check(ok, message):
    if not ok:
        raise ValueError(f"public works: {message}")


def _count(q):
    return type(q) is int and q >= 0


def _opening(regions, roads, depots, width):
    _check(type(width) is int and width > 0, "physical map width is required")
    nodes = {r.id: r for r in regions}
    _check(set(depots) == set(nodes), "missing or unknown depot")
    for stock in depots.values():
        _check(set(stock) == set(GOODS) and all(_count(q) for q in stock.values()), "invalid public inventory")
    _, edges, adj, paths = logistics._open(regions, roads, "limited", width)
    return nodes, edges, adj, paths


def _road_state(edges, road_units):
    _check(set(road_units) <= set(edges) and all(_count(q) and q <= ROAD_LIMIT for q in road_units.values()),
           "invalid opening road units")
    state = {}
    for key, edge in edges.items():
        units = road_units.get(key, 0)
        total = edge["capacity"] + units * ROAD_BONUS
        edge["remaining"] = total
        state[key] = {"a": key[0], "b": key[1], "opening_units": units, "maintained": 0, "built": 0,
                      "capacity": total, "remaining": total}
    return state


def _finish_roads(state, edges):
    rows = []
    for key, e in state.items():
        rows.append({**e, "decayed": e["opening_units"] - e["maintained"],
                     "closing_units": e["maintained"] + e["built"], "remaining": edges[key]["remaining"]})
    return rows


def residual_roads(roads, capacity):
    """Fresh Road values for the existing civilian ship() API, including closed edges."""
    _check(set(capacity) == {(e.a,e.b) for e in roads} and all(_count(q) for q in capacity.values()),
           "invalid residual road set")
    return [replace(e, capacity=capacity[e.a,e.b]) for e in roads]


def _budget(decision):
    budget = decision["budget"]
    _check(all(_count(budget.get(k)) for k in (*GOODS,"workers","admin_units")), "invalid discretionary budget")
    return budget


def _target(decision):
    if decision["action"] == "road":
        return tuple(decision["target_edge"] if "target_edge" in decision else decision["target"])
    return decision["target_region"] if "target_region" in decision else decision["target"]


def _fee(q, distance):
    return (q * distance + 99) // 100


def _soil(farmland, soil):
    treated = min(12, farmland)
    gain = min(max(0, 1150-soil), 24 * treated // max(1, farmland))
    return treated, gain


def _works_nodes(nodes, depots, balances, soil, workers):
    return [{"id": i, "owner": r.owner, "depot_open": depots[i].copy(), "depot_close": balances[i].copy(),
             "soil_open": r.soil, "soil_close": soil[i], "workers_reserved": workers[i]}
            for i,r in sorted(nodes.items())]


def _project(action, owner, source, target, edge, number, treated=0, gain=0):
    ore, tools, workers = RECIPES[action]
    return {"project_id": number, "action": action, "owner": owner, "source": source, "target": target,
            "edge": list(edge) if edge is not None else None, "workers": workers,
            "used": {"food": 0, "ore": ore, "tools": tools}, "treated_tiles": treated, "soil_gain": gain}


def _cart(source, target, good, qty, edges, paths, project):
    trip = logistics._shipment((source,target), good, qty, edges, paths)
    return {**trip, "owner": project["owner"], "purpose": project["action"], "project_id": project["project_id"]}


def execute_works(regions, roads, depots, road_units, decisions, *, width, withheld=None):
    """Post standing service and one approved discretionary project per country; validate before mutation."""
    nodes, edges, _, paths = _opening(regions, roads, depots, width)
    balances = {i: stock.copy() for i,stock in depots.items()}
    workers = dict.fromkeys(nodes, 0)
    withheld = {} if withheld is None else withheld
    _check(withheld.keys()<=nodes.keys() and all(_count(n) and n<=nodes[i].population//2 for i,n in withheld.items()),
           "civic withdrawal exceeds site's available labor")
    soil = {i:r.soil for i,r in nodes.items()}
    state = _road_state(edges, road_units)
    projects, trips, skipped = [], [], []

    def road_project(action, key, budget=None):
        edge = edges[key]
        ore, tools, labor = RECIPES[action]
        freight = _fee(ore,edge["distance"]) + _fee(tools,edge["distance"])
        if edge["remaining"] < ore+tools:
            return False
        if budget is not None and (budget["admin_units"] < 1 or budget["workers"] < labor or budget["food"] < freight
                                   or budget["ore"] < ore or budget["tools"] < tools):
            return False
        a,b = key
        feasible = [(s,t) for s,t in ((a,b),(b,a)) if balances[s]["food"] >= freight
                    and balances[s]["ore"] >= ore and balances[s]["tools"] >= tools
                    and nodes[t].population//2-workers[t]-withheld.get(t,0) >= labor]
        if not feasible:
            return False
        s,t = max(feasible, key=lambda pair: (balances[pair[0]]["ore"] + balances[pair[0]]["tools"], -pair[0]))
        project = _project(action, nodes[s].owner, s, t, key, len(projects))
        for good,qty in (("ore",ore),("tools",tools)):
            trip = _cart(s,t,good,qty,edges,paths,project)
            trips.append(trip)
            balances[s][good] -= qty
            balances[s]["food"] -= trip["cost_food"]
            edge["remaining"] -= qty
        workers[t] += labor
        state[key]["maintained" if action=="service" else "built"] += 1
        projects.append(project)
        return True

    for key, e in state.items():
        for _ in range(e["opening_units"]):
            if not road_project("service",key):
                break
    owners = {r.owner for r in regions}
    _check(set(decisions) <= owners, "unknown decision owner")
    for owner, decision in sorted(decisions.items()):
        action = decision["action"]
        if action not in ("road","soil"):
            continue
        budget, target = _budget(decision), _target(decision)
        if action == "road":
            _check(target in edges and nodes[target[0]].owner == owner, "foreign or nonexistent road selection")
            built = state[target]["maintained"] < ROAD_LIMIT and road_project("build",target,budget)
            if not built:
                skipped.append({"owner":owner, "action":action, "target":list(target)})
        else:
            _check(target in nodes and nodes[target].owner == owner, "foreign or nonexistent soil selection")
            ore, tools, labor = RECIPES["soil"]
            r = nodes[target]
            treated,gain = _soil(r.farmland, soil[target])
            if (gain == 0 or budget["admin_units"] < 1 or budget["workers"] < labor
                    or min(budget["ore"], balances[target]["ore"]) < ore
                    or min(budget["tools"], balances[target]["tools"]) < tools
                    or r.population//2 - workers[target] - withheld.get(target,0) < labor):
                skipped.append({"owner":owner,"action":action,"target":target})
                continue
            project = _project("soil",owner,target,target,None,len(projects),treated,gain)
            balances[target]["ore"] -= ore
            balances[target]["tools"] -= tools
            workers[target] += labor
            soil[target] += gain
            projects.append(project)
    rows = _finish_roads(state, edges)
    trace = {"projects": projects, "shipments": trips, "roads": rows, "skipped": skipped,
             "nodes": _works_nodes(nodes, depots, balances, soil, workers),
             "cost_food": sum(s["cost_food"] for s in trips)}
    audit_works(regions,roads,depots,road_units,decisions,trace,width=width,withheld=withheld)
    for i,r in nodes.items():
        depots[i] = balances[i]
        r.soil = soil[i]
    return trace, {(e["a"],e["b"]):e["closing_units"] for e in rows}, {
        key:e["remaining"] for key,e in edges.items()}, workers


def _audit_trip(s, nodes, edges, paths):
    """Walk trusted geometry; reconstruct orientation, per-leg fees and residual shared capacity."""
    path, qty = s["path"], s["quantity"]
    _check(isinstance(path,list) and path and len(set(path)) == len(path)
           and all(i in nodes and nodes[i].owner==s["owner"] for i in path), "invalid domestic path")
    _check(_count(qty) and qty > 0 and (path[0],path[-1]) == (s["source"],s["target"]),
           "invalid quantity or endpoints")
    tiles, legs, cost, distance = [nodes[path[0]].seat], [], 0, 0
    for a,b in zip(path,path[1:]):
        key = tuple(sorted((a,b)))
        _check(key in edges, "missing physical road")
        edge = edges[key]
        leg_distance = edge["distance"]
        charge = (qty*leg_distance+99)//100
        oriented = paths[key] if a<b else paths[key][::-1]
        tiles.extend(oriented[1:])
        legs.append({"a":a,"b":b,"distance":leg_distance,"cost_food":charge})
        cost += charge
        distance += leg_distance
        edge["remaining"] -= qty
        _check(edge["remaining"]>=0, "public loads exceed shared road capacity")
    _check(s["tile_path"]==tiles and s["legs"]==legs and s["distance"]==distance and s["cost_food"]==cost,
           "incorrect physical tiles, freight, distance, or leg posting")
    return cost


def audit_works(regions, roads, depots, road_units, decisions, trace, *, width, withheld=None):
    nodes, edges, _, paths = _opening(regions, roads, depots, width)
    withheld = {} if withheld is None else withheld
    _check(withheld.keys()<=nodes.keys() and all(_count(n) and n<=nodes[i].population//2 for i,n in withheld.items()),
           "invalid unavailable workforce")
    state = _road_state(edges, road_units)
    balances = {i: s.copy() for i,s in depots.items()}
    workers = dict.fromkeys(nodes,0)
    soil = {i:r.soil for i,r in nodes.items()}
    selected = set()
    pos = cost = 0
    construction_started = False
    for number,p in enumerate(trace["projects"]):
        action,owner,s,t = p["action"],p["owner"],p["source"],p["target"]
        _check(action in RECIPES and p["project_id"]==number and s in nodes and t in nodes
               and nodes[s].owner==nodes[t].owner==owner, "invalid project identity or location")
        ore, tools, labor = RECIPES[action]
        _check(p["used"]=={"food":0,"ore":ore,"tools":tools} and p["workers"]==labor,
               "incorrect project recipe or labor")
        workers[t] += labor
        _check(workers[t]+withheld.get(t,0)<=nodes[t].population//2, "builders spent twice or unavailable")
        project_freight = 0
        if action=="soil":
            treated,gain = _soil(nodes[t].farmland, soil[t])
            _check(s==t and p["edge"] is None and gain>0 and p["treated_tiles"]==treated and p["soil_gain"]==gain,
                   "soil area, location or gain mismatch")
            soil[t] += gain
        else:
            key = tuple(sorted((s,t)))
            _check(key in state and p["edge"]==list(key) and p["soil_gain"]==0 and p["treated_tiles"]==0,
                   "invalid road project")
            for good,qty in (("ore",ore),("tools",tools)):
                _check(pos < len(trace["shipments"]), "missing material delivery")
                trip = trace["shipments"][pos]
                pos += 1
                _check((trip["good"],trip["quantity"],trip["path"],trip["purpose"],trip["project_id"]) ==
                       (good,qty,[s,t],action,number) and trip["owner"]==owner, "incorrect construction cargo")
                fee = _audit_trip(trip,nodes,edges,paths)
                project_freight += fee
                balances[s]["food"] -= fee
                balances[s][good] -= qty
                _check(min(balances[s].values())>=0, "depot spent unfunded freight or materials")
                balances[t][good] += qty
            field = "maintained" if action=="service" else "built"
            state[key][field] += 1
            _check(state[key]["maintained"]<=state[key]["opening_units"] and
                   state[key]["maintained"]+state[key]["built"]<=ROAD_LIMIT,"invalid unit lifetime or cap")
        balances[t]["ore"] -= ore
        balances[t]["tools"] -= tools
        _check(min(balances[t].values())>=0,"construction material absent at work site")
        cost += project_freight
        if action == "service":
            _check(not construction_started,"maintenance funded after discretionary construction")
        else:
            construction_started = True
            decision = decisions.get(owner,{})
            _check(owner not in selected and decision.get("action")==("road" if action=="build" else "soil"),
                   "unapproved discretionary project")
            selected.add(owner)
            _check(_target(decision)==(key if action=="build" else t),"unapproved project target")
            b = _budget(decision)
            _check(b["admin_units"]>=1 and b["workers"]>=labor and b["food"]>=project_freight
                   and b["ore"]>=ore and b["tools"]>=tools,"project exceeds public budget")
    expected_skipped = []
    for owner,d in sorted(decisions.items()):
        if d["action"] in ("road","soil") and owner not in selected:
            target = _target(d)
            expected_skipped.append({"owner":owner,"action":d["action"],
                                     "target":list(target) if d["action"]=="road" else target})
    _check(pos==len(trace["shipments"]) and trace["cost_food"]==cost and trace["skipped"]==expected_skipped,
           "unlinked cargo, freight, or decision")
    _check(trace["nodes"]==_works_nodes(nodes,depots,balances,soil,workers)
           and trace["roads"]==_finish_roads(state,edges),"works account or capacity mismatch")


def _relief_open(nodes, edges, capacity, admin):
    _check(set(capacity)==set(edges) and all(_count(q) for q in capacity.values()),"incomplete road residuals")
    _check(set(admin)=={r.owner for r in nodes.values()} and all(_count(q) for q in admin.values()),
           "invalid relief administration limits")
    for key,e in edges.items():
        _check(capacity[key]<=e["capacity"]+ROAD_LIMIT*ROAD_BONUS,"road residual exceeds maximum physical capacity")
        e["remaining"] = capacity[key]


def _relief_rows(nodes, depots, balances, food, edges, capacity, admin, used):
    return {
        "nodes":[{"id":i,"owner":r.owner,"depot_open":depots[i].copy(),"depot_close":balances[i].copy(),
                  "private_food_open":r.stock["food"],"private_food_close":food[i]} for i,r in sorted(nodes.items())],
        "roads":[{"a":k[0],"b":k[1],"capacity":capacity[k],"remaining":e["remaining"]} for k,e in edges.items()],
        "admin":[{"owner":i,"limit":admin[i],"used":used[i]} for i in sorted(admin)],
    }


def _affordable_rations(funds, maximum, distances):
    low, high = 0, min(maximum,funds)
    while low < high:
        q = (low+high+1)//2
        if q + sum(_fee(q,d) for d in distances) <= funds:
            low = q
        else:
            high = q-1
    return low


def execute_relief(regions, roads, depots, decisions, remaining_capacity, admin_limits, *, width):
    """Deliver food locally first, then along funded physical routes; return the civilian residual."""
    nodes,edges,adj,paths = _opening(regions,roads,depots,width)
    _relief_open(nodes,edges,remaining_capacity,admin_limits)
    _check(set(decisions)<=set(admin_limits),"unknown relief decision owner")
    balances = {i:s.copy() for i,s in depots.items()}
    food = {i:r.stock["food"] for i,r in nodes.items()}
    used = dict.fromkeys(admin_limits,0)
    trips=[]
    for owner,d in sorted(decisions.items()):
        if d["action"]!="relief":
            continue
        t = _target(d)
        _check(t in nodes and nodes[t].owner==owner and _count(d["quantity"]), "invalid relief target or quantity")
        b = _budget(d)
        remaining_food = b["food"]
        need = min(d["quantity"],admin_limits[owner],max(0,nodes[t].population-food[t])) if b["admin_units"] else 0
        while need > 0:
            # Recompute feasible routes after every dispatch, as in domestic civilian shipping.
            paths_to_buyer = ((t,),) if balances[t]["food"] else logistics._routes(t,adj,edges)
            for path in paths_to_buyer:
                s = path[0]
                limits = [edges[tuple(sorted(pair))] for pair in zip(path,path[1:])]
                maximum = min([need, *(e["remaining"] for e in limits)])
                q = _affordable_rations(min(remaining_food,balances[s]["food"]),maximum,
                                        [e["distance"] for e in limits])
                if not q:
                    continue
                if s==t:
                    trip = {"source":s,"target":t,"good":"food","quantity":q,"path":[t],
                            "tile_path":[nodes[t].seat],"legs":[],"cost_food":0,"distance":0}
                else:
                    trip = logistics._shipment(path,"food",q,edges,paths)
                trips.append({**trip,"owner":owner,"purpose":"relief"})
                amount = q + trip["cost_food"]
                balances[s]["food"] -= amount
                remaining_food -= amount
                food[t] += q
                need -= q
                used[owner] += q
                for e in limits:
                    e["remaining"] -= q
                break
            else:
                break
    trace = {**_relief_rows(nodes,depots,balances,food,edges,remaining_capacity,admin_limits,used),
             "shipments":trips, "cost_food":sum(s["cost_food"] for s in trips),"delivered":sum(used.values())}
    audit_relief(regions,roads,depots,decisions,remaining_capacity,admin_limits,trace,width=width)
    for i,r in nodes.items():
        r.stock["food"] = food[i]
        depots[i] = balances[i]
    return trace,{k:e["remaining"] for k,e in edges.items()}


def audit_relief(regions, roads, depots, decisions, remaining_capacity, admin_limits, trace, *, width):
    nodes,edges,_,paths = _opening(regions,roads,depots,width)
    _relief_open(nodes,edges,remaining_capacity,admin_limits)
    balances = {i:s.copy() for i,s in depots.items()}
    food = {i:r.stock["food"] for i,r in nodes.items()}
    used, spent = dict.fromkeys(admin_limits,0), dict.fromkeys(admin_limits,0)
    cost = 0
    for trip in trace["shipments"]:
        i,owner = trip["target"],trip["owner"]
        d = decisions.get(owner,{})
        _check(trip["purpose"]=="relief" and trip["good"]=="food" and d.get("action")=="relief"
               and i==_target(d) and i in nodes and nodes[i].owner==owner,"unauthorized relief recipient")
        q, s = trip["quantity"], trip["source"]
        fee = _audit_trip(trip,nodes,edges,paths)
        b = _budget(d)
        used[owner] += q
        spent[owner] += q+fee
        food[i] += q
        balances[s]["food"] -= q+fee
        _check(b["admin_units"]>=1 and used[owner]<=min(d["quantity"],admin_limits[owner])
               and spent[owner]<=b["food"] and balances[s]["food"]>=0 and food[i]<=nodes[i].population,
               "unfunded relief, excess rations, or throughput overflow")
        cost += fee
    expected = _relief_rows(nodes,depots,balances,food,edges,remaining_capacity,admin_limits,used)
    _check(all(trace[k]==v for k,v in expected.items()) and trace["cost_food"]==cost
           and trace["delivered"]==sum(used.values()),"relief material or throughput balance mismatch")
