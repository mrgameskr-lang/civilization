"""Portable command journals for deterministic games with JSON results."""
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from experiments.publication import publish_file


SCHEMA = "game-journal/1"


def _canonical_line(value):
    """Use the repository's canonical UTF-8 format without importing an engine."""
    try:
        text = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
        result = (text + "\n").encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("expected a finite, UTF-8 encodable JSON value") from exc
    # Python's encoder accepts tuples and silently stringifies numeric object
    # keys. Commands must preserve their types across a save/load boundary.
    pending = [value]
    while pending:
        part = pending.pop()
        if type(part) is list:
            pending.extend(part)
        elif type(part) is dict:
            if not all(type(key) is str for key in part):
                raise ValueError("JSON object keys must be strings")
            pending.extend(part.values())
        elif part is not None and type(part) not in (bool, int, float, str):
            raise ValueError("expected only JSON objects, arrays and scalar values")
    return result


def _check_command(command):
    if command is not None and type(command) is not dict:
        raise ValueError("expected a command object or null")
    _canonical_line(command)


def _check_journal(journal):
    if (type(journal) is not dict or journal.keys() != {"schema", "seed", "turns"}
            or journal["schema"] != SCHEMA or type(journal["seed"]) is not int
            or type(journal["turns"]) is not list):
        raise ValueError("invalid game journal header")
    for year, row in enumerate(journal["turns"], 1):
        if (type(row) is not dict or row.keys() != {"year", "command", "record_sha256"}
                or type(row["year"]) is not int or row["year"] != year):
            raise ValueError(f"invalid game journal at turn {year}")
        digest = row["record_sha256"]
        if type(digest) is not str or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError(f"invalid record hash at turn {year}")
        _check_command(row["command"])


def new_journal(seed):
    if type(seed) is not int:
        raise ValueError("expected an integer game seed")
    return {"schema": SCHEMA, "seed": seed, "turns": []}


def append_turn(journal, command_dict_or_none, annual_record):
    """Return an independent journal with the command and digest of its result."""
    _check_journal(journal)
    _check_command(command_dict_or_none)
    digest = sha256(_canonical_line(annual_record)).hexdigest()
    result = deepcopy(journal)
    result["turns"].append({"year": len(result["turns"]) + 1, "command": deepcopy(command_dict_or_none),
                            "record_sha256": digest})
    return result


def restore_journal(journal, create, step):
    """Recreate a game and check each annual result before proceeding to the next."""
    _check_journal(journal)
    turns = deepcopy(journal["turns"])
    game = create(journal["seed"])
    for row in turns:
        actual = step(game, row["command"])
        if sha256(_canonical_line(actual)).hexdigest() != row["record_sha256"]:
            raise ValueError(f"game replay differs at turn {row['year']}")
    return game


def save_journal(path, journal):
    """Write complete canonical JSON to a new path, refusing to replace any prior save."""
    _check_journal(journal)
    save_json_slot(path, journal)


def save_json_slot(path, value):
    """Publish a complete game save to a fresh slot."""
    data = _canonical_line(value)
    path = Path(path)
    if os.path.lexists(path):
        raise FileExistsError(f"journal already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=path.parent) as scratch:
        staged = Path(scratch) / "journal.json"
        staged.write_bytes(data)
        publish_file(staged, path)
