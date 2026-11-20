"""World initialization and annual rainfall. Quantities are integers."""

from dataclasses import dataclass
from random import Random


GOODS = ("food", "ore", "tools")
NAMES = ("아르덴", "벨로라", "세린", "다르온", "에스카", "미레아", "로벤", "타비르")


@dataclass(frozen=True, slots=True)
class Tile:
    owner: int
    x: int
    y: int
    fertility: int
    ore_grade: int
    deposit: int  # Initial geological endowment. Remaining ore is pooled nationally.


@dataclass(slots=True)
class Nation:
    id: int
    name: str
    population: int
    stock: dict[str, int]
    cash: int
    productivity: int
    technology: int
    land: int
    fertility: int
    ore_grade: int
    deposit: int
    soil: int


@dataclass(slots=True)
class World:
    seed: int
    width: int
    height: int
    tiles: list[Tile]
    nations: list[Nation]


def _regions(x, y, width, height, count, rng):
    """Partition a rectangle into exactly count nonempty connected rectangles."""
    if count == 1:
        yield x, y, width, height
        return

    split_x = width > height or (width == height and rng.randrange(2) == 0)
    length = width if split_x else height
    cut = max(1, min(length - 1, length * rng.randint(43, 57) // 100))
    first_area = cut * (height if split_x else width)
    area = width * height
    # Reserve a tile for every nation on each side even on narrow, crowded maps.
    proportional = (count * first_area + area // 2) // area
    minimum = max(1, count - (area - first_area))
    maximum = min(count - 1, first_area)
    first_count = max(minimum, min(maximum, proportional))
    if split_x:
        yield from _regions(x, y, cut, height, first_count, rng)
        yield from _regions(x + cut, y, width - cut, height, count - first_count, rng)
    else:
        yield from _regions(x, y, width, cut, first_count, rng)
        yield from _regions(x, y + cut, width, height - cut, count - first_count, rng)


def generate_world(seed: int, width: int = 48, height: int = 32, nations: int = 8) -> World:
    """Generate an independent year-zero world. Every random draw uses a private RNG."""
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    if any(type(v) is not int or v < 1 for v in (width, height, nations)):
        raise ValueError("map dimensions and nation count must be positive integers")
    if nations > width * height:
        raise ValueError("each nation needs at least one tile")

    rng = Random(seed)
    boundaries = list(_regions(0, 0, width, height, nations, rng))
    tiles = []
    countries = []
    for owner, (x0, y0, w, h) in enumerate(boundaries):
        regional_fertility = rng.randint(650, 1400)
        regional_grade = rng.randint(600, 1400)
        region = []
        for y in range(y0, y0 + h):
            for x in range(x0, x0 + w):
                fertility = regional_fertility + rng.randint(-140, 140)
                grade = regional_grade + rng.randint(-250, 250)
                deposit = grade * rng.randint(65, 145) // 100
                region.append(Tile(owner, x, y, fertility, grade, deposit))

        land = len(region)
        population = land * rng.randint(42, 57)
        stock = {
            "food": population * rng.randint(220, 550) // 1000,
            "ore": population * rng.randint(15, 45) // 1000,
            "tools": population * rng.randint(10, 40) // 1000,
        }
        countries.append(Nation(
            id=owner,
            name=NAMES[owner] if owner < len(NAMES) else f"나라-{owner+1}",
            population=population,
            stock=stock,
            cash=population * rng.randint(3000, 6000) // 1000,
            productivity=rng.randint(850, 1200),
            technology=rng.randint(850, 1200),
            land=land,
            fertility=sum(t.fertility for t in region) // land,
            ore_grade=sum(t.ore_grade for t in region) // land,
            deposit=sum(t.deposit for t in region),
            soil=rng.randint(850, 1100),
        ))
        tiles.extend(region)

    tiles.sort(key=lambda t: t.y * width + t.x)
    return World(seed, width, height, tiles, countries)


def _triangle(phase: int, half_period: int, amplitude: int) -> int:
    """Integer triangle wave in [-amplitude, amplitude]."""
    distance = abs(phase % (2 * half_period) - half_period)
    return amplitude - (2 * amplitude * distance // half_period)


def climate_factor(seed: int, year: int, nation_id: int) -> int:
    """Annual rainfall multiplier in permille from one global and one local cycle."""
    global_cycle = _triangle(year + seed, 8, 100)
    local_cycle = _triangle(year + seed * 3 + nation_id * 5, 13, 100)
    return 1000 + global_cycle + local_cycle
