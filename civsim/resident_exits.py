"""Independent integer reconciliation of a resident census and its home register."""


def _counts(row, *keys):
    if type(row) is not dict or any(type(row.get(key)) is not int or row[key] < 0 for key in keys):
        raise ValueError(f"expected nonnegative integer census fields: {', '.join(keys)}")
    return tuple(row[key] for key in keys)


def _homes(rows):
    result = {}
    for row in rows:
        home, _ = _counts(row, "id", "owner")
        if home in result:
            raise ValueError(f"duplicate home {home}")
        result[home] = row
    return result


def _population(snapshot, home, owner):
    population, = _counts(snapshot, "population")
    for key, expected in (("id", home), ("owner", owner)):
        if key in snapshot and _counts(snapshot, key)[0] != expected:
            raise ValueError(f"{key} changed for home {home}")
    return population


def audit_resident_exits(population_rows, roster_rows):
    """Return auditable receipts in home-ID order for completed regional rows.

    Registered residents are a subset of the census. Their deaths and exits
    are counted within each home's population totals. Actual resident deaths
    and departures determine the two successive proportional allocations.
    """
    census = _homes(population_rows)
    register = _homes(roster_rows)
    if census.keys() != register.keys():
        raise ValueError("resident and register rows cover different homes")
    result = []
    for home in sorted(census):
        region, row = census[home], register[home]
        owner = region["owner"]
        opening = _population(region.get("opening"), home, owner)
        closing = _population(region.get("closing"), home, owner)
        before, births, deaths, survivors, departures, arrivals, after = _counts(
            region.get("demography"), "opening_population", "births", "deaths", "population_before_migration",
            "emigrants", "immigrants", "closing_population")
        if (opening != before or deaths > opening or survivors != opening + births - deaths
                or departures > survivors or survivors - departures + arrivals != after or after != closing):
            raise ValueError(f"births, deaths and migration do not explain census change at home {home}")

        pop, roll_open, released, enrolled, serving, lost, left, roll_close = _counts(
            row, "population", "opening_roster", "released", "enrolled", "serving",
            "service_deaths", "service_emigrants", "closing_roster")
        if (row["owner"] != owner or pop != opening or roll_open > opening or released > roll_open
                or serving != roll_open - released + enrolled or serving > opening):
            raise ValueError(f"invalid opening register, releases or enrollments at home {home}")
        expected_lost = serving * deaths // opening if opening else 0
        after_deaths = serving - expected_lost
        expected_left = after_deaths * departures // survivors if survivors else 0
        if (lost != expected_lost or left != expected_left or roll_close != after_deaths - expected_left
                or roll_close > closing):
            raise ValueError(f"deaths and emigration do not explain the closing register at home {home}")
        result.append({"home": home, "owner": owner, "population_open": opening, "births": births,
                       "deaths": deaths, "emigrants": departures, "immigrants": arrivals,
                       "population_close": closing, "roster_open": roll_open, "released": released,
                       "enrolled": enrolled, "serving": serving, "roster_deaths": lost,
                       "roster_emigrants": left, "roster_close": roll_close})
    return result
