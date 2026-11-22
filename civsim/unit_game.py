"""Play the standalone two-region game and save each accepted action to a new slot."""
import argparse
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from experiments.publication import publish_file

from .storage import canonical_line
from .unit_board import UnitBoard
from .unit_board_scenario import demo_board


def load_board(path):
    return UnitBoard.restore(json.loads(Path(path).read_bytes()))


def save_board(path, board):
    path = Path(path)
    if os.path.lexists(path):
        raise FileExistsError(f"save already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=path.parent) as tmp:
        staged = Path(tmp) / "turn.json"
        staged.write_bytes(canonical_line(board.snapshot()))
        publish_file(staged, path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="start a board with its own resident and unit roster")
    new.add_argument("--seed", default=0, type=int)
    new.add_argument("--out", required=True, type=Path)
    move = commands.add_parser("move", help="move tokens from one endpoint to the other")
    move.add_argument("save", type=Path)
    move.add_argument("--out", required=True, type=Path)
    move.add_argument("--home", type=int, required=True)
    move.add_argument("--affiliation", type=int, required=True)
    move.add_argument("--from", dest="source", type=int, required=True)
    move.add_argument("--to", dest="destination", type=int, required=True)
    move.add_argument("--count", type=int, required=True)
    advance = commands.add_parser("next", help="open the next turn at the saved positions")
    advance.add_argument("save", type=Path)
    advance.add_argument("--out", required=True, type=Path)
    commands.add_parser("show", help="read and validate a saved board").add_argument("save", type=Path)
    args = parser.parse_args(argv)
    try:
        board = demo_board(args.seed) if args.command == "new" else load_board(args.save)
        if args.command == "show":
            print(json.dumps(board.snapshot(), ensure_ascii=True, sort_keys=True))
            return 0
        if args.command == "move":
            result = board.move(args.home, args.affiliation, args.source, args.destination, args.count)
            if not result["ok"]:
                print(json.dumps(result))
                return 1
        else:
            if args.command == "next":
                board.next_turn()
            result = {"turn": board.turn, "save": str(args.out)}
        save_board(args.out, board)
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"{parser.prog}: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
