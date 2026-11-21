"""Independently replay seeds, match all checkpoint bytes and decompressed regional evidence."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import gzip
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from civsim.storage import canonical_line
from experiments.priority_case import suite
from experiments.priority_study import ARMS, run_seed


def contents(path):
    if path.suffix == ".gz":
        with gzip.open(path,"rb") as f:
            return sha256(f.read()).hexdigest()
    return sha256(path.read_bytes()).hexdigest()


def repeat(job):
    root,seed=job
    with TemporaryDirectory() as workspace:
        out=Path(workspace)
        run_seed(seed,out)
        names=[f"seed-{seed:02}.json",*(f"seed-{seed:02}-{a}.jsonl.gz" for a in ARMS)]
        digests={}
        for name in names:
            result=contents(out/name)
            if result!=contents(root/"study"/name):
                raise ValueError("Independent game rerun differs at "+name)
            digests[name]=result
        return {"seed":seed,"sha256":digests}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--workers",type=int,default=4)
    parser.add_argument("--seeds",type=int,nargs="+",default=list(range(40)))
    args=parser.parse_args()
    if args.out.exists() or len(set(args.seeds))!=len(args.seeds):
        raise ValueError("use a fresh output and unique seeds")
    start=perf_counter()
    case_hash=sha256(canonical_line(suite())).hexdigest()
    if case_hash!=contents(args.root/"case.json"):
        raise ValueError("short case differs")
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        results=[]
        for r in pool.map(repeat,[(args.root,s) for s in args.seeds]):
            print(f"matched seed {r['seed']}",flush=True)
            results.append(r)
    with args.out.open("xb") as f:
        f.write(canonical_line({"seeds":args.seeds,"workers":args.workers,"case_sha256":case_hash,
            "seconds":round(perf_counter()-start,3),"results":results}))


if __name__=="__main__":
    main()
