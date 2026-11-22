"""Audited real game turns; outputs are exclusive-create and replayable."""
import argparse
from copy import deepcopy
import gzip
from hashlib import sha256
from pathlib import Path

from civsim.annual_game import create
from civsim.peace62 import snapshot62
from civsim.regional_custody import CustodyObserver
from civsim.storage import canonical_line
from civsim.unit_economy import Move, audit_game, step_game
from civsim.unit_upkeep import Upkeep
from experiments.turn_civil_balances import paired_civil_delta, turn_civil_balances


def case(out):
    out.mkdir(parents=True, exist_ok=False)
    original = create(0)
    first = step_game(original)
    opening = sha256(canonical_line(snapshot62(original.economy))).hexdigest()
    paths = {}
    records = {}
    for name, move, selection in (
        ("move_off",Move(5,5,7,2),None), ("move_on",Move(5,5,7,2),Upkeep(5,2)),
        ("hold_on",None,Upkeep(5,2)), ("one",Move(5,5,7,1),Upkeep(5,1)),
        ("empty",Move(5,5,4,1),Upkeep(5,1)),
    ):
        g = deepcopy(original)
        observer = CustodyObserver()
        observer.observe(first)
        paths[name] = []
        records[name] = []
        previous = first
        data = bytearray(canonical_line(first))
        for year in (2,3):
            row = step_game(g, move if year == 2 else None, upkeep=selection if year == 2 else None)
            audit_game(row,g.economy.world,previous)
            observer.observe(row)
            data.extend(canonical_line(row))
            paths[name].append({"year":year, "move":row["unit_game"], "issue":row.get("unit_upkeep"),
                                "civil":turn_civil_balances(row), "sha256":sha256(canonical_line(row)).hexdigest()})
            previous = row
            records[name].append(row)
        with (out / (name+".jsonl.gz")).open("xb") as stream:
            stream.write(gzip.compress(bytes(data),mtime=0))
    diffs = {}
    for control in ("move_off","hold_on"):
        diffs["move_on_minus_"+control] = [
            paired_civil_delta(a,b) for a,b in zip(records[control], records["move_on"],strict=True)]
    # Separate same-opening example of relief and private deliveries competing for food.
    game = create(0)
    for _ in range(6):
        last = step_game(game)
    other = deepcopy(game)
    off = step_game(game)
    on = step_game(other,upkeep=Upkeep(5,2))
    for row in (off,on):
        audit_game(row,game.economy.world,last)
    competition = {"seed":0,"year":7,"home":5,"issue":on["unit_upkeep"],
                   "off":turn_civil_balances(off),"on":turn_civil_balances(on),
                   "delta":paired_civil_delta(off,on),
                   "sha256":[sha256(canonical_line(row)).hexdigest() for row in (off,on)]}
    with (out/"comparison.json").open("xb") as f:
        f.write(canonical_line({"seed":0,"year2_opening_sha256":opening,"paths":paths,"deltas":diffs,
                                "relief_example":competition}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True)
    case(parser.parse_args().out)
