"""Match historical F shortfalls to opening food held outside attempted origin warehouses."""
import argparse
from collections import Counter, defaultdict
import csv
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from experiments.phase5d import _json
from experiments.phase6a import digest_file
from experiments.publication import publish_file


ARCHIVE=Path(__file__).resolve().parents[1]/"examples/phase6a1/study"


def baseline(directory):
    receipt=json.loads((directory/"execution.json").read_bytes())
    files=("direction-years","aid-attempts","region-years")
    inputs={}
    for stem in files:
        p=directory/(stem+".csv.gz")
        inputs[p.name]=digest_file(p)
        if inputs[p.name]!=receipt["table_sha256"][p.name]: raise ValueError("historical ledger changed")
    def read(name,keys):
        with gzip.open(directory/(name+".csv.gz"),"rt",encoding="utf8",newline="") as stream:
            reader=csv.reader(stream)
            header=next(reader)
            wanted=[header.index(k) for k in keys]
            arm=header.index("arm")
            for row in reader:
                if row[arm]=="F": yield [row[i] for i in wanted]
    cases={}
    for s,y,d,r,accepted,q,why in read("direction-years",("seed","year","source","target","authorized","unshipped","shortfall_reasons")):
        if int(q)>0: cases[int(s),int(y),int(d),int(r)]=(int(accepted),int(q),why.split("|"))
    tried=defaultdict(set)
    for s,y,d,r,i in read("aid-attempts",("seed","year","donor","recipient","source")):
        tried[int(s),int(y),int(d),int(r)].add(int(i))
    opening=defaultdict(dict)
    for s,y,d,i,food in read("region-years",("seed","year","owner","region","opening_public_food")):
        opening[int(s),int(y),int(d)][int(i)]=int(food)
    counts,highest=Counter(),None
    for (s,y,d,r),(accepted,q,reasons) in cases.items():
        counts.update(unfilled_directions=1,unfilled_food=q)
        if "stock" not in reasons: continue
        origins=tried[s,y,d,r]
        elsewhere={i:v for i,v in opening[s,y,d].items() if i not in origins}
        food=sum(elsewhere.values())
        counts.update(stock_in_reasons=1,stock_in_reasons_unfilled_food=q)
        if reasons==["stock"]: counts.update(stock_only=1,stock_only_unfilled_food=q)
        if food:
            counts.update(other_opening_food_directions=1,other_opening_food_unfilled=q,capped_overlap=min(q,food))
            rank=(min(q,food),-s,-y,-d,-r)
            if highest is None or rank>highest[0]:
                highest=rank,dict(seed=s,year=y,donor=d,recipient=r,accepted=accepted,unfilled=q,
                                  reasons=reasons,attempted_origins=sorted(origins),other_opening_depots=elsewhere)
    return {"input_sha256":inputs,"counts":dict(counts),"illustration":highest[1] if highest else None}


def publish(output):
    if output.exists() or output.is_symlink(): raise FileExistsError(output)
    result={sample:baseline(ARCHIVE/sample) for sample in ("dev","holdout")}
    output.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as temp:
        stage=Path(temp,"prior.json")
        _json(stage,result)
        publish_file(stage,output)
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out",required=True,type=Path)
    print(json.dumps({k:v["counts"] for k,v in publish(p.parse_args().out).items()}))
