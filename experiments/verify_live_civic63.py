"""Check live civilian pair records and economic bytes against the separately published D and civic archives."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
import gzip
from hashlib import sha256
import json
from pathlib import Path
import platform
from tempfile import TemporaryDirectory
from time import perf_counter

from civsim.civic_diplomacy63 import COUNTERS
from civsim.civic_observer63 import closed_directions, run
from civsim.model import generate_world
from civsim.peace62 import snapshot62,start62
from civsim.regions import regionalize
from civsim.storage import canonical_line
from experiments.phase6a import digest_file
from experiments.publication import publish_file


ROOT=Path(__file__).resolve().parents[1]/'examples'
HORIZONS=(50,100,200)
MODES=('observe','consult')
CASES=(('dev',0),('holdout',20))


def _archive(folder, filenames):
    meta=json.loads((folder/'execution.json').read_bytes())
    actual={name:digest_file(folder/name) for name in filenames}
    if any(meta['table_sha256'][name]!=digest for name,digest in actual.items()):
        raise ValueError(f'changed published input in {folder.name}')
    return actual


def _checkpoints(path,seed,policy_key,policy):
    with path.open(encoding='utf8',newline='') as stream:
        selected=[r for r in csv.DictReader(stream) if int(r['seed'])==seed and r[policy_key]==policy]
    book={int(r['year']):r for r in selected}
    if set(book)!=set(HORIZONS) or len(book)!=len(selected): raise ValueError('missing or repeated checkpoints')
    return book


def _prior(path,seed):
    evidence={}
    with gzip.open(path,'rt',encoding='utf8',newline='') as stream:
        for r in csv.DictReader(stream):
            if int(r['seed'])>seed: break
            if int(r['seed'])==seed and r['arm']=='D':
                item={k:int(r[k]) for k in ('seed','year','source','target',*COUNTERS)}
                item['arm']='D'
                d=item['source'],item['target']
                group=evidence.setdefault(item['year'],{})
                if d in group: raise ValueError('duplicate archived direction')
                group[d]=item
    if set(evidence)!=set(range(1,201)): raise ValueError('incomplete foreign archive')
    return evidence


def _published_civic(path,seed,mode):
    # The official compressed stream interleaves modes within a seed and year.
    annual={}
    with gzip.open(path,'rb') as stream:
        for line in stream:
            row=json.loads(line)
            owners={p['seed'] for p in row['pairs']}
            if len(owners)!=1: raise ValueError('mixed seeds in annual register')
            line_seed=owners.pop()
            if line_seed>seed: break
            if line_seed==seed and row['mode']==mode:
                year=row['year']
                if year in annual: raise ValueError('duplicate annual civic row')
                annual[year]=sha256(line).digest()
    if set(annual)!=set(range(1,201)): raise ValueError('incomplete published civic register')
    return annual


def _replay(job):
    economics,study,sample,seed,mode=job
    econ=economics/sample
    civil=study/sample
    base=_checkpoints(econ/'runs.csv',seed,'arm','D')
    check=_checkpoints(civil/'runs.csv',seed,'mode',mode)
    archive=_prior(econ/'foreign-years.csv.gz',seed)
    published=_published_civic(civil/'annual.jsonl.gz',seed,mode)
    initial=sha256(canonical_line(snapshot62(start62(regionalize(generate_world(seed)))))).hexdigest()
    eh,ch=sha256(),sha256()
    milestones=[]
    directional_rows=pair_rows=0
    for year,(ledger,pairs) in enumerate(run(seed,200,mode),start=1):
        if ledger['year']!=year or len(pairs)!=28: raise ValueError('unexpected live year or pair coverage')
        directions=closed_directions(seed,ledger)
        actual={(r['source'],r['target']):r for r in directions}
        if len(actual)!=len(directions) or actual!=archive[year]: raise ValueError(f'directional mismatch {seed}/{year}')
        lag=[r for p in pairs.values() for r in p['evidence']]
        if (len(lag)!=len(archive.get(year-1,{})) or {(r['source'],r['target']):r for r in lag}!=archive.get(year-1,{})):
            raise ValueError(f'civic evidence differs from preceding settlement {seed}/{year}')
        line=canonical_line(dict(mode=mode,year=year,pairs=[pairs[p] for p in sorted(pairs)]))
        if sha256(line).digest()!=published[year]: raise ValueError(f'live/published pair rows differ {seed}/{mode}/{year}')
        eh.update(canonical_line(ledger))
        ch.update(line)
        directional_rows+=len(actual)
        pair_rows+=len(pairs)
        if year in HORIZONS:
            ehash,chash=eh.hexdigest(),ch.hexdigest()
            if (initial!=base[year]['initial_sha256'] or initial!=check[year]['initial_sha256']
                    or ehash!=base[year]['years_sha256'] or ehash!=check[year]['economic_years_sha256']
                    or chash!=check[year]['civic_years_sha256']):
                raise ValueError(f'checkpoint mismatch {sample}/{seed}/{mode}/{year}')
            milestones.append(dict(year=year,economic_years_sha256=ehash,civic_years_sha256=chash))
    return dict(sample=sample,seed=seed,mode=mode,initial_sha256=initial,annual_economic_ledgers=year,
                annual_sidecar_rows_matched=len(published),civic_pair_rows_matched=pair_rows,
                current_direction_rows_matched=directional_rows,matched_checkpoints=milestones)


def verify(economics,study,workers):
    if workers<1: raise ValueError('workers must be positive')
    start=perf_counter()
    inputs={s:{'economics':_archive(economics/s,('foreign-years.csv.gz','runs.csv')),
               'consultations':_archive(study/s,('annual.jsonl.gz','runs.csv'))} for s,_ in CASES}
    jobs=[(economics,study,s,seed,mode) for s,seed in CASES for mode in MODES]
    with ProcessPoolExecutor(max_workers=min(workers,len(jobs))) as pool:
        records=list(pool.map(_replay,jobs))
    for s,_ in CASES:
        enabled=[r for r in records if r['sample']==s]
        if [k['economic_years_sha256'] for k in enabled[0]['matched_checkpoints']]!=[
                k['economic_years_sha256'] for k in enabled[1]['matched_checkpoints']]:
            raise ValueError('consultation mode changed economic bytes')
    return dict(source_sha256=inputs,paths=records,workers=min(workers,len(jobs)),python=platform.python_version(),
                wall_seconds=round(perf_counter()-start,3))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--economics',type=Path,default=ROOT/'phase6b2/study')
    p.add_argument('--study',type=Path,default=ROOT/'phase6c1/diplomacy')
    p.add_argument('--workers',type=int,default=4)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    if args.out.exists(): raise FileExistsError(args.out)
    result=verify(args.economics,args.study,args.workers)
    with TemporaryDirectory(dir=args.out.parent) as folder:
        staged=Path(folder)/'live-check.json'
        staged.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8',newline='\n')
        publish_file(staged,args.out)
    print(f"verified {len(result['paths'])} paths and 12 economic/civic checkpoint pairs")
