"""Orchestrate one annual transition. All model inputs and outputs are serializable."""

from dataclasses import asdict, replace

from . import demography, economy, investment
from .audit import audit, observed_events
from .model import World, climate_factor
from .rules import LEGACY, Rules


def step(world: World, year: int, rules: Rules = LEGACY) -> dict:
    """Advance one year, publishing fresh country objects only after balances pass."""
    if type(year) is not int or year != world.year + 1:
        raise ValueError(f"expected next year {world.year + 1}, got {year!r}")
    version_three = rules.investment != "off"
    if world.year and any(isinstance(n, investment.InvestingNation) != version_three for n in world.nations):
        raise ValueError("switching between capital and pre-capital worlds requires a new run")
    if version_three:
        working = [investment.prepare(n) for n in world.nations]
    else:
        working = [replace(n, stock=n.stock.copy()) for n in world.nations]
    opening = {n.id: asdict(n) for n in working}
    climate = {n.id: climate_factor(world.seed, year, n.id) for n in working}
    production = {n.id: economy.produce(n, climate[n.id], rules) for n in working}
    market = economy.market(working, rules)
    for key in ("opening", "prices", "targets"):
        market[key] = {str(i): values for i, values in market[key].items()}
    consumption = {n.id: economy.consume(n) for n in working}
    people = demography.develop(working, consumption)
    countries = [
        {"id": n.id, "opening": opening[n.id], "climate": climate[n.id],
         "production": production[n.id], "consumption": consumption[n.id],
         "demography": people["countries"][n.id], "closing": asdict(n)}
        for n in working
    ]
    moves = people["moves"]
    record = {"year": year, "countries": countries, "market": market, "moves": moves,
              "events": observed_events(countries, moves)}
    audit(record)
    world.nations = working
    world.year = year
    return record

