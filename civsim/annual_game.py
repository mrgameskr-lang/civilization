"""Play one full economic year per command, using immutable replay-checked save slots."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

from .game_journal import append_turn, new_journal, restore_journal, save_json_slot
from .model import generate_world
from .peace62 import start62
from .public_harvest import RESERVE_POLICIES
from .regions import regionalize
from .storage import canonical_line
from .unit_economy import AnnualUnitGame, Move, step_game


def create(seed):
    return AnnualUnitGame(start62(regionalize(generate_world(seed))))


def play(game, command):
    selection = None
    priority = None
    public_farm = None
    reserve_policy = None
    research = None
    diffusion = None
    blocked_migration = None
    options = {"upkeep", "public_farm", "reserve_policy", "research", "diffusion", "blocked_migration"}
    if isinstance(command, dict) and command.keys() & options:
        from .unit_upkeep import Upkeep
        if "move" not in command or command.keys() - (options | {"move", "relief_first"}):
            raise ValueError("invalid game inventory command")
        priority = command.get("relief_first")
        if "upkeep" in command:
            selection = Upkeep(**command["upkeep"])
        public_farm = command.get("public_farm")
        reserve_policy = command.get("reserve_policy")
        if "research" in command:
            research = command["research"]
            if type(research) is not bool:
                raise ValueError("research must be a boolean")
        if "diffusion" in command:
            diffusion = command["diffusion"]
            if type(diffusion) is not bool:
                raise ValueError("diffusion must be a boolean")
        if "blocked_migration" in command:
            edge = command["blocked_migration"]
            if (type(edge) is not list or len(edge) != 2 or any(type(i) is not int for i in edge)
                    or not 0 <= edge[0] < edge[1]):
                raise ValueError("blocked_migration requires two increasing domestic region IDs")
            blocked_migration = tuple(edge)
        command = command["move"]
    record = step_game(game, None if command is None else Move(**command), upkeep=selection,
                       relief_first=priority, public_farm=public_farm, reserve_policy=reserve_policy,
                       research=research, diffusion=diffusion, blocked_migration=blocked_migration)
    # Historical annual records contain tuples and integer keys. Use exactly
    # their published JSON representation at the journal boundary.
    return json.loads(canonical_line(record))


def save(path, journal, away, upkeep=None, *, public_farm=False, reserve_policy=None, research=None,
         diffusion=None):
    slot = {"schema":"annual-game/1","journal":journal,"closing_away":away}
    if upkeep is not None:
        slot.update(schema="annual-game/2", game_upkeep=upkeep)
    if public_farm:
        slot.update(schema="annual-game/3", public_farm=True)
    if reserve_policy is not None:
        if not public_farm or reserve_policy not in RESERVE_POLICIES:
            raise ValueError("invalid saved reserve policy")
        slot.update(schema="annual-game/4", reserve_policy=reserve_policy)
    if research is not None:
        slot.update(schema="annual-game/5", research=research)
    if diffusion is not None:
        if research is None:
            raise ValueError("farm knowledge exchange requires research")
        slot.update(schema="annual-game/6", diffusion=diffusion)
    save_json_slot(path,slot)


def load(path, *, observer=None, observers=()):
    observers = tuple(observers)
    if observer is not None:
        observers = (observer, *observers)

    def replay_step(game,command):
        row = play(game,command)
        for active in observers:
            active.observe(row)
        return row

    slot = json.loads(path.read_bytes())
    if isinstance(slot,dict) and slot.get("schema")=="game-journal/1":
        # Early replay-only slots published with this branch.
        return slot, restore_journal(slot,create,replay_step)
    fields = {"schema","journal","closing_away"}
    schemas = {"annual-game/1":fields, "annual-game/2":fields | {"game_upkeep"}}
    if not isinstance(slot, dict):
        raise ValueError("invalid annual game save")
    diffusion_slot = slot.get("schema") == "annual-game/6"
    research_slot = slot.get("schema") == "annual-game/5" or diffusion_slot
    harvest_slot = slot.get("schema") in ("annual-game/3","annual-game/4") or (research_slot and "public_farm" in slot)
    if harvest_slot:
        schemas["annual-game/3"] = fields | {"public_farm"} | ({"game_upkeep"} if "game_upkeep" in slot else set())
        schemas["annual-game/4"] = schemas["annual-game/3"] | {"reserve_policy"}
    if research_slot:
        optional = {"public_farm", "game_upkeep"}
        if harvest_slot:
            optional.add("reserve_policy")
        schemas["annual-game/5"] = fields | {"research"} | (optional & slot.keys())
        schemas["annual-game/6"] = schemas["annual-game/5"] | {"diffusion"}
    if slot.keys() != schemas.get(slot.get("schema")) or (harvest_slot and slot["public_farm"] is not True):
        raise ValueError("invalid annual game save")
    game = restore_journal(slot["journal"],create,replay_step)
    if (diffusion_slot != (game.economy.diffusion is not None)
            or canonical_line(slot.get("diffusion")) != canonical_line(game.economy.diffusion)):
        raise ValueError("saved farm knowledge exchange differs from replay")
    if (research_slot != (game.economy.research is not None)
            or canonical_line(slot.get("research")) != canonical_line(game.economy.research)):
        raise ValueError("saved research differs from replay")
    if harvest_slot != game.economy.public_farm:
        raise ValueError("saved public harvest rule disagrees with replay")
    if slot.get("reserve_policy") != game.economy.reserve_policy or ("reserve_policy" in slot and game.economy.reserve_policy is None):
        raise ValueError("saved reserve policy disagrees with replay")
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
    advance.add_argument("--reserve-policy",choices=RESERVE_POLICIES,help="select a lower harvest target or conditional emergency relief")
    advance.add_argument("--research", action="store_true", help="enable autonomous local agricultural field trials")
    advance.add_argument("--diffusion", action="store_true",
                         help="enable farm knowledge exchange via domestic migration in a research-enabled game")
    advance.add_argument("--block-migration", nargs=2, type=int, metavar=("LOW_ID", "HIGH_ID"),
                         help="diagnostic: block household migration across one domestic edge for this turn")
    advance.add_argument("--relief-benefits",action="store_true",help="include this year's audited household receipts from ordinary and emergency relief")
    show = commands.add_parser("show",help="replay and check a save")
    show.add_argument("save",type=Path)
    show.add_argument("--custody",action="store_true",help="include audited meal, office and population receipts")
    show.add_argument("--relief-benefits",action="store_true",help="include direct political relief benefits by region for every saved year")
    args = parser.parse_args(argv)
    try:
        if args.action == "new":
            journal = new_journal(args.seed)
            save(args.out,journal,[])
            result = {"seed":args.seed,"year":0,"closing_away":[]}
        else:
            observers = []
            custody = benefits = None
            if args.action == "show" and args.custody:
                from .regional_custody import CustodyObserver
                custody = CustodyObserver()
                observers.append(custody)
            if args.action == "show" and args.relief_benefits:
                from .relief_benefits import ReliefBenefitsObserver
                benefits = ReliefBenefitsObserver()
                observers.append(benefits)
            journal, game = load(args.save,observers=observers)
            if args.action == "show":
                result = {"seed":journal["seed"],"year":game.economy.world.year,"closing_away":game.away}
                if game.economy.game_upkeep is not None:
                    result["game_upkeep"] = game.economy.game_upkeep
                if game.economy.public_farm:
                    result["public_farm"] = True
                if game.economy.reserve_policy is not None:
                    result["reserve_policy"] = game.economy.reserve_policy
                if game.economy.research is not None:
                    result["research"] = game.economy.research
                if game.economy.diffusion is not None:
                    result["diffusion"] = game.economy.diffusion
                if custody is not None:
                    result["custody"] = custody.latest
                if benefits is not None:
                    result["relief_benefits"] = benefits.report()
            else:
                command = asdict(Move(*args.move)) if args.move is not None else None
                if args.upkeep is not None:
                    from .unit_upkeep import Upkeep
                    command = {"move":command, "upkeep":asdict(Upkeep(*args.upkeep))}
                if args.relief_first:
                    if args.upkeep is None:
                        raise ValueError("--relief-first requires --upkeep HOME COUNT at activation")
                    command["relief_first"] = True
                if args.public_farm or args.reserve_policy or args.research or args.diffusion or args.block_migration:
                    if args.upkeep is None:
                        command = {"move":command}
                    if args.public_farm or args.reserve_policy:
                        command["public_farm"] = True
                    if args.reserve_policy:
                        command["reserve_policy"] = args.reserve_policy
                    if args.research:
                        command["research"] = True
                    if args.diffusion:
                        command["diffusion"] = True
                    if args.block_migration:
                        command["blocked_migration"] = args.block_migration
                row = play(game,command)
                if args.relief_benefits:
                    from .relief_benefits import VERSION, relief_benefits
                    benefit_report = {"version":VERSION, "years":[relief_benefits(row)]}
                save(args.out,append_turn(journal,command,row),game.away,game.economy.game_upkeep,
                     public_farm=game.economy.public_farm, reserve_policy=game.economy.reserve_policy,
                     research=game.economy.research, diffusion=game.economy.diffusion)
                result = {"year":row["year"],**row["unit_game"]}
                if args.relief_benefits:
                    result["relief_benefits"] = benefit_report
                if "unit_upkeep" in row:
                    result["unit_upkeep"] = row["unit_upkeep"]
                if "public_harvest" in row:
                    result["public_harvest"] = row["public_harvest"]
                if "emergency_relief" in row:
                    result["emergency_relief"] = row["emergency_relief"]
                if "research" in row:
                    result["research"] = row["research"]
                if "diffusion" in row:
                    result["diffusion"] = row["diffusion"]
        print(json.dumps(result,sort_keys=True))
    except (ValueError,OSError,TypeError) as exc:
        parser.exit(2,f"{parser.prog}: {exc}\n")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
