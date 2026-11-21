"""Conditional election institutions on archived 5.0C C-arm economic observations."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import csv
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time

from civsim.competition import start_competition, step_competition
from civsim.competition_rules import FACTIONS, PLATFORMS
from civsim.fiscal_policy import ACTIONS
from civsim.model import generate_world
from civsim.political_rules import GROUPS
from civsim.regions import regionalize
from civsim.storage import canonical_line


MUTUAL = FACTIONS.index("mutualists")
CARETAKER = -1
FISCAL = {a:i for i,a in enumerate(ACTIONS)}
TABLES = [tuple(tuple(PLATFORMS[f][a] for a in ACTIONS) for f in FACTIONS)]
TABLES.append(tuple((5,4,1,1,1) if i==MUTUAL else row for i,row in enumerate(TABLES[0])))


@dataclass(frozen=True)
class Institution:
    name: str
    term: int = 4
    seats: int = 21
    table: int = 0
    performance: bool = True


VARIANTS = (Institution("reference"),Institution("term2",term=2),Institution("term8",term=8),
            Institution("seats5",seats=5),Institution("seats101",seats=101),
            Institution("exchange_platform",table=1),Institution("no_performance",performance=False))


def allocate(votes, seats):
    turnout = sum(votes)
    if not turnout:
        return (0,)*len(FACTIONS)
    parts = [divmod(seats*v,turnout) for v in votes]
    awarded = [q for q,_ in parts]
    for i in sorted(range(len(parts)),key=lambda i:(-parts[i][1],-votes[i],i))[:seats-sum(awarded)]:
        awarded[i] += 1
    return tuple(awarded)


def choose_leader(votes, seats, incumbent):
    if not sum(votes):
        return incumbent
    return min(range(len(votes)),key=lambda i:(-seats[i],i!=incumbent,-votes[i],i))


def _key(choice):
    edge = choice["target_edge"]
    return (choice["action"], tuple(edge) if edge is not None else
            (() if choice["target_region"] is None else (choice["target_region"],)))


def _name(party):
    return "caretaker" if party==CARETAKER else FACTIONS[party]


class Opening:
    """Candidates and constituency observations shared by all alternatives in a single country-year."""
    def __init__(self,states,plan):
        self.ids = sorted(states)
        self.population = sum(s["population"] for s in states.values())
        self.groups = []
        self.slots = {}
        for i in self.ids:
            self.slots[i] = []
            for group in GROUPS:
                g = states[i]["groups"][group]
                signals = tuple(g["signals"][a] for a in ACTIONS)
                intensity = max(signals)
                n = g["members"]
                base = [tuple(sum(w*x for w,x in zip(weights,signals))//12 for weights in table) for table in TABLES]
                self.slots[i].append(len(self.groups))
                self.groups.append((group,n,signals,base,(g["support"]-500)//4,intensity,
                                    n*intensity if intensity>=25 else 0,g["demand"],g["pressure"]))
        self.candidates = []
        for c in plan["candidates"]:
            action,target = _key(c)
            if c["permitted"] and not c["constraints"] and (c["score"]>0 or action=="defer"):
                covered = list(target) if target else self.ids
                slots = [j for i in covered for j in self.slots[i]]
                self.candidates.append((action,target,FISCAL[action],c["score"],c["population_loss"],len(covered),slots))
        self.ballots = {}
        self.ranks = {}

    def ballot(self, variant, incumbent):
        cache_key = (variant.table,variant.performance,incumbent)
        if cache_key not in self.ballots:
            votes = [0]*len(FACTIONS)
            support = []
            mutual = []
            for _,_,_,base,delta,_,total,_,_ in self.groups:
                scores = list(base[variant.table])
                if variant.performance and incumbent!=CARETAKER:
                    scores[incumbent] += delta
                maximum = max(scores)
                winners = [i for i,score in enumerate(scores) if score==maximum]
                support.append(bool(total) and incumbent in winners)
                q, extra = divmod(total,len(winners))
                bloc_mutual = 0
                for j, index in enumerate(winners):
                    share = q + int(j<extra)
                    votes[index] += share
                    if index==MUTUAL:
                        bloc_mutual = share
                mutual.append(bloc_mutual)
            self.ballots[cache_key] = (tuple(votes),support,mutual)
        return self.ballots[cache_key]

    def ranking(self, variant, governing):
        cache_key = (variant.table,variant.performance,governing)
        if cache_key not in self.ranks:
            support = self.ballot(variant,governing)[1]
            candidates = []
            for action,target,idx,econ,loss,districts,slots in self.candidates:
                weight = 0
                for j in slots:
                    _,n,signals,_,_,_,_,demand,pressure = self.groups[j]
                    if governing==CARETAKER:
                        weight += n*pressure if action==demand else 0
                    else:
                        merit = max(signals[idx],pressure if action==demand else 0)
                        weight += n*merit*(3 if support[j] else 2)
                if governing==CARETAKER:
                    priority = 8*weight//(32000*districts)
                else:
                    priority = 8*weight*5*TABLES[variant.table][governing][idx]//(24*32000*districts)
                candidates.append((action,target,econ,priority,econ+priority,loss,idx))
            ranked = sorted(candidates,key=lambda c:(-c[4],-c[2],-c[5],c[6],c[1]))
            self.ranks[cache_key] = ranked
        return self.ranks[cache_key]


def _attribute(detail, opening, actual, old):
    # Each observed ballot can be re-priced without changing its participants or previous cabinet.
    bare = opening.ballot(VARIANTS[-1],old)[2]
    for bloc, actual_q, bare_q in zip(opening.groups,actual[2],bare,strict=True):
        group,_,_,_,delta,_,total,demand,_ = bloc
        for key in ("all","group_"+group,"issue_"+demand,"incumbent_"+_name(old)):
            c = detail[key]
            c.update(participation=total,actual_mutual=actual_q,signal_only_mutual=bare_q,
                     mutual_gained=max(0,actual_q-bare_q),mutual_lost=max(0,bare_q-actual_q))
            if delta>0:
                c["positive_incumbent_performance_points"] += total
            elif delta<0:
                c["negative_incumbent_performance_points"] += total


def _turnover(opening, previous, current, actual, seed, year, owner, stats, cases):
    old_ranks = opening.ranking(VARIANTS[0],previous)
    new_ranks = opening.ranking(VARIANTS[0],current)
    before, after = old_ranks[0],new_ranks[0]
    if _key(actual["outgoing_choice"])!=before[:2]:
        raise ValueError("outgoing fiscal rank disagrees with archived decision")
    economic = max(c[2] for c in new_ranks)
    common = before[:2]==after[:2]
    if not common:
        reason = "action_changed" if before[0]!=after[0] else "target_changed"
    elif len(new_ranks)==1:
        reason = "only_defer_eligible"
    elif before[3]==max(c[3] for c in old_ranks) and after[3]==max(c[3] for c in new_ranks):
        reason = "common_political_maximum"
    else:
        reason = "economic_offset"
    stats[reason] += 1
    stats["eligible_candidates_"+str(len(new_ranks))] += 1
    stats["unchanged_and_economic_maximum"] += int(common and after[2]==economic)
    stats["both_choose_defer"] += int(common and after[0]=="defer")
    stats["same_action"] += int(before[0]==after[0])
    if reason not in cases:
        def describe(row):
            return dict(zip(("action","target","economic","political","total"),row[:5]))
        cases[reason] = {"seed":seed,"year":year,"owner":owner,"previous":_name(previous),"incoming":_name(current),
                         "eligible":len(new_ranks),"outgoing_rank":[describe(r) for r in old_ranks],
                         "incoming_rank":[describe(r) for r in new_ranks]}


def _trajectory(job):
    seed, years = job
    sim = start_competition(regionalize(generate_world(seed)))
    cabinets = [{n.id:(CARETAKER,(0,)*len(FACTIONS)) for n in sim.world.nations} for _ in VARIANTS]
    digest = hashlib.sha256()
    stats = {v.name:Counter() for v in VARIANTS}
    attribution, reasons, zeros, cases = defaultdict(Counter),Counter(),Counter(),{}
    for year in range(1,years+1):
        row = step_competition(sim,year,"C","fixed")
        digest.update(canonical_line(row))
        locations = defaultdict(dict)
        for r in row["politics"]["regions"]:
            locations[r["owner"]][r["id"]] = r["opening"]
        fiscal = {a["id"]:a["decision"] for a in row["government"]["accounts"]}
        for actual in row["competition"]["countries"]:
            owner = actual["id"]
            base = fiscal[owner]
            opening = Opening(locations[owner],base)
            recorded = _key(base)
            for version,v in enumerate(VARIANTS):
                previous,old_seats = cabinets[version][owner]
                counts = stats[v.name]
                ballot = opening.ballot(v,previous)
                votes = ballot[0]
                turnout = sum(votes)
                scheduled = year>1 and (year-1)%v.term==0
                current, seats = previous,old_seats
                if scheduled:
                    potential = allocate(votes,v.seats)
                    current = choose_leader(votes,potential,previous)
                    if turnout:
                        seats = potential
                    counts.update(elections=1,zero=int(not turnout),ballot_points=turnout,
                                  ballot_eligible=opening.population*1000,turnovers=int(previous!=CARETAKER and previous!=current),
                                  first_installations=int(previous==CARETAKER and current!=previous))
                    for j,f in enumerate(FACTIONS):
                        counts["votes_"+f] += votes[j]
                        counts["awarded_"+f] += potential[j]
                        counts["wins_"+f] += int(turnout>0 and current==j)
                cabinets[version][owner] = current,seats
                chosen = opening.ranking(v,current)[0]
                counts.update(country_years=1,annual_points=turnout,annual_eligible=opening.population*1000,
                              changed_government_from_observed=int(_name(current)!=actual["governing_faction"]),
                              changed_policy_from_observed=int(chosen[:2]!=recorded),
                              changed_action_from_observed=int(chosen[0]!=recorded[0]))
                counts["in_office_"+_name(current)] += 1
                for j,f in enumerate(FACTIONS):
                    counts["annual_votes_"+f] += votes[j]
                if version:
                    continue
                election = actual["election"]
                if (_name(previous)!=actual["opening"]["incumbent"] or _name(current)!=actual["governing_faction"]
                        or dict(zip(FACTIONS,votes))!=election["vote_points"] or scheduled!=election["election"]
                        or dict(zip(FACTIONS,seats))!=actual["closing"]["seats"] or chosen[:2]!=recorded):
                    raise ValueError(f"independent baseline mismatch at seed {seed}, year {year}, country {owner}")
                if scheduled:
                    _attribute(attribution,opening,ballot,previous)
                    if not turnout:
                        maximum = max((g[5] for g in opening.groups if g[1]),default=0)
                        if maximum>=25 or seats!=old_seats or current!=previous:
                            raise ValueError("zero-turnout state was inconsistent")
                        zeros.update(total=1,eligible_points=opening.population*1000,
                                     without_population=int(not opening.population),
                                     populated_below_threshold=int(bool(opening.population)),
                                     caretaker_retained=int(previous==CARETAKER),party_retained=int(previous!=CARETAKER),
                                     authorized_seats_carried=sum(old_seats))
                        zeros["max_signal_"+str(maximum)] += 1
                        if "zero_turnout" not in cases:
                            cases["zero_turnout"] = {"seed":seed,"year":year,"owner":owner,"people":opening.population,
                                                   "maximum_signal":maximum,"incumbent":_name(previous),"seats":old_seats}
                    if previous!=CARETAKER and previous!=current:
                        _turnover(opening,previous,current,actual,seed,year,owner,reasons,cases)
    return {"seed":seed,"years":years,"c_sha256":digest.hexdigest(),"variants":stats,
            "turnover":reasons,"zero":zeros,"attribution":dict(attribution),"examples":cases}


def _sum(rows):
    if not rows:
        return {}
    keys = sorted(set().union(*(r.keys() for r in rows)))
    return {k:(_sum([r[k] for r in rows if k in r]) if any(isinstance(r.get(k),dict) for r in rows)
               else sum(r.get(k,0) for r in rows)) for k in keys}


def _publish(path, raw):
    path.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=path.parent) as tmp:
        stage = Path(tmp,"diagnostics.json")
        stage.write_bytes(raw)
        if os.name=="nt":
            stage.rename(path)
        else:
            os.link(stage,path)


def run(sample, path, workers, verify=False):
    path = Path(path)
    if sample not in ("dev","holdout") or workers<=0:
        raise ValueError("choose a sample and positive worker count")
    if not verify and os.path.lexists(path):
        raise FileExistsError(path)
    if verify and not path.is_file():
        raise FileNotFoundError(path)
    start = 0 if sample=="dev" else 20
    with ProcessPoolExecutor(max_workers=min(workers,20)) as pool:
        trials = list(pool.map(_trajectory,[(s,200) for s in range(start,start+20)]))
    ref = Path(__file__).resolve().parents[1]/"examples"/"phase5c"/"study"/sample/"runs.csv"
    with ref.open(encoding="utf-8",newline="") as stream:
        originals = {int(r["seed"]):r["years_sha256"] for r in csv.DictReader(stream) if r["arm"]=="C" and r["year"]=="200"}
    if any(t["c_sha256"]!=originals[t["seed"]] for t in trials):
        raise ValueError("original C run differs from archived 5.0C ledger")
    totals = {k:_sum([t[k] for t in trials]) for k in ("variants","turnover","zero","attribution")}
    document = {"sample":sample,"start":start,"years":200,"archived_hashes_matched":len(trials),
                "settings":[vars(v) for v in VARIANTS],"totals":totals,"trajectories":trials}
    raw = (json.dumps(document,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode("utf-8")
    if verify:
        if raw!=path.read_bytes():
            raise ValueError("independent repeat differs from published results")
    else:
        _publish(path,raw)
    return hashlib.sha256(raw).hexdigest()


if __name__=="__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sample",choices=("dev","holdout"),required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--workers",type=int,default=4)
    p.add_argument("--verify",action="store_true")
    args = p.parse_args()
    started = time.perf_counter()
    digest = run(args.sample,args.out,args.workers,args.verify)
    print(f"{args.sample}: 20 trajectories, 4000 world-years, SHA-256 {digest}, {time.perf_counter()-started:.2f} s")
