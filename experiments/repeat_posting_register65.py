"""Independently replay the audited B entry point, then match published campaign files."""
import argparse
import csv
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import io
import json
from pathlib import Path
from time import perf_counter

from civsim.posting_engine65 import run
from civsim.storage import canonical_line
from experiments.verify_civic_off64 import publish_receipt


ROOT=Path(__file__).resolve().parents[1]
YEARS=(50,100,200)
FIELDS=("economy_sha256","affiliation_sha256")
AUDIT_SOURCES=("civsim/posting_engine65.py","civsim/postings65.py")


def check(ok,message):
    if not ok:
        raise ValueError(message)


def fingerprint(path):
    return sha256(path.read_bytes()).hexdigest()


def replay(seed,years=YEARS):
    economy,book=sha256(),sha256()
    checkpoints=[]
    for y,(record,civic,register) in zip(range(1,max(years)+1),run(seed,max(years),policy="B"),strict=True):
        check(civic is None and register["year"]==record["year"]==y,"unexpected live record")
        economy.update(canonical_line(record))
        book.update(canonical_line(register))
        if y in years:
            checkpoints.append({"seed":seed,"year":y,FIELDS[0]:economy.hexdigest(),FIELDS[1]:book.hexdigest()})
    return checkpoints


def compute(path,workers):
    if path.exists():
        raise FileExistsError(path)
    check(1<=workers<=8,"choose one through eight workers")
    hashes={name:fingerprint(ROOT/name) for name in AUDIT_SOURCES}
    start=perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        result=[r for group in pool.map(replay,range(40)) for r in group]
    check(all(fingerprint(ROOT/name)==h for name,h in hashes.items()),"audit or affiliation rules changed during replay")
    publish_receipt(path,{"policy":"B","workers":workers,"world_years":8000,
                          "code_sha256":hashes,"checkpoints":result,"wall_seconds":round(perf_counter()-start,3)})


def indexed(rows):
    result={}
    for row in rows:
        key=int(row["seed"]),int(row["year"])
        check(key not in result,"duplicate checkpoint")
        result[key]=tuple(row[f] for f in FIELDS)
    return result


def match(repeat,official,first):
    replayed,archived=indexed(repeat),indexed(official)
    requested={(s,h) for s in range(first,first+20) for h in YEARS}
    check(set(archived)==set(replayed)==requested,"incomplete comparison grid")
    for key in sorted(requested):
        check(replayed[key]==archived[key],f"independent checkpoint differs for {key}")


def compare(scratch,study,out):
    if out.exists():
        raise FileExistsError(out)
    data=json.loads(scratch.read_bytes())
    check(data["policy"]=="B" and data["world_years"]==8000 and set(data["code_sha256"])==set(AUDIT_SOURCES) and
          all(fingerprint(ROOT/name)==value for name,value in data["code_sha256"].items()),
          "inconsistent replay or changed audit source")
    rows=data["checkpoints"]
    check(len(rows)==120,"expected 120 independently computed checkpoints")
    sources={}
    for cohort,first in (("dev",0),("holdout",20)):
        base=study/cohort
        metadata=json.loads((base/"execution.json").read_bytes())
        raw=(base/"runs.csv").read_bytes()
        sources[cohort]=sha256(raw).hexdigest()
        check(metadata["table_sha256"]["runs.csv"]==sources[cohort] and metadata["horizons"]==list(YEARS)
              and metadata["seeds"]==list(range(first,first+20)) and metadata["sample"]==cohort,
              "published sample identity, table or schedule changed")
        with io.StringIO(raw.decode("utf8"),newline="") as stream:
            selected=[r for r in csv.DictReader(stream) if r["arm"]=="B"]
        match([r for r in rows if first<=r["seed"]<first+20],selected,first)
    publish_receipt(out,{**data,"matched_economy":120,"matched_affiliation":120,"runs_sha256":sources})


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    sub=cli.add_subparsers(dest="action",required=True)
    execute=sub.add_parser("compute")
    execute.add_argument("--workers",type=int,default=6)
    execute.add_argument("--out",type=Path,required=True)
    verify=sub.add_parser("compare")
    verify.add_argument("--scratch",type=Path,required=True)
    verify.add_argument("--study",type=Path,default=ROOT/"examples/phase6c1-m1")
    verify.add_argument("--out",type=Path,required=True)
    args=cli.parse_args()
    if args.action=="compute":
        compute(args.out,args.workers)
        print("Replayed 8,000 years through the audited B entry point.")
    else:
        compare(args.scratch,args.study,args.out)
        print("Matched all 120 economic and 120 affiliation checkpoints.")


if __name__=="__main__":
    main()
