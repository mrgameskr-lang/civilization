"""Conservative bounds on unmet ordinary civilian relief at the recorded stage close."""
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import argparse
import gzip
from hashlib import sha256
from heapq import heappop, heappush
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from experiments.publication import publish_file


REASONS = ('spent_budget','insufficient_domestic_stock','disconnected_stock',
           'cannot_fund_one_ration_and_freight','unknown')
DETAIL = ('seed','year','owner','target','residual','food_budget_left','complete_road_distances',*REASONS)


def _one_unit_costs(target, edges):
    """Minimum food freight for one food unit using positive residual links only."""
    neighbors = defaultdict(list)
    for a,b,remaining,distance in edges:
        if remaining<0 or distance<=0:
            raise ValueError('Invalid civilian road observation')
        if remaining:
            fee = (distance+99)//100
            neighbors[a].append((b,fee))
            neighbors[b].append((a,fee))
    costs, pending = {target:0}, [(0,target)]
    while pending:
        total, i = heappop(pending)
        if total != costs[i]:
            continue
        for j,fee in neighbors[i]:
            value = total+fee
            if j not in costs or value<costs[j]:
                costs[j] = value
                heappush(pending,(value,j))
    return costs


def explain_residual(residual, food_budget_left, target, domestic_stocks, roads=None):
    """Partition a previously measured undelivered amount at one ordinary decision.

    Each successive ceiling sees only the remaining quantity. The road bound asks
    whether stocked depots lie in the target's positive-capacity component. The
    freight bound applies only when no such depot and no remaining authorized food
    budget could cover a single ration plus its least possible freight. A feasible
    one-unit quote does not establish usable throughput for the residual quantity.
    Missing physical edge distances keep the potentially affected portion unknown.
    No alternative shipment is generated and no household meal is predicted.
    """
    if target not in domestic_stocks or any(type(x) is not int or x<0 for x in
                                            (residual,food_budget_left,*domestic_stocks.values())):
        raise ValueError('Invalid relief residual or food balance')
    funded = min(residual,food_budget_left)
    stocked = min(funded,sum(domestic_stocks.values()))
    split = {'spent_budget':residual-funded,'insufficient_domestic_stock':funded-stocked,
             'disconnected_stock':0,'cannot_fund_one_ration_and_freight':0,'unknown':stocked}
    if not stocked or roads is None:
        return split
    costs = _one_unit_costs(target,roads)
    reachable = min(stocked,sum(q for i,q in domestic_stocks.items() if i in costs))
    split['disconnected_stock'] = stocked-reachable
    can_pay = any(min(q,food_budget_left)>=1+costs[i] for i,q in domestic_stocks.items() if i in costs)
    split['cannot_fund_one_ration_and_freight'] = 0 if can_pay else reachable
    split['unknown'] = reachable - split['cannot_fund_one_ration_and_freight']
    return split


def from_annual(record):
    """Return per-target evidence using only ordinary relief and domestic road receipts."""
    gov = record['government']
    relief = gov['relief']
    nodes = {n['id']:n for n in relief['nodes']}
    thresholds = {a['owner']:a['limit'] for a in relief['admin']}
    populations = {r['id']:r['opening']['population'] for r in record['regions']}
    distances = {tuple(sorted((r['a'],r['b']))):r['distance'] for r in record['domestic']['roads'] if 'distance' in r}
    stocks, roads = defaultdict(dict), defaultdict(list)
    complete = dict.fromkeys(thresholds,True)
    for i,n in nodes.items():
        stocks[n['owner']][i] = n['depot_close']['food']
    for e in relief['roads']:
        a,b = e['a'],e['b']
        owner = nodes[a]['owner']
        if nodes[b]['owner'] != owner:
            raise ValueError('Domestic relief road crosses a national boundary')
        distance = distances.get(tuple(sorted((a,b))))
        if distance is None:
            complete[owner] = False
        else:
            roads[owner].append((a,b,e['remaining'],distance))
    arrived, freight = Counter(), Counter()
    for s in relief['shipments']:
        arrived[s['target']] += s['quantity']
        freight[s['target']] += s['cost_food']
    result = []
    for account in gov['accounts']:
        owner,plan = account['id'],account['decision']
        if plan['action']!='relief':
            continue
        target = plan['target_region']
        budget = plan['budget']['food']
        admin = thresholds[owner] if plan['budget']['admin_units'] else 0
        actual_gap = max(0,populations[target]-nodes[target]['private_food_open'])
        posted = arrived[target]
        residual = min(plan['quantity'],budget,admin,actual_gap)-posted
        left = budget-posted-freight[target]
        split = explain_residual(residual,left,target,stocks[owner],roads[owner] if complete[owner] else None)
        result.append({'owner':owner,'target':target,'residual':residual,'food_budget_left':left,
                       'complete_road_distances':complete[owner],'at_stage_close':split})
    return result


def positive_years(path, seed, *, total_years=200):
    """Read just the keys and published ordinary residual from one complete C file."""
    raw = path.read_bytes()
    targets = {}
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        header = json.loads(next(stream))
        if header['seed']!=seed or header['arm']!='C' or len(set(header['columns']))!=len(header['columns']):
            raise ValueError('Unexpected regional evidence header')
        indexes = [header['columns'].index(k) for k in ('year','region','owner','ordinary_gap_not_dispatched')]
        covered = 0
        identities = None
        for year,line in enumerate(stream,1):
            seen, positive = {}, {}
            for packed in json.loads(line):
                y,i,owner,residual = (packed[j] for j in indexes)
                if y!=year or i in seen or type(residual) is not int or residual<0:
                    raise ValueError('Invalid regional observation')
                seen[i] = owner
                if residual:
                    positive[i] = (owner,residual)
            if len(seen)!=32 or (identities is not None and seen!=identities):
                raise ValueError('Incomplete or inconsistent region identities')
            identities,covered = seen,year
            if positive:
                targets[year] = positive
        if covered!=total_years:
            raise ValueError('Incomplete regional time series')
    return targets,sha256(raw).hexdigest()


def _matched_rows(seed,year,expected,settled):
    selected = [r for r in settled if r['residual']]
    if ({r['target']:(r['owner'],r['residual']) for r in selected} != expected
            or len(selected)!=len(expected)):
        raise ValueError(f'Replayed residual differs at seed {seed}, year {year}')
    rows = []
    for r in sorted(selected,key=lambda x:x['target']):
        split = r['at_stage_close']
        if set(split)!=set(REASONS) or sum(split.values())!=r['residual'] or min(split.values())<0:
            raise ValueError('Residual bounds do not reconcile')
        rows.append([seed,year,r['owner'],r['target'],r['residual'],r['food_budget_left'],
                     r['complete_road_distances'],*(split[k] for k in REASONS)])
    return rows


def _replay(job):
    # Import the unchanged public C entry point only for a seed with positive evidence.
    from civsim.annual_game import create
    from civsim.storage import canonical_line
    from experiments.food_reserve_study import advance

    seed, targets, reference_hashes = job
    game, evidence, checked = create(seed), [], []
    for year in range(1,max(targets)+1):
        record = advance(game,year,'C')
        if record['year']!=year:
            raise ValueError('Unexpected replay year')
        if str(year) in reference_hashes:
            if sha256(canonical_line(record)).hexdigest()!=reference_hashes[str(year)]:
                raise ValueError(f'Published C checkpoint differs at seed {seed}, year {year}')
            checked.append(year)
        if year in targets:
            evidence.extend(_matched_rows(seed,year,targets[year],from_annual(record)))
    return seed,evidence,checked


def study_report(study, workers=6):
    manifest = json.loads((study/'execution.json').read_bytes())
    if manifest['seeds']!=list(range(40)) or 'C' not in manifest['arms'] or not 1<=workers<=8:
        raise ValueError('Expected a complete forty-seed C study and one through eight workers')
    start = perf_counter()
    jobs, hashes, schedule = [], {}, {}
    original_count = original_amount = 0
    for seed in range(40):
        stem = f'seed-{seed:02}'
        path = study/(stem+'-C-regions.jsonl.gz')
        targets,hashes[path.name] = positive_years(path,seed)
        schedule[seed] = max(targets,default=0)
        if targets:
            reference = json.loads((study/(stem+'.json')).read_bytes())
            if reference['seed']!=seed or set(reference['annual_hashes']['C'])!={'50','100','200'}:
                raise ValueError('Invalid original C checkpoint schedule')
            jobs.append((seed,targets,reference['annual_hashes']['C']))
            original_count += sum(len(t) for t in targets.values())
            original_amount += sum(q for ts in targets.values() for _,q in ts.values())
    details, checked = [], {}
    if jobs:
        with ProcessPoolExecutor(max_workers=min(workers,len(jobs))) as pool:
            for s,part,years in pool.map(_replay,jobs):
                details.extend(part)
                checked[s] = years
    if len(details)!=original_count or sum(r[4] for r in details)!=original_amount:
        raise ValueError('Published positive observations were not all reproduced')
    groups = {}
    for group,lo,hi in [('development',0,20),('validation',20,40),('all',0,40)]:
        rows = [r for r in details if lo<=r[0]<hi]
        groups[group] = {'positive_region_years':len(rows), 'raw_residual':sum(r[4] for r in rows),
                         **{k:sum(r[DETAIL.index(k)] for r in rows) for k in REASONS}}
    return {'schema':'ordinary-civil-relief-bounds/1','arm':'C','regional_files_sha256':hashes,
            'last_replay_year_by_seed':schedule,'replayed_seed_count':len(jobs),
            'replayed_world_years':sum(schedule.values()),'matched_checkpoint_years':checked,
            'matched_positive_region_years':original_count,'published_residual':original_amount,
            'workers':min(workers,len(jobs)),'elapsed_seconds':round(perf_counter()-start,3),
            'definitions':{'spent_budget':'Remaining post-delivery authorization is smaller than the published residual.',
                           'insufficient_domestic_stock':'Total food left in all domestic depots bounds the remaining residual.',
                           'disconnected_stock':'After that ceiling, there is insufficient food in the positive-residual-road component.',
                           'cannot_fund_one_ration_and_freight':'Food is in the component but no single ration can pay its minimum actual one-unit freight and stay within the residual budget.',
                           'unknown':'No stronger attribution can be established from the observed ordinary-stage close. An open path or an affordable unit does not establish delivery of the remaining amount.',
                           'order':'Apply the ceilings in listed order. Multiple constraints can bind; these are accounting bounds, not independent causal effects.'},
            'cohorts':groups,'columns':DETAIL,'rows':details}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study',required=True,type=Path)
    parser.add_argument('--out',required=True,type=Path)
    parser.add_argument('--workers',type=int,default=6)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    receipt = study_report(args.study,args.workers)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=args.out.parent) as folder:
        tmp=Path(folder)/'ordinary.json'
        tmp.write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n',encoding='utf8',newline='\n')
        publish_file(tmp,args.out)
    print(f"Matched {receipt['matched_positive_region_years']} positive region-years across {receipt['replayed_seed_count']} replayed seeds.")


if __name__=='__main__':
    main()
