"""Evidence carried by an event candidate in a JSON-normalized annual ledger."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Candidate:
    kind: str
    country: int
    region: int | None
    importance: int
    description: str
    evidence: dict[str, str]
    counterparty: int | None = None


def resolve(row, pointer):
    """Resolve a non-root JSON Pointer, without Python's negative array indexing."""
    if not pointer.startswith("/"):
        raise ValueError(f"expected an absolute evidence pointer: {pointer!r}")
    value = row
    for part in pointer[1:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not key.isascii() or not key.isdecimal() or key != str(int(key)):
                raise ValueError(f"invalid evidence array index: {pointer}")
            index = int(key)
            if index >= len(value):
                raise ValueError(f"missing evidence array index: {pointer}")
            value = value[index]
        elif isinstance(value, dict) and key in value:
            value = value[key]
        else:
            raise ValueError(f"missing evidence field: {pointer}")
    return value
