"""Play one full economic year per command, using immutable replay-checked save slots."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

from .game_journal import append_turn, new_journal, restore_journal, save_json_slot
from .model import generate_world
from .peace62 import start62
from .regions import regionalize
from .storage import canonical_line
from .unit_economy import AnnualUnitGame, Move, step_game


def create(seed):
    return AnnualUnitGame(start62(regionalize(generate_world(seed))))


def play(game, command):
    selection = None
    priority = None
    public_farm = None
    if isinstance(command, dict) and ("upkeep" in command or "public_farm" in command):
        from .unit_upkeep import Upkeep
        if "move" not in command or command.keys() - {"upkeep", "move", "relief_first", "public_farm"}:
            raise ValueError("invalid game inventory command")
        priority = command.get("relief_first")
        if "upkeep" in command:
            selection = Upkeep(**command["upkeep"])
        public_farm = command.get("public_farm")
        command = command["move"]
    record = step_game(game, None if command is None else Move(**command), upkeep=selection,
                       relief_first=priority, public_farm=public_farm)
    # Historical annual records contain tuples and integer keys. Use exactly
    # their published JSON representation at the journal boundary.
    return json.loads(canonical_line(record))


def save(path, journal, away, upkeep=None, *, public_farm=False):
    slot = {"schema":"annual-game/1","journal":journal,"closing_away":away}
    if upkeep is not None:
        slot.update(schema="annual-game/2", game_upkeep=upkeep)
    if public_farm:
        slot.update(schema="annual-game/3", public_farm=True)
    save_json_slot(path,slot)


def load(path, *, observer=None):
    def replay_step(game,command):
        row = play(game,command)
        if observer is not None:
            observer.observe(row)
        return row

    slot = json.loads(path.read_bytes())
    if isinstance(slot,dict) and slot.get("schema")=="game-journal/1":
        # Early replay-only slots published with this branch.
        return slot, restore_journal(slot,create,replay_step)
    fields = {"schema","journal","closing_away"}
    schemas = {"annual-game/1":fields, "annual-game/2":fields | {"game_upkeep"}}
    harvest_slot = type(slot) is dict and slot.get("schema") == "annual-game/3"
    if harvest_slot:
        schemas["annual-game/3"] = fields | {"public_farm"} | ({"game_upkeep"} if "game_upkeep" in slot else set())
    if type(slot) is not dict or slot.keys() != schemas.get(slot.get("schema")) or (harvest_slot and slot["public_farm"] is not True):
        raise ValueError("invalid annual game save")
    game = restore_journal(slot["journal"],create,replay_step)
    if harvest_slot != game.economy.public_farm:
        raise ValueError("saved public harvest rule disagrees with replay")
    if canonical_line(slot["closing_away"])!=canonical_line(game.away):
        raise ValueError("saved locations disagree with the replayed closing ledger")
    if (("game_upkeep" in slot) != (game.economy.game_upkeep is not None)
            or canonical_line(slot.get("game_upkeep")) != canonical_line(game.economy.game_upkeep)):
        raise ValueError("saved game inventory disagrees with replay")
    return slot["journal"], game


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action",required=True)
    new = commands.add_parser("new",help="start a generated civilization world")
    new.add_argument("--seed",type=int,default=0)
    new.add_argument("--out",type=Path,required=True)
    advance = commands.add_parser("step",help="play the next annual economy with an optional one-edge move")
    advance.add_argument("save",type=Path)
    advance.add_argument("--move",nargs=4,type=int,metavar=("HOME","FROM","TO","COUNT"))
    advance.add_argument("--upkeep", nargs=2, type=int, metavar=("HOME","COUNT"),
                         help="mark up to two existing game pieces for local inventory checkout each turn")
    advance.add_argument("--out",type=Path,required=True)
    advance.add_argument("--relief-first",action="store_true",help="give domestic relief first claim on inventory")
    advance.add_argument("--public-farm",action="store_true",help="assign part of the existing crop to local reserves from this year")
    show = commands.add_parser("show",help="replay and check a save")
    show.add_argument("save",type=Path)
    show.add_argument("--custody",action="store_true",help="include audited meal, office and population receipts")
    args = parser.parse_args(argv)
    try:
        if args.action == "new":
            journal = new_journal(args.seed)
            save(args.out,journal,[])
            result = {"seed":args.seed,"year":0,"closing_away":[]}
        else:
            observer = None
            if args.action == "show" and args.custody:
                from .regional_custody import CustodyObserver
                observer = CustodyObserver()
            journal, game = load(args.save,observer=observer)
            if args.action == "show":
                result = {"seed":journal["seed"],"year":game.economy.world.year,"closing_away":game.away}
                if game.economy.game_upkeep is not None:
                    result["game_upkeep"] = game.economy.game_upkeep
                if game.economy.public_farm:
                    result["public_farm"] = True
                if observer is not None:
                    result["custody"] = observer.latest
            else:
                command = asdict(Move(*args.move)) if args.move is not None else None
                if args.upkeep is not None:
                    from .unit_upkeep import Upkeep
                    command = {"move":command, "upkeep":asdict(Upkeep(*args.upkeep))}
                if args.relief_first:
                    if args.upkeep is None:
                        raise ValueError("--relief-first requires --upkeep HOME COUNT at activation")
                    command["relief_first"] = True
                if args.public_farm:
                    if args.upkeep is None:
                        command = {"move":command}
                    command["public_farm"] = True
                row = play(game,command)
                save(args.out,append_turn(journal,command,row),game.away,game.economy.game_upkeep,
                     public_farm=game.economy.public_farm)
                result = {"year":row["year"],**row["unit_game"]}
                if "unit_upkeep" in row:
                    result["unit_upkeep"] = row["unit_upkeep"]
                if "public_harvest" in row:
                    result["public_harvest"] = row["public_harvest"]
        print(json.dumps(result,sort_keys=True))
    except (ValueError,OSError,TypeError) as exc:
        parser.exit(2,f"{parser.prog}: {exc}\n")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
