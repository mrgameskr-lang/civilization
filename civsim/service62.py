"""Resident bookkeeping for fictional peacetime public duty, meals and domestic workplaces."""
from copy import deepcopy
from types import SimpleNamespace

from .audit import BalanceError
from .competition_rules import PLATFORMS
from .model import GOODS
from .regions import _split


MODES = ("off","fixed","adaptive")
STAFF_PER_TOOL = 12
PLAN_TOTALS = ("opening_roster","eligible_workers","enrolled","released","serving")
SETTLED_TOTALS = ("stationed","available","unavailable","ration_food","tools_used","travel_food",
                  "reassignment_out","reassignment_in","rationed_at_station")
CLOSING_TOTALS = ("service_deaths","service_emigrants","closing_roster")


def _check(ok,reason):
    if not ok:
        raise BalanceError("resident service: "+reason)


def _count(n):
    return type(n) is int and n>=0


def _nodes(regions):
    result={}
    for obj in regions:
        node=SimpleNamespace(**obj) if isinstance(obj,dict) else obj
        _check(node.id not in result and _count(node.population) and _count(node.land),"invalid resident register")
        result[node.id]=node
    return result


def start_service(regions):
    return {i:0 for i in sorted(_nodes(regions))}


def _signed_steps(value,step,ceiling):
    magnitude=min(ceiling,abs(value)//step)
    return -magnitude if value<0 else magnitude


def _national_policy(country,pairs,mode):
    owner=country["id"]
    tension=breaches=exposure=0
    relations=[]
    for r in pairs:
        if not r["adjacent"] or owner not in (r["a"],r["b"]):
            continue
        opening=r["opening"]
        relations.append(opening["relation"])
        t=opening["tension"]
        outgoing=next(d for d in opening["last"] if d["source"]==owner)
        tension=max(tension,t)
        exposure=max(exposure,t*outgoing["import_dependence"]//1000)
        breaches+=sum(d["agreement_breach"] for d in opening["last"])
    p=country["population"]
    buffer=p//64
    food=country["depot"]["food"]
    gap=1000*max(0,buffer-food)//buffer if buffer else 0
    signals=country["groups"]
    industrial=signals["industry"]["signals"]["road"]
    farm=signals["farm"]["signals"]["relief"]
    consumer=signals["consumer"]["signals"]["relief"]
    shortage=country["shortage_permille"]
    previous_workers=country["prior_need"]//2
    reference=p//2*24//1000
    foregone=country["prior_crop"]*reference//previous_workers if previous_workers else 0
    food_base=country["prior_need"]+country["stock"]["food"]
    share=min(1000,1000*foregone//food_base) if food_base else 0
    party=country["party"]
    platform=PLATFORMS.get(party,{"road":2,"relief":2})
    members=sum(g["members"] for g in signals.values())
    support=sum(g["support"]*g["members"] for g in signals.values())//members if members else 500
    mean_relation=(abs(sum(relations))//len(relations)) if relations else 0
    if sum(relations)<0:
        mean_relation=-mean_relation
    adjustments={"tension":tension//20,"recent_breaches":6*min(4,breaches),"trade_exposure":exposure//40,
                 "industry":industrial//80,"shortage":-(shortage//12),"farm":-(farm//100),
                 "consumer":-(consumer//100),"public_food_gap":-(gap//100),
                 "opportunity":-min(12,share//4),"incumbent":max(-6,min(6,platform["road"]-platform["relief"])),
                 "support":_signed_steps(support-500,125,4),"relation":-_signed_steps(mean_relation,50,8)}
    adaptive=max(0,min(80,24+sum(adjustments.values())))
    rate={"off":0,"fixed":24,"adaptive":adaptive}[mode]
    return {"id":owner,"population":p,"max_opening_tension":tension,"prior_breached_directions":breaches,
            "tension_weighted_import_dependence":exposure,"public_food":food,"public_food_buffer":buffer,
            "public_gap_permille":gap,"shortage_permille":shortage,"industry_road_signal":industrial,
            "farm_relief_signal":farm,"consumer_relief_signal":consumer,"rate_adjustments":adjustments,
            "adaptive_rate_permille":adaptive,"target_rate_permille":rate,"prior_crop":country["prior_crop"],
            "prior_food_need":country["prior_need"],"prior_workforce_proxy":previous_workers,
            "reference_roster":reference,"reference_foregone_food":foregone,"food_cost_denominator":food_base,
            "foregone_share_permille":share,"incumbent":party,"platform_road":platform["road"],
            "platform_relief":platform["relief"],"political_members":members,"weighted_support":support,
            "adjacent_pairs":len(relations),"mean_opening_relation":mean_relation}


def _sum_country(trace,fields):
    for c in trace["countries"]:
        local=[r for r in trace["regions"] if r["owner"]==c["id"]]
        for field in fields:
            c[field]=sum(r[field] for r in local)


def plan_service(regions,roster,diplomacy_ctx,mode,*,withheld=None,recruit=True):
    """Reserve a subset of opening workers. An enrollment hold leaves incumbent personnel eligible."""
    nodes=_nodes(regions)
    withheld={} if withheld is None else withheld
    _check(mode in MODES and type(recruit) is bool,"invalid policy or enrollment flag")
    _check(set(roster)==set(nodes) and set(withheld)<=set(nodes),"incomplete roster or unknown workers")
    national={c["id"]:c for c in diplomacy_ctx["countries"]}
    _check(set(national)=={r.owner for r in nodes.values()},"country observations do not cover residents")
    trace={"mode":mode,"recruit":recruit,"stage":"planned","countries":[],"regions":[],"moves":[]}
    for n,c in sorted(national.items()):
        rows=[]
        policy=_national_policy(c,diplomacy_ctx["pairs"],mode)
        for i,r in sorted(nodes.items()):
            if r.owner!=n:
                continue
            blocked=withheld.get(i,0)
            workers=r.population//2
            _check(_count(blocked) and blocked<=workers and _count(roster[i]) and roster[i]<=r.population,
                   "labor or carried roster exceeds residents")
            food=r.stock["food"]
            _check(_count(food),"invalid opening private food")
            weight=r.population+4*r.land+2*max(0,r.population//4-food) if r.population else 0
            rows.append({"id":i,"owner":n,"population":r.population,"workers":workers,"withheld":blocked,
                         "eligible_workers":workers-blocked,"opening_roster":roster[i],"station_weight":weight,
                         "land":r.land,"opening_private_food":food})
        _check(sum(r["population"] for r in rows)==c["population"],"national population differs from residents")
        weights=[r["eligible_workers"] for r in rows]
        policy["target"]=sum(weights)*policy["target_rate_permille"]//1000
        for row,target in zip(rows,_split(policy["target"],weights),strict=True):
            old=row["opening_roster"]
            kept=min(old,target,row["eligible_workers"])
            pace=(row["eligible_workers"]+95)//96
            add=min(pace,target-kept) if recruit else 0
            row.update(target=target,recruitment_limit=pace,enrolled=add,released=old-kept,serving=kept+add)
        trace["regions"].extend(rows)
        trace["countries"].append(policy)
    trace["regions"].sort(key=lambda r:r["id"])
    _sum_country(trace,PLAN_TOTALS)
    for c in trace["countries"]:
        previous_workers=c["prior_workforce_proxy"]
        c["opportunity_food_estimate"]=c["prior_crop"]*c["serving"]//previous_workers if previous_workers else 0
    return trace


def _check_roads(roads,nodes,residual):
    keys=set()
    for e in roads:
        key=e.a,e.b
        _check(e.a in nodes and e.b in nodes and e.a<e.b and key not in keys,"noncanonical domestic road")
        a,b=nodes[e.a],nodes[e.b]
        _check(a.owner==b.owner and type(e.distance) is int and e.distance>0 and len(e.path)==e.distance+1
               and (e.path[0],e.path[-1])==(a.seat,b.seat) and len(set(e.path))==len(e.path),"invalid workplace route")
        if hasattr(a,"members") and hasattr(b,"members"):
            _check(set(e.path)<=set(a.members)|set(b.members),"route outside endpoint territories")
        keys.add(key)
    _check(set(residual)==keys and all(_count(v) for v in residual.values()),"invalid shared road balances")


def settle_service(trace,regions,depots,roads,residual,*,away=None):
    """Reserve home rations, settle paid round trips, then pay for tools where work is performed."""
    _check(trace["stage"]=="planned","service has already settled")
    nodes=_nodes(regions)
    roads=list(roads)
    _check_roads(roads,nodes,residual)
    _check(set(nodes)==set(depots) and all(set(s)==set(GOODS) and all(_count(v) for v in s.values())
                                           for s in depots.values()),"invalid public depots")
    result=deepcopy(trace)
    balances={i:s.copy() for i,s in depots.items()}
    left=residual.copy()
    rows={r["id"]:r for r in result["regions"]}
    _check(set(rows)==set(nodes),"region plan differs from world")
    for n in result["countries"]:
        local=[r for r in result["regions"] if r["owner"]==n["id"]]
        goals=_split(n["serving"],[r["station_weight"] for r in local])
        for r,goal in zip(local,goals,strict=True):
            i=r["id"]
            food=min(r["serving"],balances[i]["food"])
            r.update(station_target=goal,stationed=r["serving"],ration_food=food,travel_food=0,tools_used=0,
                     reassignment_out=0,reassignment_in=0,opening_depot=balances[i].copy())
            balances[i]["food"]-=food
    for e in sorted(roads,key=lambda edge:(edge.distance,edge.a,edge.b)):
        key=e.a,e.b
        for home,station in ((e.a,e.b),(e.b,e.a)):
            origin,dest=rows[home],rows[station]
            surplus=max(0,origin["stationed"]-origin["station_target"])
            demand=max(0,dest["station_target"]-dest["stationed"])
            tool_places=max(0,STAFF_PER_TOOL*balances[station]["tools"]-dest["stationed"])
            fed=origin["ration_food"]-origin["reassignment_out"]
            affordable=100*balances[home]["food"]//(2*e.distance)
            people=min(surplus,demand,tool_places,fed,left[key]//2,affordable)
            if away:
                # A returning daily commute must start with a resident physically at home.
                people=min(people,max(0,origin["serving"]-away.get(home,0)-origin["reassignment_out"]))
            if people==0:
                continue
            fee=(2*people*e.distance+99)//100
            path=e.path if home==e.a else e.path[::-1]
            result["moves"].append({"home":home,"station":station,"owner":origin["owner"],"people":people,
                                    "distance":e.distance,"path":list(path),"road_load":2*people,"travel_food":fee,
                                    "road_before":left[key],"food_before":balances[home]["food"],
                                    "surplus":surplus,"demand":demand,"tool_places":tool_places,"fed_home_available":fed})
            balances[home]["food"]-=fee
            left[key]-=2*people
            origin["stationed"]-=people
            origin["reassignment_out"]+=people
            origin["travel_food"]+=fee
            dest["stationed"]+=people
            dest["reassignment_in"]+=people
    for i,r in rows.items():
        fed=r["ration_food"]-r["reassignment_out"]+r["reassignment_in"]
        available=min(fed,STAFF_PER_TOOL*balances[i]["tools"])
        tools=(available+STAFF_PER_TOOL-1)//STAFF_PER_TOOL
        balances[i]["tools"]-=tools
        r.update(available=available,unavailable=r["stationed"]-available,rationed_at_station=fed,tools_used=tools,
                 used={"food":r["ration_food"]+r["travel_food"],"ore":0,"tools":tools},closing_depot=balances[i].copy())
    _sum_country(result,SETTLED_TOTALS)
    for c in result["countries"]:
        _check(c["stationed"]==c["serving"] and c["reassignment_in"]==c["reassignment_out"],"resident staffing mismatch")
        c["readiness_permille"]=1000*c["available"]//c["serving"] if c["serving"] else 0
        c["used"]={"food":c["ration_food"]+c["travel_food"],"ore":0,"tools":c["tools_used"]}
    result["stage"]="settled"
    for i in nodes:
        depots[i].update(balances[i])
    trace.update(result)
    return left


def apply_service_rations(trace,regions):
    """Release segregated home-depot meals to residents immediately before ordinary consumption."""
    _check(trace["stage"]=="settled","home rations may be claimed only once")
    nodes=_nodes(regions)
    _check(set(nodes)=={r["id"] for r in trace["regions"]},"meal recipients differ from the opening")
    for r in trace["regions"]:
        node=nodes[r["id"]]
        _check(node.population==r["population"] and 0<=r["ration_food"]<=r["serving"]<=node.population
               and _count(node.stock["food"]),"invalid or lost home resident")
    for r in trace["regions"]:
        nodes[r["id"]].stock["food"]+=r["ration_food"]
    trace["stage"]="rationed"


def close_service(trace,vitals):
    """Deaths and emigrants leave the register as subsets of already counted census changes."""
    _check(trace["stage"]=="rationed" and set(vitals)=={r["id"] for r in trace["regions"]},"invalid census stage")
    pending={}
    for r in trace["regions"]:
        i,p,serving=r["id"],r["population"],r["serving"]
        v=vitals[i]
        born,dead,out,arrive=(v[k] for k in ("births","deaths","emigrants","immigrants"))
        after=p+born-dead
        _check(all(_count(n) for n in (born,dead,out,arrive)) and v["opening_population"]==p and dead<=p
               and after==v["population_before_migration"] and out<=after and after-out+arrive==v["closing_population"],
               "census does not close")
        lost=serving*dead//p if p else 0
        left=(serving-lost)*out//after if after else 0
        closing=serving-lost-left
        _check(0<=closing<=v["closing_population"],"closing register exceeds residents")
        pending[i]={"service_deaths":lost,"service_emigrants":left,"closing_roster":closing}
    for r in trace["regions"]:
        r.update(pending[r["id"]])
    _sum_country(trace,CLOSING_TOTALS)
    trace["stage"]="closed"
    return {i:v["closing_roster"] for i,v in pending.items()}


def audit_service(trace,*,regions,roster,diplomacy_ctx,withheld,depots,roads,residual,vitals,away=None):
    """Rebuild all choices and cashless postings from original opening evidence and census receipts."""
    expected=plan_service(regions,roster,diplomacy_ctx,trace["mode"],withheld=withheld,recruit=trace["recruit"])
    copies=deepcopy(list(_nodes(regions).values()))
    funds=deepcopy(depots)
    left=settle_service(expected,copies,funds,roads,residual,away=away)
    charged={k:0 for k in residual}
    for m in trace["moves"]:
        key=tuple(sorted((m["home"],m["station"])))
        _check(key in charged and m["road_load"]==2*m["people"] and m["travel_food"]==-(-m["road_load"]*m["distance"]//100),
               "incorrect round trip")
        charged[key]+=m["road_load"]
    _check(all(left[k]+charged[k]==residual[k] for k in left),"domestic road mismatch")
    apply_service_rations(expected,copies)
    close_service(expected,vitals)
    _check(expected==trace,"policy, region costs, personnel, provisions or closing coverage differs")
