"""Run the three-year integration gate and publish complete reproducible annual ledgers."""
import argparse
from copy import deepcopy
from dataclasses import asdict, replace
import gzip
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from civsim import peace62
from civsim.model import generate_world
from civsim.regions import regionalize
from civsim.storage import canonical_line
from civsim.unit_economy import AnnualUnitGame, Move, audit_game, location_totals, step_game
from experiments.annual_unit_study import ORDER, digest
from experiments.unit_economy_metrics import civil_totals


def require(ok, message):
    if not ok:
        raise ValueError(message)


def opening(narrow=False):
    world = regionalize(generate_world(0))
    if narrow:
        world.roads = [replace(e,capacity=1) if (e.a,e.b)==(0,3) else e for e in world.roads]
    game = AnnualUnitGame(peace62.start62(world))
    first = peace62.step62(game.economy,1,"C")
    return game, first


def measures(row):
    gov = row["government"]
    result = civil_totals(row)
    by_id = {e["region"]:e for e in gov["depots"]}
    positions = location_totals(row,"closing")
    for r in row["regions"]:
        i = r["id"]
        result["regions"][i].update(population=r["closing"]["population"], cash=r["closing"]["cash"],
                                    depot_close=by_id[i]["closing"], units_present=positions[i])
    result["road"] = next(e for e in gov["roads"] if (e["a"],e["b"])==(4,5))
    result["world"]["cash"] = sum(c["closing"]["cash"] for c in row["countries"])
    return result


def write_ledger(out, name, rows):
    with (out/name).open("xb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            for row in rows:
                zipped.write(canonical_line(row))


def case(out):
    out.mkdir(parents=True,exist_ok=False)
    game, first = opening()
    control = deepcopy(game)
    initial = peace62.snapshot62(game.economy)
    require(initial==peace62.snapshot62(control.economy),"opening fork differs")
    write_ledger(out,"year2-opening.json.gz",[initial])
    write_ledger(out,"year1.jsonl.gz",[first])
    movement = step_game(game,ORDER)
    hold = step_game(control)
    before = game.away
    successor = step_game(game)
    successor_hold = step_game(control)
    for pair in ((movement,successor),(hold,successor_hold)):
        audit_game(pair[0],game.economy.world,previous=first)
        audit_game(pair[1],game.economy.world,previous=pair[0])
    write_ledger(out,"move-years2-3.jsonl.gz",[movement,successor])
    write_ledger(out,"hold-years2-3.jsonl.gz",[hold,successor_hold])
    receipt=movement["unit_game"]["receipt"]
    require(receipt["ok"] and receipt["count"]==1 and receipt["road_used"]==1 and receipt["food_spent"]==1,
            "real move did not settle")
    require(before==successor["unit_game"]["opening_away"]==[[5,4,1]],"lost closing position")
    road=next(e for e in game.economy.world.roads if (e.a,e.b)==tuple(receipt["road"]))
    summary={"seed":0, "year":2, "opening_sha256":digest(initial), "road":asdict(road),"receipt":receipt,
             "opening_roster_home5":initial["service_roster"][5],
             "closing_away":before,"next_opening_away":successor["unit_game"]["opening_away"],
             "move":measures(movement),"hold":measures(hold), "failures":[]}
    for name, order, narrow in (("empty_store",Move(4,4,5,1),False),
                                ("roster_exceeded",Move(5,5,4,99999),False),
                                ("exhausted_road",Move(3,3,0,1),True)):
        g, _ = opening(narrow)
        frozen=deepcopy(g)
        failed,held=step_game(g,order),step_game(frozen)
        a,b=failed["unit_game"],held["unit_game"]
        require(not a["receipt"]["ok"] and a["receipt"]["food_spent"]==0 and a["receipt"]["road_used"]==0 and
                a["closing_away"]==b["closing_away"],"denial changed physical state")
        without_cmd=lambda r: {k:v for k,v in r.items() if k!="unit_game"}
        ha,hb = digest(without_cmd(failed)),digest(without_cmd(held))
        require(ha==hb and peace62.snapshot62(g.economy)==peace62.snapshot62(frozen.economy),
                "failed command changed the economy")
        edge=next(r for r in failed["government"]["roads"] if [r["a"],r["b"]]==a["receipt"]["road"])
        summary["failures"].append({"case":name,"command":asdict(order),"receipt":a["receipt"],
                                    "map_override":{"road":[0,3],"base_capacity":1} if narrow else None,
                                    "road":edge,"failed_economy_sha256":ha,"held_economy_sha256":hb,
                                    "closing_state_sha256":digest(peace62.snapshot62(g.economy))})
        write_ledger(out, name+".jsonl.gz",[failed,held])
    (out/"results.json").write_text(json.dumps(summary,sort_keys=True,ensure_ascii=True,indent=2)+"\n",
                                   encoding="utf-8",newline="\n")


def verify(reference):
    with TemporaryDirectory() as tmp:
        repeat=Path(tmp)/"case"
        case(repeat)
        expected={p.name:p for p in reference.iterdir() if p.is_file()}
        actual={p.name:p for p in repeat.iterdir()}
        require(expected.keys()==actual.keys(),"different case files")
        for name,path in actual.items():
            a,b=path.read_bytes(),expected[name].read_bytes()
            if name.endswith(".gz"):
                a,b=gzip.decompress(a),gzip.decompress(b)
            require(a==b,"replay differs: "+name)
        return {name:sha256(path.read_bytes()).hexdigest() for name,path in sorted(expected.items())}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    target=parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--out",type=Path)
    target.add_argument("--verify",type=Path)
    args=parser.parse_args()
    if args.out:
        case(args.out)
        print("Published audited one-year move/hold, successor and three denials.")
    else:
        print(json.dumps(verify(args.verify), sort_keys=True))
