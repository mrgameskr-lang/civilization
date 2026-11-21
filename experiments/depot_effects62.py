"""Independently summarize matched public-warehouse results and a same-opening intervention."""
import argparse
from collections import Counter, defaultdict
import csv
import gzip
from itertools import groupby
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from civsim.model import GOODS, generate_world
from civsim.regions import regionalize
from civsim.supply62 import fork_supply62, start62, step62
from experiments.phase6a import digest_file
from experiments.publication import publish_file


ROOT = Path(__file__).resolve().parents[1]
METRICS = ('food_need','food_eaten','food_deficit','closing_population','relief_food','produced_food',
           'aid_approved','aid_sent','aid_received','aid_handling_food','aid_freight_food','aid_unshipped',
           'aid_budget','aid_total_debit','aid_budget_left','aid_budget_overrun','internal_aid_freight_food',
           'domestic_reserve_freight_food','public_works_freight_food','public_relief_freight_food',
           'depot_edge_cargo','private_edge_cargo','road_works_use','road_relief_use','road_capacity','road_unused',
           'private_freight_food','exports_value','trade_freight_food','foreign_out','public_spoil_food',
           'emergency_aid_units','forward_aid_units','domestic_reserve_units',
           *(p+g for p in ('public_transfer_out_','private_transfer_out_','foreign_out_') for g in GOODS))


def rows(path):
    reader = gzip.open if path.suffix=='.gz' else open
    with reader(path,'rt',encoding='utf-8',newline='') as f:
        yield from csv.DictReader(f)


def signs(values):
    values = list(values)
    return dict(negative=sum(v<0 for v in values),zero=values.count(0),positive=sum(v>0 for v in values))


def paired_sums(pairs):
    a,b = (Counter({k:sum(int(r[j][k]) for r in pairs) for k in METRICS}) for j in (0,1))
    delta = {k:b[k]-a[k] for k in METRICS}
    rates = {key:v['food_deficit']/v['food_need'] if v['food_need'] else None for key,v in (('A',a),('B',b))}
    directions = {k:signs(int(y[k])-int(x[k]) for x,y in pairs) for k in
                  ('closing_population','food_eaten','food_deficit','aid_sent','private_edge_cargo','exports_value')}
    for v in (a,b):
        if (v['food_need']!=v['food_eaten']+v['food_deficit'] or
                v['aid_approved']!=v['aid_sent']+v['aid_unshipped'] or
                v['aid_sent']!=v['aid_received']+v['aid_handling_food'] or
                v['aid_total_debit']!=v['aid_sent']+v['aid_freight_food']+v['internal_aid_freight_food'] or
                v['aid_budget']!=v['aid_total_debit']+v['aid_budget_left'] or v['aid_budget_overrun']):
            raise ValueError('inconsistent world meal or aid account')
    return dict(A=dict(a), B=dict(b), delta=delta, seed_signs=directions, pooled_shortage_rate=rates)


def reason_counts(path, horizons):
    totals = {y:{a:defaultdict(Counter) for a in 'AB'} for y in horizons}
    conditional = {y:Counter() for y in horizons}
    # File ordering is seed, arm, year. Retain just one seed's positive baseline observations.
    for _, chunk in groupby(rows(path), key=lambda r:int(r['seed'])):
        baseline = {}
        for r in chunk:
            year,src,dst = (int(r[k]) for k in ('year','source','target'))
            key = year,src,dst
            arm = r['arm']
            approved,sent,received,left = (int(r[k]) for k in ('authorized','sent','received','unshipped'))
            why = r['shortfall_reasons']
            if left:
                if not why or approved!=sent+left:
                    raise ValueError('foreign shortfall lacks intact reason and account')
                for y in horizons:
                    if year<=y: totals[y][arm][why].update(directions=1,units=left)
            if arm=='A' and left and why=='stock':
                baseline[key] = approved,sent,received,left
            if arm=='B' and key in baseline:
                original = baseline.pop(key)
                for y in horizons:
                    if year>y: continue
                    c = conditional[y]
                    c.update(direction_years=1,A_unshipped=original[3],B_unshipped=left,
                             A_authorized=original[0],B_authorized=approved,A_sent=original[1],B_sent=sent,
                             A_received=original[2],B_received=received,
                             same_authorization=int(approved==original[0]),B_no_authorization=int(approved==0),
                             B_fewer_unshipped=int(left<original[3]),B_more_sent=int(sent>original[1]))
        if baseline: raise ValueError('missing adjacent foreign direction counterpart')
    return totals,conditional


def shipment_counts(path,horizons):
    out = {y:defaultdict(Counter) for y in horizons}
    for r in rows(path):
        if r['arm']!='B': raise ValueError('unexpected public transport in historical arm')
        q,fee = int(r['quantity']),int(r['cost_food'])
        legs = len(r['region_path'].split())-1
        if q<=0 or fee<legs or legs<=0: raise ValueError('invalid public transfer')
        for y in horizons:
            if int(r['year'])<=y:
                out[y][r['purpose']].update({r['good']:q,'trips':1,'fee':fee,'edge_units':q*legs})
    return out


def local_requests(path,horizons):
    out = {y:defaultdict(Counter) for y in horizons}
    for r in rows(path):
        year = int(r['year'])
        unfilled,begin,end = (int(r[k]) for k in ('unfilled','opening','closing'))
        if unfilled!=max(0,int(r['target'])-end) or end<begin:
            raise ValueError('invalid warehouse request receipt')
        for y in horizons:
            if year<=y:
                c = out[y][r['purpose']]
                c.update(requests=1,below_target=int(unfilled>0),no_transfer=int(end==begin))
                if unfilled: c['observed_'+(r['observed_limits'] or 'unspecified')]+=1
    return out


def exposure(path,horizons):
    out = {y:defaultdict(Counter) for y in horizons}
    for _,chunk in groupby(rows(path),key=lambda r:int(r['seed'])):
        controls = {}
        for r in chunk:
            y,index = int(r['year']),int(r['region'])
            k = y,index
            if r['arm']=='A':
                controls[k] = r
            else:
                a = controls.pop(k)
                category = 'B_received' if int(r['aid_received']) else 'B_no_receipt'
                c = out[y][category]
                c.update(regions=1,B_receipts=int(r['aid_received']))
                for key in ('food_eaten','food_deficit','food_need','relief_food'):
                    c[key]+=int(r[key])-int(a[key])
        if controls: raise ValueError('unmatched region checkpoint')
    return out


def congestion(path,horizons):
    """Count paired road/country/world YEARS. Historical trajectories can diverge before a given year."""
    out = {y:{k:Counter() for k in ('road_year','country_year','world_year','world_checkpoint')} for y in horizons}
    examples = {y:{} for y in horizons}
    def observe(y,level,key,x):
        a,b,p = x
        c = out[y][level]
        c['observations']+=1
        if not p: return
        c['public_active']+=1
        c['private_lower']+=int(a>b)
        c['drop_exceeds_new_public']+=int(a-b>p)
        if a-b>p:
            old = examples[y].get(level)
            if old is None or a-b-p>old['excess']:
                examples[y][level]=dict(key=key,A_private=a,B_private=b,B_public=p,excess=a-b-p)
    for s,chunk in groupby(rows(path),key=lambda r:int(r['seed'])):
        ctrl={}
        annual=defaultdict(lambda:[0,0,0])
        for r in chunk:
            y,n,a,b=(int(r[k]) for k in ('year','owner','a','b'))
            index=y,n,a,b
            if r['arm']=='A':
                if index in ctrl: raise ValueError('duplicate control road')
                ctrl[index]=int(r['private_use'])
            else:
                values=(ctrl.pop(index),int(r['private_use']),int(r['supply_use']))
                for horizon in horizons:
                    if y<=horizon: observe(horizon,'road_year',(s,y,n,a,b),values)
                for group in ((y,n),(y,None)):
                    for i,v in enumerate(values): annual[group][i]+=v
        if ctrl: raise ValueError('unmatched road')
        for h in horizons:
            total=[0,0,0]
            for (y,n),values in annual.items():
                if y>h: continue
                level='world_year' if n is None else 'country_year'
                observe(h,level,(s,y,n) if n is not None else (s,y),values)
                if n is None:
                    for j,v in enumerate(values): total[j]+=v
            observe(h,'world_checkpoint',(s,h),total)
    return {h:dict(counts=out[h],largest=examples[h]) for h in horizons}


def summarize(directory):
    meta = json.loads((directory/'execution.json').read_bytes())
    h = tuple(meta['horizons'])
    names = ('runs.csv','regions.csv','foreign-years.csv.gz','public-shipments.csv.gz','depot-requests.csv.gz',
             'road-years.csv.gz')
    fingerprints = {f:digest_file(directory/f) for f in names}
    if any(v!=meta['table_sha256'][k] for k,v in fingerprints.items()): raise ValueError('input digest mismatch')
    book = {(int(r['seed']),r['arm'],int(r['year'])):r for r in rows(directory/names[0])}
    seeds = range(meta['first_seed'],meta['first_seed']+meta['seeds'])
    if set(book)!={(s,a,y) for s in seeds for a in 'AB' for y in h}: raise ValueError('incomplete cohort')
    reasons,conditional = reason_counts(directory/names[2],h)
    shipping = shipment_counts(directory/names[3],h)
    demands = local_requests(directory/names[4],h)
    affected = exposure(directory/names[1],h)
    roads = congestion(directory/names[5],h)
    checkpoints = {}
    for y in h:
        pairs = [(book[s,'A',y],book[s,'B',y]) for s in seeds]
        if any(a['initial_sha256']!=b['initial_sha256'] for a,b in pairs): raise ValueError('initial worlds differ')
        result = paired_sums(pairs)
        for arm in 'AB':
            if sum(c['units'] for c in reasons[y][arm].values())!=result[arm]['aid_unshipped']:
                raise ValueError('reason combinations double counted or incomplete')
        for g in GOODS:
            if sum(c[g] for c in shipping[y].values())!=result['B']['public_transfer_out_'+g]:
                raise ValueError('shipment table differs from checkpoint')
        if sum(c['edge_units'] for c in shipping[y].values())!=result['B']['depot_edge_cargo']:
            raise ValueError('edge loads differ from physical shipments')
        if sum(c['food_eaten'] for c in affected[y].values())!=result['delta']['food_eaten']:
            raise ValueError('regional consumption differs from world')
        result.update(shortfall_reasons=reasons[y],matched_A_stock_only=dict(conditional[y]),
                      B_shipments=shipping[y],B_requests=demands[y],regions_by_B_aid_receipt=affected[y],
                      paired_road_congestion=roads[y])
        checkpoints[str(y)] = result
    return dict(seeds=meta['seeds'], sha256=fingerprints, checkpoints=checkpoints)


def summarize_fork(seed,year):
    sim = start62(regionalize(generate_world(seed)))
    for i in range(1,year): step62(sim,i,'B')
    on,held = fork_supply62(sim,year)
    def totals(r):
        t = Counter()
        for x in r['regions']:
            for k in ('food_eaten','food_need','food_unmet'): t[k]+=x['consumption'][k]
        for s in r['domestic']['shipments']:
            t['private_'+s['good']]+=s['quantity']
            t['private_edge_units']+=len(s['legs'])*s['quantity']
        for s in r['supply']['shipments']:
            t['public_'+s['good']]+=s['quantity']
            t['public_edge_units']+=len(s['legs'])*s['quantity']
            t['internal_fee']+=s['cost_food']
        for s in r['border_market']['trades']:
            t['foreign_'+s['good']]+=s['quantity']
            t['foreign_value']+=s['value']
        for s in r['diplomacy']['physical']['aid']['shipments']: t['aid_received']+=s['received']
        t['relief']=sum(s['quantity'] for s in r['government']['relief']['shipments'])
        return t
    def key(r): return r['a'],r['b']
    def routes(t): return [dict(source=s['source'],target=s['target'],good=s['good'],quantity=s['quantity'],
                                path=s['path'],fee=s['cost_food']) for s in t]
    def customs(t):
        return [dict(source=s['seller'],target=s['buyer'],good=s['good'],quantity=s['quantity'],
                     value=s['value']) for s in t]
    a,b = totals(on),totals(held)
    edges=[]
    for x,z in zip(on['government']['roads'],held['government']['roads'],strict=True):
        if key(x)!=key(z): raise ValueError('unequal roads')
        if x['supply_use'] or x['private_use']!=z['private_use'] or x['relief_use']!=z['relief_use']:
            edges.append(dict(edge=key(x),capacity=x['capacity'],public=x['supply_use'],private_on=x['private_use'],
                              private_held=z['private_use'],relief_on=x['relief_use'],relief_held=z['relief_use']))
    return dict(seed=seed,year=year,on=a,held=b,delta={k:a[k]-b[k] for k in sorted(set(a)|set(b))},
                roads=edges,public=routes(on['supply']['shipments']),
                private_on=routes(on['domestic']['shipments']),private_held=routes(held['domestic']['shipments']),
                foreign_on=customs(on['border_market']['trades']),foreign_held=customs(held['border_market']['trades']),
                regions=[dict(region=x['id'],owner=x['owner'],eaten_on=x['consumption']['food_eaten'],
                              eaten_held=z['consumption']['food_eaten']) for x,z in zip(on['regions'],held['regions'],strict=True)
                         if x['consumption']['food_eaten']!=z['consumption']['food_eaten']])


def screen_forks(seeds=range(6), years=50):
    from civsim.supply62 import _stage62
    counts=defaultdict(Counter)
    largest={}
    for seed in seeds:
        sim=start62(regionalize(generate_world(seed)))
        for year in range(1,years+1):
            held=_stage62(sim,year,'B',enabled=False,diagnostic='hold_supply')[1]
            on=step62(sim,year,'B')
            if [r['opening'] for r in on['regions']]!=[r['opening'] for r in held['regions']]:
                raise ValueError('unmatched intervention opening')
            deficit=sum(a['consumption']['food_unmet']-b['consumption']['food_unmet']
                        for a,b in zip(on['regions'],held['regions'],strict=True))
            def observe(level,key,prior,actual,public):
                c=counts[level]
                c['observations']+=1
                if not public: return
                c['public_active']+=1
                excess=prior-actual-public
                c['drop_exceeds_public']+=int(excess>0)
                c['with_higher_world_shortage']+=int(excess>0 and deficit>0)
                if level not in largest or excess>largest[level]['excess']:
                    largest[level]=dict(seed=seed,year=year,key=key,private_held=prior,private_on=actual,
                                        public=public,excess=excess,world_deficit_delta=deficit)
            owner=defaultdict(Counter)
            for a,b in zip(on['government']['roads'],held['government']['roads'],strict=True):
                key=(a['a'],a['b'])
                if key!=(b['a'],b['b']): raise ValueError('intervention road mismatch')
                observe('road_edge_cargo',key,b['private_use'],a['private_use'],a['supply_use'])
                owner[a['owner']].update(prior=b['private_use'],actual=a['private_use'],public=a['supply_use'])
            world=Counter()
            for n,c in owner.items():
                observe('country_edge_cargo',n,**c)
                world.update(c)
            observe('world_edge_cargo',None,**world)
            def volume(r,field):
                return sum(t['quantity'] for t in
                           (r['domestic']['shipments'] if field=='domestic' else r['border_market']['trades']))
            pub=sum(s['quantity'] for s in on['supply']['shipments'])
            hdom,odom=volume(held,'domestic'),volume(on,'domestic')
            htrade,otrade=volume(held,'foreign'),volume(on,'foreign')
            observe('world_private_domestic_units',None,hdom,odom,pub)
            observe('world_private_foreign_units',None,htrade,otrade,pub)
            observe('world_private_domestic_and_foreign_units',None,hdom+htrade,odom+otrade,pub)
    return dict(seeds=list(seeds),years=years,counts=counts,largest=largest)


if __name__=='__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--study',type=Path,default=ROOT/'examples/phase6b1/study')
    p.add_argument('--case',nargs=2,type=int,metavar=('DEV_SEED','YEAR'))
    p.add_argument('--scan-only',action='store_true',help='screen fixed development seeds 0–5, years 1–50')
    p.add_argument('--case-only',action='store_true',help='summarize only the specified development case')
    p.add_argument('--out',required=True,type=Path)
    args = p.parse_args()
    if args.out.exists(): raise FileExistsError(args.out)
    if args.case_only and (not args.case or args.scan_only): p.error('--case-only requires --case and excludes --scan-only')
    if args.scan_only:
        data=screen_forks()
    elif args.case_only:
        data={}
    else:
        data={sample:summarize(args.study/sample) for sample in ('dev','holdout')}
    if args.case:
        seed,year=args.case
        if not 0<=seed<20 or not 1<=year<=200: raise ValueError('case outside development scope')
        data['same_opening']=summarize_fork(seed,year)
    with TemporaryDirectory(dir=args.out.parent) as temp:
        staged = Path(temp)/'effects.json'
        staged.write_text(json.dumps(data,sort_keys=True,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        publish_file(staged,args.out)
