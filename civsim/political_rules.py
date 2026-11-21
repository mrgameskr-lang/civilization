"""Version 5.0B political observations and next-year candidate ranking."""
from collections import Counter
from copy import deepcopy

from .economy import BASE_PRICES
from .fiscal_policy import ACTIONS
from .model import GOODS


GROUPS = ("farm", "industry", "consumer")


def _ratio(x, denominator):
    return min(1000, 1000*max(0,x)//denominator) if denominator else 0


def _neutral():
    return {"members":0, "support":500, "discontent":0, "demand":"none", "age":0, "pressure":0,
            "benefit":0, "burden":0, "levy_value":0, "relief_food":0, "public_workers":0,
            "fiscal_burden":0, "signals":dict.fromkeys(ACTIONS,0), "history":[]}


def initial_politics(world):
    """Opening composition is unclassified until the first production journal exists."""
    return {r.id: {"region":r.id, "owner":r.owner, "year":0, "population":r.population,
                   "membership_known":False, "unclassified":r.population,
                   "groups":{k:_neutral() for k in GROUPS}, "evidence":{}}
            for r in world.regions}


def _shares(total, members):
    p = sum(members.values())
    if not p:
        if total:
            raise ValueError("relief delivered to uninhabited region")
        return dict.fromkeys(GROUPS,0)
    pairs = {k:divmod(total*members[k],p) for k in GROUPS}
    result = {k:q for k,(q,_) in pairs.items()}
    for k in sorted(GROUPS,key=lambda k:-pairs[k][1])[:total-sum(result.values())]:
        result[k] += 1
    return result


def _road_experience(record, region_ids):
    """Credit cargo at its destination once, when its final leg consumed an added slot."""
    receipts = {i:dict.fromkeys(GOODS,0) for i in region_ids}
    pressure, remaining = Counter(), {}
    for edge in record["government"]["roads"]:
        a, b = edge["a"],edge["b"]
        cap = edge["capacity"]
        congestion = _ratio(4*(cap-edge["unused"])-3*cap,cap)
        pressure[a],pressure[b] = max(pressure[a],congestion),max(pressure[b],congestion)
        if edge["opening_units"]:
            remaining[a,b] = max(0,edge["base"]-edge["works_use"]-edge["relief_use"])
    for shipment in record["domestic"]["shipments"]:
        legs = shipment["legs"]
        for index, leg in enumerate(legs):
            edge = tuple(sorted((leg["a"],leg["b"])))
            if edge not in remaining:
                continue
            q = shipment["quantity"]
            base_load = min(remaining[edge],q)
            remaining[edge] -= base_load
            if index==len(legs)-1:
                receipts[shipment["target"]][shipment["good"]] += q-base_load
    return receipts, pressure


def _group_state(k, members, prior, e, help_food, levy, workers):
    n = members[k]
    if n == 0:
        return _neutral()
    fiscal = _ratio(levy+8*workers,8*n)
    received = 8*help_food
    road = e["road_enabled_receipts"]
    if k=="industry":
        received += 4*road["ore"]+12*road["tools"]
    if k=="consumer":
        received += 8*road["food"]
    benefit = min(1000,_ratio(received,8*n)+(e["public_soil_gain"] if k=="farm" else 0))
    shortage, gap = e["shortage_permille"],e["relative_shortage_permille"]
    burden = min(1000,shortage+fiscal)
    support = (3*prior["support"] + 500 + (benefit-burden)//2)//4
    discontent = (3*prior["discontent"] + min(1000,max(0,burden+gap-benefit)))//4
    signals = dict.fromkeys(ACTIONS,0)
    signals["relief"] = (2*shortage+gap)//3
    signals["defer"] = max(0,fiscal-benefit)
    if k=="farm":
        signals["soil"] = min(1000,(max(0,1000-e["soil_close"])+_ratio(e["population"]-e["production"]["food"],
                                                                       e["population"]))//2)
    elif k=="industry":
        signals["road"] = min(e["industrial_shortage_permille"],e["road_congestion_permille"])
    else:
        signals["reserve"] = min(max(0,e["previous_shortage_permille"]-shortage),e["reserve_gap_permille"])
    demand = max(ACTIONS,key=signals.get)
    strength = signals[demand]
    age, pressure = 0,0
    if strength >= 25:
        age = prior["age"]+1 if prior["demand"]==demand else 1
        pressure = min(1000,(strength+discontent+max(0,500-support))//2 + 12*min(8,age-1))
    else:
        demand = "none"
    return {"members":n,"support":support,"discontent":discontent,"demand":demand,"age":age,
            "pressure":pressure,"benefit":benefit,"burden":burden,"levy_value":levy,"relief_food":help_food,
            "public_workers":workers,"fiscal_burden":fiscal,"signals":signals}


def observe(record, prior):
    """Observe only closed physical records. Political state never changes the current year's postings."""
    regions = {r["id"]:r for r in record["regions"]}
    if set(prior)!=set(regions) or len(regions)!=len(record["regions"]):
        raise ValueError("political regions do not match annual ledger")
    gov = record["government"]
    levies = {r["region"]:r["levied"] for r in gov["levies"]}
    depots = {r["region"]:r["closing"]["food"] for r in gov["depots"]}
    transport = {r["id"]:r for r in record["domestic"]["nodes"]}
    receipts, congestion = _road_experience(record,regions)
    help_food, public_workers, soil_gain = Counter(), Counter(), Counter()
    for shipment in gov["relief"]["shipments"]:
        help_food[shipment["target"]] += shipment["quantity"]
    for project in gov["works"]["projects"]:
        public_workers[project["target"]] += project["workers"]
        soil_gain[project["target"]] += project["soil_gain"]
    unmet, needs = Counter(),Counter()
    for r in regions.values():
        unmet[r["owner"]] += r["consumption"]["food_unmet"]
        needs[r["owner"]] += r["consumption"]["food_need"]

    result = {}
    for i,r in sorted(regions.items()):
        owner, old, year = r["owner"], prior[i], record["year"]
        if (old["owner"],old["region"],old["year"]+1)!=(owner,i,year):
            raise ValueError("political history must follow its region and year")
        p, meal = r["opening"]["population"],r["consumption"]
        labor = r["production"]["labor"]
        members = {"farm":labor["farm"],"industry":labor["mine"]+labor["factory"]}
        members["consumer"] = p-sum(members.values())
        if min(members.values())<0 or meal["food_need"]!=p:
            raise ValueError("invalid population or realized workforce")
        shortage = _ratio(meal["food_unmet"],p)
        country = _ratio(unmet[owner],needs[owner])
        node = transport[i]
        def industrial_value(stock):
            return 4*stock["ore"] + 12*stock["tools"]
        e = {"population":p, "food_need":p, "food_eaten":meal["food_eaten"], "food_unmet":meal["food_unmet"],
             "country_food_need":needs[owner], "country_food_unmet":unmet[owner],
             "shortage_permille":shortage, "country_shortage_permille":country,
             "relative_shortage_permille":max(0,shortage-country),
             "previous_shortage_permille":old["evidence"].get("shortage_permille",0),
             "production":r["production"]["produced"].copy(), "labor":labor.copy(), "levied":levies[i].copy(),
             "relief_food":help_food[i], "public_workers":public_workers[i], "public_soil_gain":soil_gain[i],
             "soil_close":r["closing"]["soil"], "public_food_close":depots[i],
             "reserve_gap_permille":_ratio(p//8-depots[i],p//8), "road_enabled_receipts":receipts[i],
             "road_congestion_permille":congestion[i], "industrial_target_value":industrial_value(node["targets"]),
             "industrial_shortage_value":industrial_value(node["unmet_after"])}
        e["industrial_shortage_permille"] = _ratio(e["industrial_shortage_value"],e["industrial_target_value"])
        levy = dict.fromkeys(GROUPS,0)
        for good, sector in (("food","farm"),("ore","industry"),("tools","industry")):
            holder = sector if members[sector] else "consumer"
            levy[holder] += BASE_PRICES[good]*levies[i][good]
        aid = _shares(help_food[i],members)
        groups = {k:_group_state(k,members,old["groups"][k],e,aid[k],levy[k],
                                 public_workers[i] if k=="consumer" else 0) for k in GROUPS}
        for k,g in groups.items():
            entry = {field:g[field] for field in ("members","benefit","burden","fiscal_burden","relief_food",
                                                   "levy_value","public_workers")}
            g["history"] = [dict(v) for v in old["groups"][k]["history"][-2:]] + [{"year":year, **entry}]
        result[i] = {"region":i,"owner":owner,"year":year,"population":p,"membership_known":True,
                     "unclassified":0,"groups":groups,"evidence":e}
    return result


def prioritize(plan, states):
    """Add political priority to the economic shortlist, leaving every recipe and price unchanged."""
    owner = plan["owner"]
    local = {int(i):s for i,s in states.items() if s["owner"]==owner}
    if set(local)!={o["region"] for o in plan["observations"]}:
        raise ValueError("political state coverage differs from fiscal decision")
    rows = []
    for c in plan["candidates"]:
        edge = c["target_edge"]
        action, region = c["action"],c["target_region"]
        targets = sorted(local) if action=="defer" else list(edge) if edge is not None else [region]
        weights = []
        for i in targets:
            for k in GROUPS:
                g = local[i]["groups"][k]
                if g["demand"]==action and g["pressure"] and g["members"]:
                    weights.append({"region":i,"group":k,"members":g["members"],"pressure":g["pressure"],
                                    "member_pressure":g["members"]*g["pressure"]})
        political = 8*sum(w["member_pressure"] for w in weights)//(32*1000*len(targets))
        eligible = c["permitted"] and not c["constraints"] and (c["score"]>0 or action=="defer")
        rows.append({"action":action,"target_region":region,"target_edge":list(edge) if edge is not None else None,
                     "quantity":c["quantity"],"eligible":eligible,"economic_score":c["score"],
                     "political_score":political,"total_score":political+c["score"],
                     "target_regions":targets,"contributions":weights})
    def ranking(index):
        c, row = plan["candidates"][index],rows[index]
        target = tuple(c["target_edge"]) if c["target_edge"] is not None else (c["target_region"],)
        return -row["total_score"],-c["score"],-c["population_loss"],ACTIONS.index(c["action"]),target
    selected = min((i for i,r in enumerate(rows) if r["eligible"]),key=ranking)
    original = next(i for i,c in enumerate(plan["candidates"]) if c["action"]==plan["action"] and
                    c["target_region"]==plan["target_region"] and c["target_edge"]==plan["target_edge"])
    choice = deepcopy(plan)
    c = choice["candidates"][selected]
    choice.update(action=c["action"], quantity=c["quantity"], target_region=c["target_region"], target_edge=c["target_edge"],
                  target=c["target_edge"] if c["action"]=="road" else c["target_region"],
                  budget=c["budget"].copy(), admin_units=c["budget"]["admin_units"], selected_score=c["score"],
                  relief_limit=c["quantity"] if c["action"]=="relief" else 0)
    def summary(index):
        return {k:v for k,v in rows[index].items() if k not in ("target_regions","contributions","eligible")}
    return choice, {"owner":owner,"changed":selected!=original,"economic_choice":summary(original),
                    "political_choice":summary(selected),"candidates":rows}
