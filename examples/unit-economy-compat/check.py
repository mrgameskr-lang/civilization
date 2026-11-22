"""Compare existing replay artifacts to the original Git object, without altering the repository."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[2]
PIN = "b0490cdd8c987342258f992f4234f3c8a3330614"
GAMES = ("short-cases.json", "seeds.csv", "traces.jsonl.gz", "summary.json")
GRID = {(s,y) for s in range(40) for y in (50,100,200)}


def original(name):
    return subprocess.run(["git","cat-file","blob",PIN+":"+name],cwd=ROOT,
                          stdout=subprocess.PIPE,check=True).stdout


def sha(content):
    return hashlib.sha256(content).hexdigest()


def publish(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("x",encoding="utf8",newline="\n") as stream:
        json.dump(value,stream,ensure_ascii=False,sort_keys=True,indent=2)
        stream.write("\n")


def module(name, *args):
    subprocess.run([sys.executable,"-B","-X","utf8","-m",name,*map(str,args)],cwd=ROOT,
                   check=True,stdout=subprocess.PIPE)


def game_comparison(scratch):
    scratch=Path(scratch)
    paths=("civsim/unit_board.py","civsim/unit_board_scenario.py","civsim/unit_game.py",
           "experiments/unit_board_trials.py")
    source_hashes={p:sha((ROOT/p).read_bytes()) for p in paths}
    current={}
    checks=ROOT/"examples/unit-board-checks"
    demo=ROOT/"examples/unit-board-v1"
    module("civsim.unit_game","new","--seed","0","--out",scratch/"start.json")
    module("civsim.unit_game","move",scratch/"start.json","--home","0","--affiliation","1",
           "--from","0","--to","1","--count","1","--out",scratch/"moved.json")
    module("civsim.unit_game","next",scratch/"moved.json","--out",scratch/"turn-2.json")
    trial=scratch/"repeat"
    module("experiments.unit_board_trials","--out",trial,"--verify-against",demo)
    module("experiments.unit_board_trials","--zero-maximum-out",scratch/"zero-maximum.json")
    for src, dest in [(scratch/n,checks/n) for n in ("start.json","moved.json","turn-2.json")] + [
            (trial/n,demo/n) for n in GAMES] + [(scratch/"zero-maximum.json",demo/"zero-maximum.json")]:
        label=dest.relative_to(ROOT).as_posix()
        expected=original(label)
        if src.read_bytes()!=expected or dest.read_bytes()!=expected:
            raise ValueError("replayed bytes differ from pinned baseline in "+label)
        current[label]=sha(expected)
    if any(sha((ROOT/p).read_bytes())!=value for p,value in source_hashes.items()):
        raise ValueError("game source changed during the replay")
    return {"reference_commit":PIN,"working_source_sha256":source_hashes,"independent_game_only":True,"world_years":0,"seeds":40,
            "turns_per_path":200,"turn_states":16000,"seed_path_checkpoints":240,
            "pinned_files_compared":len(current),"original_and_regenerated_sha256":current}


def annual_comparison(folder):
    refs={"A":("legacy-a.json","examples/phase6c1-m1/pr18-replay.json",3),
          "B":("legacy-b.json","examples/phase6c1-m1/register-repeat.json",2)}
    final={}
    for key,(name,ref,streams) in refs.items():
        reference_bytes=original(ref)
        baseline=json.loads(reference_bytes)
        fresh_bytes=(folder/name).read_bytes()
        fresh=json.loads(fresh_bytes)
        if (ROOT/ref).read_bytes()!=reference_bytes:
            raise ValueError("historical receipt file changed: "+ref)
        rows=fresh["checkpoints"]
        if (fresh["world_years"]!=8000 or len(rows)!=len(GRID) or
                {(r["seed"],r["year"]) for r in rows}!=GRID or rows!=baseline["checkpoints"]):
            raise ValueError("incomplete or divergent annual checkpoint table: "+ref)
        metadata=lambda r:{k:v for k,v in r.items() if k not in {"wall_seconds","workers"}}
        if metadata(fresh)!=metadata(baseline):
            raise ValueError("a scientific receipt field differs: "+ref)
        final[key]={"original_path":ref,"original_receipt_sha256":sha(reference_bytes),
                    "replayed_receipt_sha256":sha(fresh_bytes),"world_years":fresh["world_years"],
                    "checkpoints":len(rows),"streams_per_checkpoint":streams,"matched_digests":len(rows)*streams,
                    "workers_in_source_receipt":fresh.get("workers"),"wall_seconds":fresh["wall_seconds"]}
    return {"reference_commit":PIN,"seeds_each_path":40,"annual_horizons":[50,100,200],"paths":final,
            "matched_digests":sum(v["matched_digests"] for v in final.values())}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("part",choices=("games","annual"))
    parser.add_argument("--out",required=True,type=Path)
    parser.add_argument("--receipts",type=Path,default=Path(__file__).resolve().parent)
    args=parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    if args.part=="games":
        args.out.parent.mkdir(parents=True,exist_ok=True)
        with TemporaryDirectory(dir=args.out.parent) as work:
            result=game_comparison(work)
    else:
        result=annual_comparison(args.receipts)
    publish(args.out,result)
