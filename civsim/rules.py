"""Versioned choices for agricultural labor and international settlement."""

from dataclasses import dataclass

from .model import GOODS


@dataclass(frozen=True, slots=True)
class Rules:
    labor: str = "idle"
    order: tuple[str, ...] = GOODS

    def __post_init__(self) -> None:
        if self.labor not in ("idle", "reallocate"):
            raise ValueError("labor must be 'idle' or 'reallocate'")
        if (type(self.order) is not tuple or len(self.order) != len(GOODS)
                or any(good not in self.order for good in GOODS)):
            raise ValueError("order must be a tuple containing food, ore and tools exactly once")

    @property
    def version(self) -> str:
        return "1.0" if self == LEGACY else "2.0"


LEGACY = Rules()
