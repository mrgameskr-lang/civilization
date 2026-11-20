"""Annual birth, death and migration accounting in individual people."""

from .model import Nation


BIRTHS_PER_THOUSAND_FED = 28
BASE_DEATHS_PER_THOUSAND = 12
EXTRA_DEATHS_PER_THOUSAND_UNFED = 110
SETTLEMENT_PLACES_PER_TILE = 65
PEOPLE_UNDER_PRESSURE_PER_MIGRANT = 12


def _local_balance(nation: Nation, meal: dict) -> dict[str, int]:
    population = nation.population
    need = meal["food_need"]
    eaten = meal["food_eaten"]
    reserve = nation.stock["food"]
    quantities = (population, need, eaten, reserve, nation.land)
    if any(type(value) is not int or value < 0 for value in quantities):
        raise ValueError("demography requires nonnegative integer quantities")
    if need != population or eaten > need:
        raise ValueError("annual food need must equal opening population and cover food eaten")

    shortage = need - eaten
    births = eaten * BIRTHS_PER_THOUSAND_FED // 1000
    deaths = (population * BASE_DEATHS_PER_THOUSAND
              + shortage * EXTRA_DEATHS_PER_THOUSAND_UNFED) // 1000
    residents = population + births - deaths
    places = nation.land * SETTLEMENT_PLACES_PER_TILE
    crowding = max(0, residents - places)
    pressure = max(shortage, crowding)
    departures = min(residents, pressure // PEOPLE_UNDER_PRESSURE_PER_MIGRANT)
    vacancies = 0 if shortage else min(reserve, max(0, places - residents))
    return {
        "opening_population": population, "food_need": need, "food_eaten": eaten,
        "food_shortage": shortage, "land": nation.land, "food_reserve": reserve,
        "births": births, "deaths": deaths, "population_before_migration": residents,
        "settlement_places": places, "crowding": crowding, "pressure": pressure,
        "pressure_permille": pressure * 1000 // max(1, population),
        "requested_departures": departures, "host_capacity": vacancies,
        "emigrants": 0, "immigrants": 0,
    }


def develop(nations: list[Nation], consumption: dict[int, dict]) -> dict:
    """Plan moves from a single post-vital snapshot and then commit populations."""
    ids = {nation.id for nation in nations}
    if len(ids) != len(nations) or ids != consumption.keys():
        raise ValueError("each nation must have a unique ID and exactly one consumption record")
    rows = {nation.id: _local_balance(nation, consumption[nation.id]) for nation in nations}
    donors = sorted((i for i in ids if rows[i]["requested_departures"]),
                    key=lambda i: (-rows[i]["pressure_permille"], i))
    hosts = sorted((i for i in ids if rows[i]["host_capacity"]),
                   key=lambda i: (-rows[i]["host_capacity"], i))
    moves = []
    host_index = 0
    for source in donors:
        donor = rows[source]
        remaining = donor["requested_departures"]
        while remaining and host_index < len(hosts):
            target = hosts[host_index]
            host = rows[target]
            available = host["host_capacity"] - host["immigrants"]
            people = min(remaining, available)
            moves.append({"source": source, "target": target, "people": people})
            donor["emigrants"] += people
            host["immigrants"] += people
            remaining -= people
            if people == available:
                host_index += 1

    for nation in nations:
        row = rows[nation.id]
        nation.population = row["population_before_migration"] + row["immigrants"] - row["emigrants"]
        row["closing_population"] = nation.population
    return {"countries": rows, "moves": moves}
