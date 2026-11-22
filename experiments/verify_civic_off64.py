"""Read-only compatibility replay against the civilian archives at revision 2114ca3."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
from hashlib import sha256
from itertools import combinations
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from civsim.civic_diplomacy63 import audit_civic_pair
from civsim.civic_observer63 import closed_directions
from civsim.model import generate_world
from civsim.peace62 import audit62, snapshot62, start62
from civsim.regional_engine import state
from civsim.regions import regionalize
from civsim.storage import canonical_line
from experiments.civic_baseline63 import civic_year, require
from experiments.publication import publish_file
from experiments.verify_live_civic63 import HORIZONS, ROOT


PINS={
    "phase6b2/study/dev/runs.csv":"8316548fb4678a2e0c5e3dbcead763028269960a7189e677ea46f4a48d1f9f10",
    "phase6b2/study/holdout/runs.csv":"b82e38340ffac1dffb608854bf5832ae94d006d7aff2e9b3e3ae2f784ee26d58",
    "phase6c1/diplomacy/dev/runs.csv":"b22f9773c303bdfe7075af6e9c09daf0b273ae426c29ef7ad26f637ded5ad5e6",
    "phase6c1/diplomacy/holdout/runs.csv":"4bf2ef00de76997f575b89ed835ac863cc39278f99a9e6b63c376d4d6dda0699",
    "phase6c1/baseline/checkpoints.csv":"f272612dc74db41a8d48ffdccd0c29a5bdbbafe86a5ce129ff7ff2e4065bbd1c",
}
PAIRS=tuple(combinations(range(8),2))
EXTRA=(0,20)


def load_references(root=ROOT):
    tables={}
    for name,pin in PINS.items():
        path=root/name
        require(sha256(path.read_bytes()).hexdigest()==pin,"changed historical archive "+name)
        with path.open(encoding="utf8",newline="") as f:
            tables[name]=list(csv.DictReader(f))
    grid={s:{"observe":{},"consult":{}} for s in range(40)}
    frozen={(int(r["seed"]),int(r["year"])):(r["initial_sha256"],r["years_sha256"])
            for r in tables["phase6c1/baseline/checkpoints.csv"]}
    require(len(frozen)==120,"incomplete historical economy")
    for offset,cohort in ((0,"dev"),(20,"holdout")):
        econ={(int(r["seed"]),int(r["year"])):(r["initial_sha256"],r["years_sha256"])
              for r in tables[f"phase6b2/study/{cohort}/runs.csv"] if r["arm"]=="D"}
        for r in tables[f"phase6c1/diplomacy/{cohort}/runs.csv"]:
            s,y,m=int(r["seed"]),int(r["year"]),r["mode"]
            require(offset<=s<offset+20 and y in HORIZONS and m in grid[s] and y not in grid[s][m],
                    "unexpected or duplicate historical checkpoint")
            require(frozen[s,y]==econ[s,y]==(r["initial_sha256"],r["economic_years_sha256"]),
                    "legacy references disagree")
            grid[s][m][y]={"initial":r["initial_sha256"],"economy":r["economic_years_sha256"],"civic":r["civic_years_sha256"]}
    require(all(set(rows)==set(HORIZONS) for case in grid.values() for rows in case.values()),"missing checkpoint")
    return grid,dict(PINS)


def check_pairs(seed,year,consult,rows,previous,previous_flows):
    require(set(rows)==set(PAIRS),"incomplete historical consultation pairs")
    observed=[]
    for (a,b),p in rows.items():
        require((p["seed"],p["year"],p["a"],p["b"])==(seed,year,a,b) and p["consult"] is consult,
                "wrong historical pair identity")
        audit_civic_pair(p, None if previous is None else previous[a,b])
        observed.extend(p["evidence"])
    sort=lambda records:sorted(records,key=lambda r:(r["source"],r["target"]))
    require(sort(observed)==sort(previous_flows),"pair evidence does not match the previous settled year")


def extension_line(year,rows):
    require(isinstance(rows,dict) and set(rows)==set(PAIRS),"incomplete enabled pair register")
    return canonical_line({"mode":"consult_on","year":year,"pairs":[rows[p] for p in PAIRS]})


def replay(job):
    from civsim.civic_followup64 import run
    seed,mode,pledges,expected=job
    world=regionalize(generate_world(seed))
    opening=sha256(canonical_line(snapshot62(start62(world)))).hexdigest()
    consult=mode=="consult"
    econ_digest,civic_digest=sha256(),sha256()
    pledge_digest=sha256() if pledges else None
    previous_ledger,previous_pairs,previous_flows=None,None,()
    comparison=[] if seed in EXTRA else None
    checkpoints=[]
    region_years=country_years=allocations=invoice_count=0
    expected_years=range(1,max(expected)+1)
    for y,result in zip(expected_years,run(seed,max(expected),consult=consult,pledges=pledges),strict=True):
        ledger,pairs,extra=result
        require((extra is not None)==pledges and ledger["year"]==y,"extension shape or historical chronology changed")
        if y==1:
            require([r["opening"] for r in ledger["regions"]]==[state(r) for r in world.regions] and
                    [n["opening"] for n in ledger["countries"]]==[state(n) for n in world.nations],"opening economy differs")
        audit62(ledger,geography=world,previous_record=previous_ledger)
        regional,countries=civic_year(ledger)
        region_years+=len(regional)
        country_years+=len(countries)
        aid=ledger["diplomacy"]["physical"]["aid"]
        allocations+=len(aid["donors"])
        invoice_count+=len(aid["shipments"])
        check_pairs(seed,y,consult,pairs,previous_pairs,previous_flows)
        economic_bytes=canonical_line(ledger)
        civic_bytes=canonical_line(dict(mode=mode,year=y,pairs=[pairs[p] for p in PAIRS]))
        econ_digest.update(economic_bytes)
        civic_digest.update(civic_bytes)
        if pledge_digest is not None:
            require(consult,"only consulted enabled paths sampled")
            pledge_digest.update(extension_line(y,extra))
        if comparison is not None:
            comparison.append((sha256(economic_bytes).digest(),sha256(civic_bytes).digest()))
        if y in expected:
            hashes={"initial":opening,"economy":econ_digest.hexdigest(),"civic":civic_digest.hexdigest()}
            require(hashes==expected[y],f"legacy digest mismatch for {seed}/{mode}/{pledges}/{y}")
            receipt={"year":y,**hashes}
            if pledge_digest is not None:
                receipt["pledge_years_sha256"]=pledge_digest.hexdigest()
            checkpoints.append(receipt)
        previous_pairs,previous_flows=pairs,closed_directions(seed,ledger)
        previous_ledger=ledger
    return (dict(seed=seed,mode=mode,pledges=pledges,years=len(expected_years),opening_matches=True,matched=checkpoints,
                 region_years=region_years,country_years=country_years,pair_years=len(PAIRS)*len(expected_years),
                 donor_accounts_checked=allocations,public_aid_invoices_checked=invoice_count),comparison)


def crosscheck_study(cases,root):
    """Match each live digest to the independently produced follow-up study table."""
    source={}
    archived={}
    for cohort in ("dev","holdout"):
        folder=root/cohort
        path=folder/"runs.csv"
        digest=sha256(path.read_bytes()).hexdigest()
        require(digest==json.loads((folder/"execution.json").read_bytes())["table_sha256"]["runs.csv"],
                "follow-up study table is unverified")
        source[cohort]=digest
        with path.open(encoding="utf8",newline="") as f:
            for r in csv.DictReader(f):
                k=int(r["seed"]),r["mode"],r["pledges"],int(r["year"])
                require(k not in archived,"duplicate follow-up study cell")
                archived[k]=r
    on=off=0
    for case in cases:
        enabled=case["pledges"]
        for y in case["matched"]:
            r=archived[case["seed"],case["mode"],"on" if enabled else "off",y["year"]]
            require((y["initial"],y["economy"],y["civic"])==
                    (r["initial_sha256"],r["economic_years_sha256"],r["civic_years_sha256"]),
                    "follow-up study changed historical bytes")
            new_hash=y["pledge_years_sha256"] if enabled else y["civic"]
            require(new_hash==r["register_sha256"],"live serialized register differs from follow-up study")
            on+=int(enabled)
            off+=int(not enabled)
    return dict(runs_sha256=source,enabled_register_checkpoints=on,disabled_register_checkpoints=off)


def verify(workers,study_root=ROOT/"phase6c1-followup"/"pledges"):
    require(type(workers) is int and workers>0,"workers must be positive")
    started=perf_counter()
    refs,pins=load_references()
    jobs=[(s,"consult",False,refs[s]["consult"]) for s in refs]
    for s in EXTRA:
        jobs.extend(((s,"observe",False,refs[s]["observe"]),(s,"consult",True,refs[s]["consult"])))
    cases=[]
    by_seed={}
    with ProcessPoolExecutor(max_workers=min(workers,len(jobs))) as pool:
        for case,traces in pool.map(replay,jobs):
            cases.append(case)
            if traces is not None:
                by_seed[case["seed"],case["mode"],case["pledges"]]=traces
    for s in EXTRA:
        base=by_seed[s,"consult",False]
        require(by_seed[s,"consult",True]==base,"enabled extension modified an annual legacy record")
        require([e[0] for e in by_seed[s,"observe",False]]==[e[0] for e in base],
                "observe and consult economies differ by year")
    return dict(reference_revision="2114ca3",source_sha256=pins,study_comparison=crosscheck_study(cases,study_root),
                checkpoints=list(HORIZONS),samples={"dev":[0,19],"holdout":[20,39]},
                disabled_consult=dict(seeds=40,opening_hashes=40,checkpoint_pairs=120,world_years=8000),
                disabled_observe=dict(seeds=list(EXTRA),opening_hashes=2,checkpoint_pairs=6,world_years=400),
                enabled_consult=dict(seeds=list(EXTRA),opening_hashes=2,checkpoint_pairs=6,world_years=400,
                                     legacy_annual_pairs_identical=400),
                independent_audit={k:sum(c[k] for c in cases) for k in
                                   ("years","region_years","country_years","pair_years","donor_accounts_checked","public_aid_invoices_checked")},
                paths=cases,workers=min(workers,len(jobs)),wall_seconds=round(perf_counter()-started,3))


def publish_receipt(path,report):
    if os.path.lexists(path):
        raise FileExistsError(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=path.parent) as tmp:
        file=Path(tmp)/"receipt.json"
        file.write_text(json.dumps(report,sort_keys=True,indent=2)+"\n",encoding="utf8",newline="\n")
        publish_file(file,path)


def compare_release(first,repeat,output):
    blobs=[p.read_bytes() for p in (first,repeat)]
    data=[json.loads(b) for b in blobs]
    times=[r.pop("wall_seconds") for r in data]
    require(data[0]==data[1],"repeat differs in fields other than elapsed time")
    common=data[0]
    require(common["reference_revision"]=="2114ca3" and len(common["paths"])==44,
            "unexpected compatibility release")
    report=dict(
        first={"file":first.name,"file_sha256":sha256(blobs[0]).hexdigest(),"wall_seconds":times[0]},
        repeat={"file":repeat.name,"file_sha256":sha256(blobs[1]).hexdigest(),"wall_seconds":times[1]},
        comparison=dict(omitted_fields=["wall_seconds"],all_remaining_fields_identical=True,
                        normalized_sha256=sha256(canonical_line(common)).hexdigest(),
                        encoding="Sorted-key compact JSON as UTF-8 with literal Unicode and one final LF"),
        reference_revision=common["reference_revision"],paths=len(common["paths"]),
        annual_economic_records=common["independent_audit"]["years"],
        economic_civic_checkpoint_pairs=sum(len(path["matched"]) for path in common["paths"]),
        enabled_register_matches=common["study_comparison"]["enabled_register_checkpoints"],
        first_procedure="Replayed 44 live paths. The six additional register digests were joined after two separately repeated enabled paths matched their original economic and civic receipts. The first wall time covers the 44 paths.",
        repeat_procedure="One complete invocation generated the 44 paths, all three hash series and the comparisons to the published study.")
    publish_receipt(output,report)
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers",type=int,default=8)
    parser.add_argument("--study",type=Path,default=ROOT/"phase6c1-followup"/"pledges")
    parser.add_argument("--compare-release",nargs=2,type=Path,metavar=("FIRST","REPEAT"))
    parser.add_argument("--out",required=True,type=Path)
    args=parser.parse_args()
    if os.path.lexists(args.out):
        raise FileExistsError(args.out)
    if args.compare_release:
        compare_release(*args.compare_release,args.out)
        print("The two compatibility receipts agree on every field except elapsed time.")
    else:
        result=verify(args.workers,args.study)
        publish_receipt(args.out,result)
        print(f"Verified {len(result['paths'])} paths in {result['wall_seconds']} seconds.")
