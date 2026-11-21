"""Two-space token-game regression evidence. Games are independent of annual economic worlds."""
import argparse
from collections import Counter
from contextlib import contextmanager
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import platform
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

from civsim.unit_board import UnitBoard


HORIZONS = (50, 100, 200)
FILES = ("short-cases.json", "seeds.csv", "traces.jsonl.gz", "summary.json")


def canonical_line(value):
    return (json.dumps(value,ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(",",":"))+"\n").encode("utf8")


def write_json(path,value):
    with path.open("x",encoding="utf8",newline="\n") as f:
        json.dump(value,f,indent=2,sort_keys=True,ensure_ascii=False)
        f.write("\n")


@contextmanager
def compressed(path):
    with path.open("xb") as raw, gzip.GzipFile(filename="",fileobj=raw,mode="wb",compresslevel=4,mtime=0) as packed:
        with io.TextIOWrapper(packed,encoding="utf8",newline="") as text:
            yield text


def sample_board(*, food=3, capacity=3, remaining=None):
    return UnitBoard.create(population={0:9,1:6}, roster={(0,1):3,(1,0):2}, food={0:food,1:2},
                            edge=(0,1), capacity=capacity, remaining=remaining)


def play_move(board, count):
    return board.move(home=0,affiliation=1,source=0,destination=1,count=count)


def restored_next_turn(snapshot, scratch):
    savefile=scratch/"board.json"
    write_json(savefile,snapshot)
    command=[sys.executable,"-B","-m","experiments.unit_board_trials","--load-one-turn",str(savefile)]
    raw=subprocess.run(command,check=True,stdout=subprocess.PIPE).stdout
    return json.loads(raw)


def production_pool(snapshot):
    unassigned={r["id"]:r["population"] for r in snapshot["nodes"]}
    for r in snapshot["roster"]:
        unassigned[r["home"]]-=r["count"]
    return unassigned


def small_cases(staging):
    result={}
    for case,options in (("success",{}),("no_food",{"food":0}),("no_capacity",{"remaining":0})):
        b=sample_board(**options)
        opening=b.snapshot()
        receipt=play_move(b,2)
        closing=b.snapshot()
        resumed=None
        if case=="success":
            with TemporaryDirectory(dir=staging) as temp:
                resumed=restored_next_turn(closing,Path(temp))
        b.next_turn()
        result[case]={"opening":opening,"input":{"home":0,"affiliation":1,"source":0,"destination":1,"count":2},
                      "receipt":receipt,"after":closing,"next_turn":b.snapshot()}
        if resumed is not None:
            if resumed!={"loaded":closing,"next_turn":b.snapshot()}:
                raise ValueError("restoration in a new process lost state")
            result[case]["fresh_process"]=resumed
        elif closing!=opening or receipt["ok"] or receipt["food_spent"] or receipt["road_used"]:
            raise ValueError("rejected move changed the state or charged a cost")
    return result


def zero_maximum():
    b=sample_board(capacity=0)
    before=b.snapshot()
    receipt=play_move(b,2)
    after=b.snapshot()
    b.next_turn()
    if (receipt["ok"] or receipt["reason"]!="insufficient_capacity" or after!=before or b.remaining!=0):
        raise ValueError("zero maximum turn limit allowed a charge or replenishment")
    return {"opening":before,"receipt":receipt,"after":after,"next_turn":b.snapshot()}


def verify_state(opening,state,turn,paid):
    if (state["turn"]!=turn or state["roster"]!=opening["roster"] or
            production_pool(state)!=production_pool(opening) or
            [(r["id"],r["population"]) for r in state["nodes"]]!=[(r["id"],r["population"]) for r in opening["nodes"]]):
        raise ValueError("game clock, residence, roster or production pool changed unexpectedly")
    positions=Counter({(r["home"],r["affiliation"],r["location"]):r["count"] for r in opening["positions"]})
    if paid:
        positions[0,1,0]-=1
        positions[0,1,1]+=1
    expected={k:v for k,v in positions.items() if v}
    actual={(r["home"],r["affiliation"],r["location"]):r["count"] for r in state["positions"]}
    if actual!=expected or len(actual)!=len(state["positions"]) or len(state["moves"])!=paid:
        raise ValueError("tokens vanished, duplicated or returned to their starting space")
    if state["remaining"]!=(opening["remaining"]-paid if turn==1 else opening["capacity"]):
        raise ValueError("turn limit changed incorrectly")
    for a,b in zip(opening["nodes"],state["nodes"],strict=True):
        spent=paid if a["id"]==0 else 0
        if a["food"]-b["food"]!=spent or b["food_spent"]!=spent:
            raise ValueError("departure resource was double charged or incorrectly replenished")


def play_seed(seed,raw):
    from civsim.unit_board_scenario import demo_board
    move=demo_board(seed)
    opening=move.snapshot()
    hold=UnitBoard.restore(opening)
    if hold.snapshot()!=opening:
        raise ValueError("paired games have different openings")
    receipt=play_move(move,1)
    histories={mode:hashlib.sha256() for mode in ("move","hold")}
    rows=[]
    for turn in range(1,201):
        for mode,board in (("move",move),("hold",hold)):
            if turn>1:
                board.next_turn()
            state=board.snapshot()
            paid=int(mode=="move" and receipt["ok"])
            verify_state(opening,state,turn,paid)
            histories[mode].update(canonical_line(state))
            raw.write(canonical_line({"seed":seed,"mode":mode,"turn":turn,"state":state}).decode("utf8"))
            if turn not in HORIZONS:
                continue
            target=sum(r["count"] for r in state["positions"] if (r["home"],r["affiliation"],r["location"])==(0,1,1))
            nodes={r["id"]:r for r in state["nodes"]}
            pools=production_pool(state)
            rows.append({"seed":seed,"mode":mode,"turn":turn,"initial_sha256":hashlib.sha256(canonical_line(opening)).hexdigest(),
                         "states_sha256":histories[mode].hexdigest(),"requested_moves":int(mode=="move"),
                         "paid_moves":len(state["moves"]),"tokens_at_destination_in_group":target,
                         "food_0":nodes[0]["food"],"food_1":nodes[1]["food"],"spent_0":nodes[0]["food_spent"],
                         "remaining":state["remaining"],"unassigned_home_0":pools[0],"unassigned_home_1":pools[1]})
    return rows


def run(output,*,verify=None):
    output=Path(output)
    if output.exists():
        raise FileExistsError(output)
    start=time.perf_counter()
    subprocess.run([sys.executable,"-B","-m","unittest","tests.test_unit_board_trials","-q"],check=True)
    output.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=output.parent,prefix=".two-space-") as scratch:
        stage=Path(scratch)/"result"
        stage.mkdir()
        cases=small_cases(Path(scratch))
        write_json(stage/"short-cases.json",cases)
        rows=[]
        with compressed(stage/"traces.jsonl.gz") as raw:
            for seed in range(40):
                rows.extend(play_seed(seed,raw))
        with (stage/"seeds.csv").open("x",encoding="utf8",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=tuple(rows[0]),lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        final=[r for r in rows if r["turn"]==200 and r["mode"]=="move"]
        summary={"source":"standalone two-space game fixtures","seeds":40,"turns_per_game":200,
                 "turns_with_move_policy":8000,"turns_with_hold_policy":8000,"checkpoint_rows":len(rows),
                 "unique_openings":len({r["initial_sha256"] for r in final}),"move_commands":40,
                 "accepted_on_turn_one":sum(r["paid_moves"] for r in final),
                 "original_group_present_at_destination_on_turn_200":sum(r["tokens_at_destination_in_group"]>0 for r in final),
                 "failed_on_turn_one":sum(r["paid_moves"]==0 for r in final),
                 "six_short_checks_passed_before_games":True,
                 "controlled_failures":{k:v["receipt"]["reason"] for k,v in cases.items() if not v["receipt"]["ok"]}}
        write_json(stage/"summary.json",summary)
        hashes={}
        for n in FILES:
            content=(stage/n).read_bytes()
            hashes[n]=hashlib.sha256(content).hexdigest()
            if verify is not None and (Path(verify)/n).read_bytes()!=content:
                raise ValueError(f"standalone repeat differs in {n}")
        meta={"python":platform.python_version(),"wall_seconds":time.perf_counter()-start,
              "science_sha256":hashes,"byte_compared_files":len(FILES) if verify else 0}
        write_json(stage/"execution.json",meta)
        if output.exists():
            raise FileExistsError(output)
        stage.rename(output)
    return meta


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument("--out",type=Path)
    group.add_argument("--load-one-turn",type=Path)
    group.add_argument("--zero-maximum-out",type=Path)
    p.add_argument("--verify-against",type=Path)
    args=p.parse_args()
    if args.load_one_turn:
        board=UnitBoard.restore(json.loads(args.load_one_turn.read_bytes()))
        loaded=board.snapshot()
        board.next_turn()
        print(json.dumps({"loaded":loaded,"next_turn":board.snapshot()}))
    elif args.zero_maximum_out:
        write_json(args.zero_maximum_out,zero_maximum())
    else:
        print(json.dumps(run(args.out,verify=args.verify_against)))
