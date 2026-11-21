"""Play one full economic year per command, using immutable replay-checked save slots."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

from .game_journal import append_turn, new_journal, restore_journal, save_journal
from .model import generate_world
from .peace62 import start62
from .regions import regionalize
from .storage import canonical_line
from .unit_economy import AnnualUnitGame, Move, step_game


def create(seed):
    return AnnualUnitGame(start62(regionalize(generate_world(seed))))


def play(game, command):
    record = step_game(game, None if command is None else Move(**command))
    # Historical annual records contain tuples and integer keys. Use exactly
    # their published JSON representation at the journal boundary.
    return json.loads(canonical_line(record))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action",required=True)
    new = commands.add_parser("new",help="start a generated civilization world")
    new.add_argument("--seed",type=int,default=0)
    new.add_argument("--out",type=Path,required=True)
    advance = commands.add_parser("step",help="play the next annual economy with an optional one-edge move")
    advance.add_argument("save",type=Path)
    advance.add_argument("--move",nargs=4,type=int,metavar=("HOME","FROM","TO","COUNT"))
    advance.add_argument("--out",type=Path,required=True)
    commands.add_parser("show",help="replay and check a save").add_argument("save",type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "new":
            journal = new_journal(args.seed)
            save_journal(args.out,journal)
            result = {"seed":args.seed,"year":0,"closing_away":[]}
        else:
            journal = json.loads(args.save.read_bytes())
            game = restore_journal(journal,create,play)
            if args.action == "show":
                result = {"seed":journal["seed"],"year":game.economy.world.year,"closing_away":game.away}
            else:
                command = asdict(Move(*args.move)) if args.move is not None else None
                row = play(game,command)
                save_journal(args.out,append_turn(journal,command,row))
                result = {"year":row["year"],**row["unit_game"]}
        print(json.dumps(result,sort_keys=True))
    except (ValueError,OSError,TypeError) as exc:
        parser.exit(2,f"{parser.prog}: {exc}\n")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
