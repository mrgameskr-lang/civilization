"""5.0C occupational preferences, representative support and fixed-term governments."""
from copy import deepcopy

from .fiscal_policy import ACTIONS
from .political_rules import GROUPS, _ratio, observe, prioritize


PLATFORMS = {name:dict(zip(ACTIONS,weights,strict=True)) for name,weights in (
    ("stewards",(1,2,5,3,1)), ("builders",(1,5,2,1,3)),
    ("mutualists",(5,1,1,4,1)), ("restraint",(1,2,1,2,6)))}
FACTIONS = tuple(PLATFORMS)
TERM = 4
SEATS = 21


def differentiated_observe(record, prior):
    """Keep 5B realized incidence and attitudes, recomputing policy preferences from physical inputs."""
    states = observe(record,prior)
    links = {i for e in record["government"]["roads"] for i in (e["a"],e["b"])}
    nodes = {n["id"]:n for n in record["domestic"]["nodes"]}
    for region in record["regions"]:
        i = region["id"]
        old, s, p = prior[i],states[i],region["production"]
        e, previous = s["evidence"],old["evidence"]
        people = s["population"]
        farmers = p["labor"]["farm"]
        last_workers = previous.get("labor",{}).get("farm",0)
        last_crop = previous.get("production",{}).get("food",0)
        crop = p["produced"]["food"]
        drop = _ratio(last_crop*farmers-crop*last_workers,last_crop*farmers) if last_workers else 0
        desired = min(p["factory_capacity"],max(0,p["investment"]["tool_target"]
                                    - (p["closing_stock"]["tools"]-p["produced"]["tools"])))
        feed = _ratio(desired-p["produced"]["tools"],desired)
        depleted = _ratio(p["mining_capacity"]-p["produced"]["ore"],p["mining_capacity"])
        tool_gap = _ratio(p["tool_need"]-p["investment"]["sector_used"]["tools"],p["tool_need"])
        crop_gap = _ratio(people-crop,people)
        field = (2*max(0,1000-e["soil_close"])+crop_gap+drop)//4 if p["farmland"] else 0
        hunger = min(1000,e["shortage_permille"]+e["relative_shortage_permille"]//2)
        last_rates = [*previous.get("shortage_lags",[])[-2:],e["shortage_permille"]]
        buffer = people//8
        stock = e["public_food_close"] + region["closing"]["stock"]["food"]
        reserve = _ratio(buffer-stock,buffer)*max(drop,*last_rates)//1000
        local_food = _ratio(nodes[i]["unmet_after"]["food"],people)
        ore_gap = _ratio(nodes[i]["unmet_after"]["ore"],nodes[i]["targets"]["ore"])
        e.update(yield_decline=drop,crop_gap=crop_gap,desired_tools=desired,factory_input_gap=feed,
                 mine_depletion=depleted,farm_tool_gap=tool_gap,soil_pressure=field,nutrition_pressure=hunger,
                 shortage_lags=last_rates,reserve_food_target=buffer,combined_food_buffer=stock,
                 reserve_pressure=reserve,after_freight_food_gap=local_food,after_freight_ore_gap=ore_gap,
                 domestic_road_connected=i in links)
        def route(x):
            return x*(1000+e["road_congestion_permille"])//2000 if i in links else 0
        interests = {"farm":(hunger//2,route(tool_gap),field,reserve//2),
                     "industry":(hunger//2,route(max(feed,min(depleted,ore_gap),e["industrial_shortage_permille"])),field//3,reserve//2),
                     "consumer":(hunger,route(local_food),field//3,reserve)}
        for name in GROUPS:
            g = s["groups"][name]
            if not g["members"]:
                continue
            signals = dict(zip(ACTIONS,(*interests[name],max(0,g["fiscal_burden"]-g["benefit"])),strict=True))
            demand = max(ACTIONS,key=signals.get)
            signal = signals[demand]
            old_group = old["groups"][name]
            age, pressure = 0,0
            if signal >= 25:
                age = old_group["age"]+1 if old_group["demand"]==demand else 1
                pressure = min(1000,(signal+g["discontent"]+max(0,500-g["support"]))//2+12*min(8,age-1))
            else:
                demand = "none"
            g.update(signals=signals,demand=demand,age=age,pressure=pressure)
    return states


def initial_cabinets(world):
    owners = {n.id for n in world.nations} if hasattr(world,"nations") else {r.owner for r in world.regions}
    return {owner:{"owner":owner,"incumbent":"caretaker","term_start":1,"last_election":0,
                   "elections":0,"turnovers":0,"seats":dict.fromkeys(FACTIONS,0)}
            for owner in sorted(owners)}


def _preference(group, incumbent):
    performance = (group["support"]-500)//4 if incumbent in FACTIONS else 0
    values = {f:sum(PLATFORMS[f][a]*group["signals"][a] for a in ACTIONS)//12
              + (performance if f==incumbent else 0) for f in FACTIONS}
    return values, performance


def _seats(votes):
    turnout = sum(votes.values())
    if not turnout:
        return dict.fromkeys(FACTIONS,0)
    parts = {f: divmod(SEATS*votes[f],turnout) for f in FACTIONS}
    seats = {f:q for f,(q,_) in parts.items()}
    rank = sorted(FACTIONS,key=lambda f:(-parts[f][1],-votes[f],FACTIONS.index(f)))
    for f in rank[:SEATS-sum(seats.values())]:
        seats[f] += 1
    return seats


def elect(year, states, cabinets):
    """Score lagged constituency ballots annually. Only a scheduled election can change the cabinet."""
    if type(year) is not int or year<1 or set(cabinets)!={s["owner"] for s in states.values()}:
        raise ValueError("invalid political year or cabinet ownership")
    updated, trace = {},{}
    for owner, old in sorted(cabinets.items()):
        incumbent = old["incumbent"]
        if incumbent not in (*FACTIONS,"caretaker") or owner!=old["owner"]:
            raise ValueError("unknown incumbent or cabinet")
        votes, ballots, eligible = dict.fromkeys(FACTIONS,0),[],0
        for i,s in sorted(states.items()):
            if s["owner"]!=owner:
                continue
            eligible += 1000*s["population"]
            for name in GROUPS:
                g = s["groups"][name]
                intensity = max(g["signals"].values())
                points = g["members"]*intensity if intensity>=25 else 0
                preferences, adjustment = _preference(g,incumbent)
                best = [f for f in FACTIONS if preferences[f]==max(preferences.values())]
                shares = dict.fromkeys(FACTIONS,0)
                q, extra = divmod(points,len(best))
                for n,f in enumerate(best):
                    shares[f] = q+int(n<extra)
                    votes[f] += shares[f]
                ballots.append({"region":i,"group":name,"members":g["members"],"participation_points":points,
                                "preference":preferences,"performance_adjustment":adjustment,"vote_points":shares})
        turnout = sum(votes.values())
        seats = _seats(votes)
        leading = min(FACTIONS,key=lambda f:(-seats[f],f!=incumbent,-votes[f],FACTIONS.index(f))) if turnout else incumbent
        scheduled = year>1 and (year-1)%TERM==0
        chosen = leading if scheduled else incumbent
        installation = incumbent=="caretaker" and chosen!="caretaker"
        turnover = incumbent!="caretaker" and chosen!=incumbent
        c = {**old,"seats":old["seats"].copy()}
        if scheduled:
            c.update(incumbent=chosen,last_election=year,elections=old["elections"]+1,turnovers=old["turnovers"]+int(turnover))
            if turnout:
                c.update(term_start=year,seats=seats.copy())
        updated[owner] = c
        trace[owner] = {"owner":owner,"year":year,"election":scheduled,"previous_incumbent":incumbent,
                        "incumbent":chosen,"installation":installation,"turnover":turnover,"leading_faction":leading,
                        "vote_points":votes,"seats":seats,"eligible_points":eligible,"participation_points":turnout,
                        "abstention_points":eligible-turnout,"ballots":ballots}
    return updated,trace


def cabinet_plan(base_plan, states, cabinet, allow_negative):
    if type(allow_negative) is not bool or cabinet["owner"]!=base_plan["owner"]:
        raise ValueError("invalid competition policy or cabinet")
    party = cabinet["incumbent"]
    if party not in (*FACTIONS,"caretaker"):
        raise ValueError("unknown cabinet platform")
    plan, trace = prioritize(base_plan,states)
    rows, candidates = trace["candidates"],plan["candidates"]
    populations = {r["region"]:r["population"] for r in plan["observations"]}
    support = {}
    if party in FACTIONS:
        for i in populations:
            for name in GROUPS:
                g = states[i]["groups"][name]
                values,_ = _preference(g,party)
                support[i,name] = max(g["signals"].values())>=25 and values[party]==max(values.values())
    for c,row in zip(candidates,rows,strict=True):
        action, targets = c["action"],row["target_regions"]
        cap = min(192,8*sum(populations[i] for i in targets)//(128*len(targets)))
        feasible = c["permitted"] and not c["constraints"] and (action=="defer" or c["quantity"]>0)
        political = row["political_score"]
        if party in FACTIONS:
            doubled_weight, contributions = 0,[]
            for i in targets:
                for name in GROUPS:
                    g = states[i]["groups"][name]
                    merit = max(g["signals"][action],g["pressure"] if g["demand"]==action else 0)
                    if g["members"] and merit:
                        points = g["members"]*merit
                        doubled_weight += points*(3 if support[i,name] else 2)
                        contributions.append({"region":i,"group":name,"members":g["members"],"pressure":merit,
                                              "member_pressure":points,"support_base":support[i,name]})
            political = (8*doubled_weight*5*PLATFORMS[party][action])//(2*12*32*1000*len(targets))
            row["contributions"] = contributions
        exception = (party in FACTIONS and allow_negative and feasible and action!="defer" and c["benefit_value"]>0
                     and political>0 and -cap<=c["score"]<=0)
        row.update(hard_feasible=feasible,exception_eligible=exception,funded_loss_cap=cap,
                   platform_weight=PLATFORMS[party][action] if party in FACTIONS else 0,
                   eligible=feasible and (c["score"]>0 or action=="defer" or exception),
                   political_score=political,total_score=political+c["score"])
    def ranking(i):
        c,row = candidates[i],rows[i]
        target = tuple(c["target_edge"]) if c["target_edge"] is not None else (c["target_region"],)
        return -row["total_score"],-c["score"],-c["population_loss"],ACTIONS.index(c["action"]),target
    winner = min((i for i,row in enumerate(rows) if row["eligible"]),key=ranking)
    original = next(i for i,c in enumerate(candidates) if (c["action"],c["target_region"],c["target_edge"])==
                    (base_plan["action"],base_plan["target_region"],base_plan["target_edge"]))
    c = candidates[winner]
    plan.update(action=c["action"],quantity=c["quantity"],target_region=c["target_region"],target_edge=c["target_edge"],
                target=c["target_edge"] if c["action"]=="road" else c["target_region"],selected_score=c["score"],
                relief_limit=c["quantity"] if c["action"]=="relief" else 0,budget=c["budget"].copy(),
                admin_units=c["budget"]["admin_units"])
    def description(i):
        return {k:deepcopy(rows[i][k]) for k in ("action","target_region","target_edge","quantity",
                                                  "economic_score","political_score","total_score")}
    trace.update(changed=winner!=original,economic_choice=description(original),political_choice=description(winner),
                 incumbent=party,allow_negative=allow_negative,exception_used=rows[winner]["exception_eligible"],
                 funded_loss_cap=rows[winner]["funded_loss_cap"])
    return plan,trace
