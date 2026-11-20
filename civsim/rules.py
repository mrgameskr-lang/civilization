"""Versioned choices for agricultural labor and international settlement."""

from dataclasses import dataclass

from .model import GOODS


POLICIES31 = tuple(f"{geometry}-{selection}"
                   for geometry in ("fixed", "diminishing", "scaled", "combined")
                   for selection in ("single", "multi") if (geometry, selection) != ("fixed", "single"))


@dataclass(frozen=True, slots=True)
class Rules:
    labor: str = "idle"
    order: tuple[str, ...] = GOODS
    investment: str = "off"
    policy31: str = "off"

    def __post_init__(self) -> None:
        if self.policy31 != "off" and (self.policy31 not in POLICIES31 or self.investment != "capital"):
            raise ValueError("a 3.1 policy requires a supported geometry/selection and capital investment")
        if self.investment not in ("off", "inventory", "capital"):
            raise ValueError("investment must be 'off', 'inventory' or 'capital'")
        if self.labor not in ("idle", "reallocate"):
            raise ValueError("labor must be 'idle' or 'reallocate'")
        if (type(self.order) is not tuple or len(self.order) != len(GOODS)
                or any(good not in self.order for good in GOODS)):
            raise ValueError("order must be a tuple containing food, ore and tools exactly once")

    @property
    def version(self) -> str:
        if self.policy31 != "off":
            return "3.1"
        if self.investment != "off":
            return "3.0"
        return "1.0" if self == LEGACY else "2.0"


LEGACY = Rules()
