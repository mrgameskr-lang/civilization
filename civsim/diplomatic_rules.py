"""6.0A. Opening bilateral choices and annual diplomatic memory backed by physical receipts."""
from copy import deepcopy
from itertools import combinations

from .audit import BalanceError
from .collective_rules import ACTIVE
from .competition_rules import PLATFORMS
from .fiscal_policy import ACTIONS
from .model import GOODS
from .political_rules import GROUPS


def _check(ok, message):
    if not ok:
        raise BalanceError("diplomacy: "+message)


def _rate(x,n):
    return min(1000,1000*max(0,x)//n) if n else 0


COUNTS = ("trade_value","trade_freight","trades","migrants","aid_sent","aid_received","aid_freight","aid_handling",
          "trade_opportunity","trade_denied","migration_denied_exit","migration_denied_entry","access_kept",
          "agreement_breach","pact_proposals","pact_rejections","aid_request","aid_offer","aid_quantity",
          "aid_request_rejected","aid_offer_rejected","all_import_value","all_export_value","source_food_need")
RATES = ("import_dependence","export_exposure","food_import_share")


def _empty_flow(source,target):
    return {"source":source,"target":target,"goods":dict.fromkeys(GOODS,0),**dict.fromkeys(COUNTS+RATES,0)}


def _empty_pair(a,b):
    return {"year":0,"trust":500,"relation":0,"tension":0,"cooperation":0,"reciprocity":0,
            "agreement_start":0,"agreement_end":0,"breach_streak":0,"cooldown_until":0,
            "signed_total":0,"breached_total":0,
            "last":[_empty_flow(a,b),_empty_flow(b,a)],"totals":[_empty_flow(a,b),_empty_flow(b,a)]}


def initial_pairs(world):
    return {(a,b):_empty_pair(a,b) for a,b in combinations(sorted(n.id for n in world.nations),2)}


def _countries(region_rows, depots, political, cabinets, memory, pairs):
    out = {}
    for n in sorted(cabinets):
        places = [r for r in region_rows if r["owner"]==n]
        states = [political[r["id"]] for r in places]
        evidence = [s["evidence"] for s in states]
        p = sum(r["population"] for r in places)
        groups = {}
        for k in GROUPS:
            entries = [s["groups"][k] for s in states]
            members = sum(g["members"] for g in entries)
            groups[k] = {"members":members,
                         "support":sum(g["members"]*g["support"] for g in entries)//members if members else 500,
                         "discontent":sum(g["members"]*g["discontent"] for g in entries)//max(1,members),
                         "signals":{a:sum(g["members"]*g["signals"][a] for g in entries)//max(1,members) for a in ACTIONS}}
        stock = {g:sum(r["stock"][g] for r in places) for g in GOODS}
        depot = {g:sum(depots[r["id"]][g] for r in places) for g in GOODS}
        need = sum(e.get("food_need",0) for e in evidence)
        unmet = sum(e.get("food_unmet",0) for e in evidence)
        flows = [f for key,m in pairs.items() if n in key for f in m["last"]]
        out[n] = {"id":n,"population":p,"stock":stock,"depot":depot,"cash":sum(r["cash"] for r in places),
                  "prior_need":need,"prior_unmet":unmet,"prior_crop":sum(e.get("production",{}).get("food",0) for e in evidence),
                  "prior_pop_delta":p-need if any(s["year"] for s in states) else 0,"shortage_permille":_rate(unmet,need),
                  "party":cabinets[n]["incumbent"],"groups":groups,
                  "mobilized":sum(memory[r["id"]][k]["action"] in ACTIVE for r in places for k in GROUPS),
                  "foreign_import_value":sum(f["trade_value"] for f in flows if f["target"]==n),
                  "foreign_export_value":sum(f["trade_value"] for f in flows if f["source"]==n)}
    return list(out.values())


def _direction(n, other, old, direct, incoming, capacity, distance, arm):
    adjacent = capacity>0
    p = n["population"]
    own_need = n["prior_unmet"]
    party = PLATFORMS.get(n["party"])
    road_weight = party["road"] if party else 2
    social_weight = party["relief"] if party else 2
    industrial = n["groups"]["industry"]["signals"]["road"]
    hunger = n["groups"]["consumer"]["signals"]["relief"]
    reserve = n["groups"]["consumer"]["signals"]["reserve"]
    exp_food = direct["goods"]["food"]
    access = (incoming["trade_value"]+direct["trade_value"])//8 + 4*min(own_need,incoming["goods"]["food"])
    access += (incoming["goods"]["ore"]+2*incoming["goods"]["tools"])*industrial*road_weight//2000
    out_volume = sum(direct["goods"].values())
    observed_volume = out_volume + sum(incoming["goods"].values())
    if observed_volume:
        access = access*min(capacity,observed_volume)//observed_volume
    expected_freight = (min(out_volume,capacity)*distance+99)//100
    regular = 8*max(1,p//2000)
    history = old["relation"]*max(1,p//2000)//12
    expense = regular+direct["trade_freight"]+expected_freight+4*min(own_need,exp_food)
    score = access+history-expense
    contact = bool(direct["trades"] or incoming["trades"])
    pact = arm in ("C","D") and adjacent and contact and score>0
    # Food lost to export or scarcity at home is a political motive, not a claim on foreign stocks.
    protection = 8*min(own_need,exp_food)*(1000+hunger)//1000
    export_cost = regular+direct["trade_value"]//16
    trade_rate = 1000
    exit_rate = entry_rate = 1000
    if arm=="D" and adjacent:
        if exp_food and protection>export_cost:
            trade_rate = 500
        elif incoming["trade_denied"] and old["tension"]>=100:
            trade_rate = 750
        if direct["migrants"] and n["prior_pop_delta"]<0 and (industrial+n["groups"]["farm"]["discontent"]>=100):
            exit_rate = 750
        if direct["migrants"] and other["shortage_permille"]>=60 and other["groups"]["consumer"]["discontent"]>=40:
            entry_rate = 500
    aid_need = min(max(0,other["prior_unmet"]-other["depot"]["food"]),other["population"]//32)
    retained = p//64 + own_need//2 + p*reserve//8000
    budget = min(p//48,max(0,n["depot"]["food"]-retained))
    aid_ceiling = min(aid_need,capacity,100*budget//(100+distance))
    aid_freight_estimate = (aid_ceiling*distance+99)//100
    aid_score = other["shortage_permille"]-n["shortage_permille"]+(old["trust"]-500)//5
    aid_score += (social_weight-2)*min(100,other["shortage_permille"])//10
    aid_score -= _rate(direct["aid_freight"]+direct["aid_handling"],max(1,direct["aid_sent"]))//8
    aid_score -= _rate(aid_freight_estimate,p)
    return {"source":n["id"],"target":other["id"],"import_dependence":_rate(incoming["trade_value"],n["foreign_import_value"]),
            "export_exposure":_rate(direct["trade_value"],n["foreign_export_value"]),
            "food_import_share":_rate(incoming["goods"]["food"],n["prior_need"]),
            "border_capacity":capacity,"border_distance":distance,"expected_trade_freight":expected_freight,
            "pact_score":score,"access_value":access,"historical_value":history,"pact_cost":expense,
            "pact_willing":pact,"trade_protection_value":protection,"foregone_export_value":export_cost,
            "trade_limit_permille":trade_rate,"migration_limit_permille":exit_rate,"migration_accept_permille":entry_rate,
            "aid_need":aid_need,"aid_retained_food":retained,"aid_budget":budget,"aid_ceiling":aid_ceiling,
            "aid_freight_estimate":aid_freight_estimate,"aid_score":aid_score,
            "aid_request":0,"aid_offer":0,"aid_accepted":False,"aid_quantity":0}


def _plan_aid(pairs,countries):
    routes = [(r,d) for r in pairs if r["adjacent"] for d in r["policy"]["directions"]]
    # Each government can initiate one request and fund one offer. No country earmarks a warehouse twice.
    for recipient,n in countries.items():
        potential = [(r,d) for r,d in routes if d["target"]==recipient and d["aid_need"]>=2]
        if potential and n["shortage_permille"]>=30:
            r,d = max(potential,key=lambda rd:(rd[1]["aid_ceiling"],rd[0]["opening"]["trust"],
                                              -rd[1]["aid_freight_estimate"],-rd[1]["source"]))
            d["aid_request"] = d["aid_need"]
    for donor in countries:
        potential = [(r,d) for r,d in routes if d["source"]==donor and d["aid_ceiling"]>=2
                     and d["aid_score"]>0 and r["opening"]["trust"]>=300]
        if potential:
            r,d = max(potential,key=lambda rd:(rd[1]["aid_score"]+25*int(rd[1]["aid_request"]>0),
                                             rd[1]["aid_ceiling"],-rd[1]["target"]))
            d["aid_offer"] = d["aid_ceiling"]
    for recipient in countries:
        offers = [(r,d) for r,d in routes if d["target"]==recipient and d["aid_offer"]]
        if not offers:
            continue
        remaining = offers[0][1]["aid_need"]
        ordered = sorted(offers,key=lambda rd:(not rd[1]["aid_request"],-rd[0]["opening"]["trust"],rd[1]["source"]))
        for r,d in ordered:
            qty = min(remaining,d["aid_offer"])
            if qty>=2 and r["opening"]["trust"]>=350:
                d.update(aid_accepted=True,aid_quantity=qty)
                remaining -= qty


def _choices(year,arm,memories,countries,borders,intervention):
    by_id = {n["id"]:n for n in countries}
    links = {}
    for edge in borders:
        if edge["capacity"]>0:
            key = tuple(sorted((edge["owner_a"],edge["owner_b"])))
            capacity, distance = links.get(key,(0,edge["distance"]))
            links[key] = capacity+edge["capacity"], min(distance,edge["distance"])
    pairs = []
    for (a,b),old in sorted(memories.items()):
        _check(old["year"]==year-1,"pair history must immediately precede decision")
        capacity,distance = links.get((a,b),(0,0))
        adjacent = capacity>0
        directions = [_direction(by_id[n],by_id[o],old,old["last"][i],old["last"][1-i],capacity,distance,arm)
                      for i,(n,o) in enumerate(((a,b),(b,a)))]
        expiry = bool(old["agreement_end"] and year>old["agreement_end"])
        carried = bool(old["agreement_start"] and not expiry)
        negotiation = arm in ("C","D") and adjacent and not carried and not expiry and year>old["cooldown_until"]
        proposing = [d["source"] for d in directions if negotiation and d["pact_willing"]]
        started = len(proposing)==2
        policy = {"agreement_active":carried or started,"agreement_started":started,"agreement_expired":expiry,
                  "agreement_start":year if started else old["agreement_start"] if carried else 0,
                  "expires_after":year+4 if started else old["agreement_end"] if carried else 0,
                  "proposers":proposing,"directions":directions}
        pairs.append({"a":a,"b":b,"adjacent":adjacent,"opening":deepcopy(old),"policy":policy})
    if arm=="D":
        _plan_aid(pairs,by_id)
    if intervention is not None:
        kind = intervention.get("kind")
        if kind=="no_new_pact":
            _check(set(intervention)=={"kind","a","b"},"invalid pact intervention")
            selected = next((r for r in pairs if (r["a"],r["b"])==(intervention["a"],intervention["b"])),None)
            _check(selected and selected["policy"]["agreement_started"],"intervention requires a new bilateral agreement")
            selected["policy"].update(agreement_active=False,agreement_started=False,agreement_start=0,expires_after=0)
        else:
            _check(kind in ("open_trade","open_migration") and set(intervention)=={"kind","source","target"},
                   "invalid directional intervention")
            selected = next((d for r in pairs for d in r["policy"]["directions"]
                             if (d["source"],d["target"])==(intervention["source"],intervention["target"])),None)
            fields = ("trade_limit_permille",) if kind=="open_trade" else ("migration_limit_permille","migration_accept_permille")
            _check(selected and any(selected[k]<1000 for k in fields),"intervention requires a naturally restricted direction")
            selected.update(dict.fromkeys(fields,1000))
    return pairs


def prepare_diplomacy(sim_collective, year, arm, pairs, intervention=None):
    sim,world = sim_collective,sim_collective.world
    _check(arm in ("A","B","C","D") and type(year) is int and year==world.year+1,"invalid arm or year")
    _check(set(pairs)==set(combinations(sorted(n.id for n in world.nations),2)),"complete pair history required")
    owners = {r.id:r.owner for r in world.regions}
    borders = [{"a":e.a,"b":e.b,"owner_a":owners[e.a],"owner_b":owners[e.b],"capacity":e.capacity,"distance":e.distance}
               for e in world.borders]
    regions = [{k:getattr(r,k) for k in ("id","owner","population","stock","cash")} for r in world.regions]
    comp = sim.competition
    countries = _countries(regions,comp.political.fiscal.depots,comp.political.states,comp.cabinets,sim.memory,pairs)
    return {"year":year,"arm":arm,"countries":countries,"borders":borders,
            "intervention":deepcopy(intervention),"pairs":_choices(year,arm,pairs,countries,borders,intervention)}


def _movements(record):
    ctx = record["diplomacy"]
    owner = {r["id"]:r["owner"] for r in record["regions"]}
    flows = {(n,o):_empty_flow(n,o) for r in ctx["pairs"] for n,o in ((r["a"],r["b"]),(r["b"],r["a"]))}
    physical = ctx["physical"]
    for t in record["border_market"]["trades"]:
        f = flows[owner[t["seller"]],owner[t["buyer"]]]
        f["goods"][t["good"]] += t["quantity"]
        f["trade_value"] += t["value"]
        f["trade_freight"] += t["cost_food"]
        f["trades"] += 1
    for m in record["moves"]:
        a,b = owner[m["source"]],owner[m["target"]]
        if a!=b:
            flows[a,b]["migrants"] += m["people"]
    for t in physical["trade_attempts"]:
        f = flows[owner[t["source"]],owner[t["target"]]]
        f["trade_opportunity"] += t["feasible"]
        f["trade_denied"] += t["denied"]
    for m in physical["migration_attempts"]:
        a,b = owner[m["source"]],owner[m["target"]]
        if a!=b:
            flows[a,b]["migration_denied_exit"] += m["denied_exit"]
            flows[a,b]["migration_denied_entry"] += m["denied_entry"]
    for h in physical["aid"]["shipments"]:
        a,b = owner[h["source"]],owner[h["target"]]
        _check((a,b)==(h["donor"],h["recipient"]),"foreign aid warehouse owner")
        f = flows[a,b]
        f["aid_sent"] += h["quantity"]
        f["aid_received"] += h["received"]
        f["aid_freight"] += h["cost_food"]
        f["aid_handling"] += h["handling_food"]
    imports, exports, needs = {},{},{}
    for (src,dst),f in flows.items():
        exports[src] = exports.get(src,0)+f["trade_value"]
        imports[dst] = imports.get(dst,0)+f["trade_value"]
    for r in record["regions"]:
        n = r["owner"]
        needs[n] = needs.get(n,0)+r["consumption"]["food_need"]
    for (src,dst),f in flows.items():
        f.update(all_import_value=imports[src],all_export_value=exports[src],source_food_need=needs[src])
        _dependence(f,flows[dst,src])
    return flows


def _dependence(f,incoming):
    f["import_dependence"] = _rate(incoming["trade_value"],f["all_import_value"])
    f["export_exposure"] = _rate(f["trade_value"],f["all_export_value"])
    f["food_import_share"] = _rate(incoming["goods"]["food"],f["source_food_need"])


def _close_pair(row, flows, year):
    a,b = row["a"],row["b"]
    p,old = row["policy"],row["opening"]
    events = []
    def event(kind,n=a,o=b,quantity=1):
        events.append({"kind":kind,"a":a,"b":b,"source":n,"target":o,"quantity":quantity})
    for n in p["proposers"]:
        event("pact_proposed",n,b if n==a else a)
    if len(p["proposers"])==1:
        n = p["proposers"][0]
        event("pact_rejected",b if n==a else a,n)
    if p["agreement_started"]:
        event("pact_started")
    if p["agreement_expired"]:
        event("pact_expired")
    last,totals = [],[]
    for i,d in enumerate(p["directions"]):
        n,o = d["source"],d["target"]
        f = flows[n,o]
        f["pact_proposals"] = int(n in p["proposers"])
        f["pact_rejections"] = int(p["proposers"]==[o])
        for key in ("aid_request","aid_offer","aid_quantity"):
            f[key] = d[key]
        f["aid_request_rejected"] = int(d["aid_request"]>0 and not d["aid_offer"])
        f["aid_offer_rejected"] = int(d["aid_offer"]>0 and not d["aid_accepted"])
        f["agreement_breach"] = int(p["agreement_active"] and d["trade_limit_permille"]<1000 and f["trade_denied"]>0)
        f["access_kept"] = int(p["agreement_active"] and f["trade_opportunity"]>0 and not f["trade_denied"])
        if d["aid_request"]:
            event("aid_requested",o,n,d["aid_request"])
        if d["aid_offer"]:
            event("aid_offered",n,o,d["aid_offer"])
        if f["aid_request_rejected"]:
            event("aid_request_rejected",n,o,d["aid_request"])
        if f["aid_offer_rejected"]:
            event("aid_offer_rejected",o,n,d["aid_offer"])
        if d["aid_accepted"]:
            event("aid_accepted",o,n,d["aid_quantity"])
        if f["aid_received"]:
            event("aid_delivered",n,o,f["aid_received"])
        shortfall = d["aid_quantity"]-f["aid_sent"]
        _check(shortfall>=0,"aid exceeded bilateral assent")
        if shortfall:
            event("aid_shortfall",n,o,shortfall)
        if d["trade_limit_permille"]<1000:
            event("trade_restricted",n,o,d["trade_limit_permille"])
        if d["migration_limit_permille"]<1000:
            event("migration_exit_restricted",n,o,d["migration_limit_permille"])
        if d["migration_accept_permille"]<1000:
            event("migration_entry_restricted",o,n,d["migration_accept_permille"])
        if f["agreement_breach"]:
            event("pact_breached",n,o,f["trade_denied"])
        t = old["totals"][i]
        totals.append({"source":n,"target":o,"goods":{g:t["goods"][g]+f["goods"][g] for g in GOODS},
                       **{key:t[key]+f[key] for key in COUNTS}})
        last.append(f)
    _dependence(totals[0],totals[1])
    _dependence(totals[1],totals[0])
    breaches = sum(f["agreement_breach"] for f in last)
    streak = old["breach_streak"]+1 if breaches else 0
    terminated = streak>=2
    if terminated:
        event("pact_terminated")
    benefit = [f["trade_value"]+8*(f["aid_received"]+f["migrants"]) for f in last]
    reciprocal = _rate(2*min(benefit),sum(benefit))
    trade_sides = sum(bool(f["trades"]) for f in last)
    helpful = (180*trade_sides + 120*int(any(f["migrants"] for f in last)) +
               300*int(any(f["aid_received"] for f in last)) + 120*int(any(f["access_kept"] for f in last)))
    strain = min(1000,300*int(any(f["trade_denied"] for f in last)) +
                 200*int(any(f["migration_denied_exit"]+f["migration_denied_entry"] for f in last)) +
                 300*int(bool(breaches)) + 100*int(any(f["aid_quantity"]>f["aid_sent"] for f in last)))
    coop = (3*old["cooperation"]+helpful)//4
    tension = (3*old["tension"]+strain)//4
    reciprocity = (3*old["reciprocity"]+reciprocal)//4
    trust = (3*old["trust"]+max(0,min(1000,500+helpful//3+reciprocal//6-strain//2)))//4
    relation = max(-1000,min(1000,trust-500+(coop+reciprocity)//4-tension//2))
    closing = {"year":year,"trust":trust,"relation":relation,"tension":tension,"cooperation":coop,"reciprocity":reciprocity,
               "agreement_start":0 if terminated else p["agreement_start"],"agreement_end":0 if terminated else p["expires_after"],
               "breach_streak":0 if terminated else streak,"cooldown_until":year+2 if terminated else old["cooldown_until"],
               "signed_total":old["signed_total"]+int(p["agreement_started"]),"breached_total":old["breached_total"]+breaches,
               "last":deepcopy(last),"totals":totals}
    return {"directions":last},closing,events


def finish_diplomacy(record):
    ctx = record["diplomacy"]
    flows, events = _movements(record),[]
    for row in ctx["pairs"]:
        row["flows"],row["closing"],pair_events = _close_pair(row,flows,record["year"])
        events.extend(pair_events)
    ctx["events"] = events


def audit_diplomatic_rules(record, previous_record=None):
    ctx = record["diplomacy"]
    year,arm = record["year"],ctx["arm"]
    _check(ctx["year"]==year and arm in ("A","B","C","D"),"unexpected year or policy")
    pairs = {(r["a"],r["b"]):r["opening"] for r in ctx["pairs"]}
    countries = {r["id"] for r in record["countries"]}
    _check(list(pairs)==list(combinations(sorted(countries),2)) and len(pairs)==len(ctx["pairs"]),"missing country pair")
    if year==1:
        _check(all(m==_empty_pair(*key) for key,m in pairs.items()),"invalid initial relationship")
    if previous_record is not None:
        prev = previous_record["diplomacy"]
        _check(previous_record["year"]+1==year and prev["arm"]==arm and prev["intervention"] is None and
               pairs=={(r["a"],r["b"]):r["closing"] for r in prev["pairs"]},"prior diplomatic memory mismatch")
    owners = {r["id"]:r["owner"] for r in record["regions"]}
    borders = [{"a":e["a"],"b":e["b"],"owner_a":owners[e["a"]],"owner_b":owners[e["b"]],
                "capacity":e["capacity"],"distance":e["distance"]} for e in ctx["physical"]["roads"]]
    _check(sorted(ctx["borders"],key=lambda e:(e["a"],e["b"]))==sorted(borders,key=lambda e:(e["a"],e["b"])),
           "foreign access assumptions differ from audited border network")
    camps = {r["id"]:{k:g["prior"] for k,g in r["groups"].items()} for r in record["collective"]["regions"]}
    evidence = _countries([r["opening"] for r in record["regions"]],
                          {d["region"]:d["opening"] for d in record["government"]["depots"]},
                          {r["id"]:r["opening"] for r in record["politics"]["regions"]},
                          {c["id"]:c["opening"] for c in record["competition"]["countries"]},camps,pairs)
    _check(evidence==ctx["countries"],"national observations differ from opening private and public ledgers")
    choices = _choices(year,arm,pairs,evidence,borders,ctx["intervention"])
    flows, events = _movements(record),[]
    for actual, expected in zip(ctx["pairs"],choices,strict=True):
        expected["flows"],expected["closing"],emitted = _close_pair(expected,flows,year)
        _check(actual==expected,"bilateral policy, receipts or closing relationship mismatch")
        events.extend(emitted)
    _check(events==ctx["events"],"diplomatic events do not match receipts")
