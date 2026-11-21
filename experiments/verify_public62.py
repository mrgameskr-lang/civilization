"""Rebuild every regular 6.0B trajectory, audit annual postings, and compare published checkpoint hashes."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
from hashlib import sha256
from importlib import import_module
import json
from pathlib import Path
import platform
from tempfile import TemporaryDirectory
from time import perf_counter

from civsim.model import generate_world
from civsim.regions import regionalize
from civsim.storage import canonical_line
from experiments.publication import publish_file


ROOT = Path(__file__).resolve().parents[1]
HORIZONS = (50,100,200)
STAGES = {'B1':('civsim.supply62',('A','B')), 'B2':('civsim.peace62',('C','D'))}


def _reference(study, sample, arms):
    folder = study/sample
    receipt = json.loads((folder/'execution.json').read_bytes())
    p = folder/'runs.csv'
    fingerprint = sha256(p.read_bytes()).hexdigest()
    first = 0 if sample=='dev' else 20
    if (receipt['table_sha256']['runs.csv']!=fingerprint or receipt['sample']!=sample
            or receipt['seeds']!=20 or receipt['first_seed']!=first or tuple(receipt['arms'])!=arms
            or tuple(receipt['horizons'])!=HORIZONS):
        raise ValueError(f'{sample}: published checkpoints or their numerical coverage differ from the protocol')
    record={}
    with p.open(encoding='utf8',newline='') as f:
        for row in csv.DictReader(f):
            key=int(row['seed']),row['arm'],int(row['year'])
            if key in record: raise ValueError(f'duplicate published checkpoint {key}')
            record[key]=row['initial_sha256'],row['years_sha256']
    if set(record)!={(s,a,y) for s in range(first,first+20) for a in arms for y in HORIZONS}:
        raise ValueError(f'{sample}: missing or unexpected published checkpoint')
    return record,fingerprint


def _replay(job):
    engine_name,seed,arm,expected=job
    engine=import_module(engine_name)
    world=regionalize(generate_world(seed))
    sim=engine.start62(world)
    opening=sha256(canonical_line(engine.snapshot62(sim))).hexdigest()
    if any(opening!=initial for initial,_ in expected.values()):
        raise ValueError(f'initial snapshot mismatch for seed {seed}, arm {arm}')
    chain=sha256()
    observed=[]
    prior=None
    for year in range(1,max(HORIZONS)+1):
        row=engine.step62(sim,year,arm)
        if arm=='A':
            # A dispatches the unmodified F engine and needs the strengthened geographic audit explicitly.
            engine.audit62(row,geography=world,previous_record=prior)
            prior=row
        chain.update(canonical_line(row))
        if year in expected:
            actual=chain.hexdigest()
            if actual!=expected[year][1]:
                raise ValueError(f'annual ledger mismatch for seed {seed}, arm {arm}, year {year}')
            observed.append((seed,arm,year,opening,actual))
    return observed


def verify(stage, study, workers):
    engine_name,arms=STAGES[stage]
    if workers<1: raise ValueError('workers must be positive')
    start=perf_counter()
    jobs=[]
    receipt={}
    expected_by_sample={}
    for sample in ('dev','holdout'):
        expected,fingerprint=_reference(study,sample,arms)
        expected_by_sample[sample]=expected
        seeds=sorted({s for s,_,_ in expected})
        for seed in seeds:
            for arm in arms:
                jobs.append((engine_name,seed,arm,{y:expected[seed,arm,y] for y in HORIZONS}))
        receipt[sample]=dict(seed_range=[seeds[0],seeds[-1]],runs_csv_sha256=fingerprint)
    observed={'dev':[],'holdout':[]}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for j,items in enumerate(pool.map(_replay,jobs),1):
            observed['dev' if items[0][0]<20 else 'holdout'].extend(items)
            if j%10==0: print(f'{stage}: {j}/{len(jobs)} trajectories verified',flush=True)
    for sample,items in observed.items():
        expected=expected_by_sample[sample]
        comparable=[(s,a,y,*value) for (s,a,y),value in sorted(expected.items())]
        if comparable!=sorted(items): raise ValueError('checkpoint comparison incomplete')
        digest=sha256(b''.join(canonical_line(r) for r in comparable)).hexdigest()
        receipt[sample].update(paths=len(items)//len(HORIZONS),annual_ledgers=len(items)*max(HORIZONS)//len(HORIZONS),
                               initial_comparisons=len(items),cumulative_comparisons=len(items),
                               matched_checkpoint_table_sha256=digest)
    return dict(stage=stage,arms=list(arms),horizons=list(HORIZONS),samples=receipt,
                audit='A: annual geographic audit plus predecessor; B/C/D: annual geographic audit inside regular step',
                workers=workers,python=platform.python_version(),wall_seconds=round(perf_counter()-start,3))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage',choices=tuple(STAGES),required=True)
    p.add_argument('--workers',type=int,default=5)
    p.add_argument('--study',type=Path)
    p.add_argument('--out',required=True,type=Path)
    args=p.parse_args()
    if args.out.exists(): raise FileExistsError(args.out)
    result=verify(args.stage,args.study or ROOT/'examples'/('phase6'+args.stage.lower())/'study',args.workers)
    with TemporaryDirectory(dir=args.out.parent) as tmp:
        staged=Path(tmp)/'audit.json'
        staged.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8',newline='\n')
        publish_file(staged,args.out)
    print(json.dumps(result))
