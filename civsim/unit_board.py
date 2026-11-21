"""Two-square board for player-selected token moves. No simulation dependencies."""
from threading import Lock


def _natural(value):
    return type(value) is int and value >= 0


def _require(valid, reason):
    if not valid:
        raise ValueError("unit board: " + reason)


def assess_crossing(*, count, tokens, food, remaining) -> tuple[str, int, int]:
    """Quote one board move as (reason, food spent, edge units spent).

    The three balances are nonnegative integer counters. A rejected request
    spends zero. A successful request costs one of each resource per token.
    """
    _require(all(_natural(q) for q in (tokens, food, remaining)), "invalid crossing balance")
    if not _natural(count) or not count:
        return "invalid_count", 0, 0
    if count > tokens:
        return "insufficient_tokens", 0, 0
    if count > food:
        return "insufficient_food", 0, 0
    if count > remaining:
        return "insufficient_capacity", 0, 0
    return "moved", count, count


def _read_rows(rows, fields):
    """Persist integer keys as JSON rows, rejecting duplicate and non-integer values."""
    _require(type(rows) is list, "expected rows")
    for row in rows:
        _require(type(row) is dict and row.keys() == set(fields)
                 and all(_natural(row[field]) for field in fields), "invalid numeric row")
    return rows


def _encode_groups(balances, keys):
    return [{**dict(zip(keys, ids, strict=True)), "count":count}
            for ids,count in sorted(balances.items())]


def _decode_groups(rows, keys):
    result = {}
    for row in _read_rows(rows, (*keys, "count")):
        key = tuple(row[k] for k in keys)
        _require(key not in result and row["count"] > 0, "duplicate or empty allocation")
        result[key] = row["count"]
    return result


_GROUP = ("home", "affiliation")
_POSITION = (*_GROUP, "location")
_MOVE = ("turn", "home", "affiliation", "source", "destination", "count")
_NODE = ("id", "population", "initial_food", "food", "food_spent")
_SCHEMA = "unit-board/1"


class UnitBoard:
    """Each token crossing costs one food at departure and one shared edge unit.

    Population and affiliation are immutable labels/counts. Current location
    changes only on an accepted move. Food is never replenished by this game.
    """

    @classmethod
    def create(cls, *, population, roster, food, edge, capacity, remaining=None, turn=1):
        return cls(population, roster, food, edge, capacity, remaining, turn)

    def __init__(self, population, roster, food, edge, capacity, remaining, turn):
        _require(isinstance(edge,(tuple,list)) and len(edge) == 2
                 and all(_natural(i) for i in edge) and edge[0] != edge[1], "expected two distinct squares")
        self._edge = tuple(sorted(edge))
        for table in (population, food):
            _require(isinstance(table,dict) and all(_natural(i) and _natural(q) for i,q in table.items())
                     and set(table) == set(edge), "one nonnegative amount required for each square")
        _require(isinstance(roster,dict), "invalid roster")
        self._roster = {}
        home_total = dict.fromkeys(edge,0)
        for key,count in roster.items():
            _require(type(key) is tuple and len(key) == 2 and all(_natural(i) for i in key)
                     and key[0] in home_total and _natural(count), "invalid roster group")
            if count:
                self._roster[key] = count
                home_total[key[0]] += count
        _require(all(q <= population[i] for i,q in home_total.items()), "roster exceeds residents at home")
        _require(_natural(capacity) and _natural(turn) and turn > 0, "invalid capacity or turn")
        remaining = capacity if remaining is None else remaining
        _require(_natural(remaining) and remaining <= capacity, "invalid remaining edge balance")
        self._population = population.copy()
        self._initial_food = food.copy()
        self._food = food.copy()
        self._positions = {(h,a,h):q for (h,a),q in self._roster.items()}
        self._capacity = capacity
        self._turn = self._initial_turn = turn
        self._remaining = self._initial_remaining = remaining
        self._moves = []
        self._lock = Lock()

    @property
    def edge(self):
        return self._edge

    @property
    def capacity(self):
        return self._capacity

    @property
    def turn(self):
        return self._turn

    @property
    def remaining(self):
        return self._remaining

    @property
    def population(self):
        return self._population.copy()

    @property
    def roster(self):
        return self._roster.copy()

    @property
    def food(self):
        with self._lock:
            return self._food.copy()

    @property
    def positions(self):
        with self._lock:
            return self._positions.copy()

    def _move_terms(self, home, affiliation, source, destination, count):
        if not _natural(count) or not count:
            return "invalid_count", 0, 0
        if not all(_natural(i) for i in (home,affiliation,source,destination)):
            return "invalid_key", 0, 0
        if (home,affiliation) not in self._roster:
            return "unknown_group", 0, 0
        if source == destination or source not in self._edge or destination not in self._edge:
            return "invalid_edge", 0, 0
        return assess_crossing(count=count, tokens=self._positions.get((home,affiliation,source),0),
                               food=self._food[source], remaining=self._remaining)

    def move(self, home, affiliation, source, destination, count):
        with self._lock:
            reason, food_spent, road_used = self._move_terms(home, affiliation, source, destination, count)
            values = (self._turn, home, affiliation, source, destination, count)
            # Bad noninteger inputs have a safe and JSON-serializable representation.
            move = {k:v if type(v) is int else None for k,v in zip(_MOVE, values, strict=True)}
            if reason == "moved":
                old_key = (home,affiliation,source)
                new_key = (home,affiliation,destination)
                self._positions[old_key] -= count
                if not self._positions[old_key]:
                    del self._positions[old_key]
                self._positions[new_key] = self._positions.get(new_key,0) + count
                self._food[source] -= food_spent
                self._remaining -= road_used
                self._moves.append(move)
            return {**move, "ok":reason == "moved", "reason":reason, "food_spent":food_spent, "road_used":road_used}

    def next_turn(self):
        with self._lock:
            self._turn += 1
            self._remaining = self._capacity
        return self

    def snapshot(self):
        with self._lock:
            nodes = [{"id":i, "population":self._population[i], "initial_food":self._initial_food[i],
                      "food":self._food[i], "food_spent":self._initial_food[i]-self._food[i]} for i in self._edge]
            return {"schema":_SCHEMA, "edge":list(self._edge), "capacity":self._capacity,
                    "initial_remaining":self._initial_remaining, "initial_turn":self._initial_turn,
                    "turn":self._turn, "remaining":self._remaining, "nodes":nodes,
                    "roster":_encode_groups(self._roster,_GROUP), "positions":_encode_groups(self._positions,_POSITION),
                    "moves":[m.copy() for m in self._moves]}

    @classmethod
    def restore(cls, snapshot):
        """Replay every paid crossing and check the supplied balances independently.

        The saved initial square budgets are authoritative, just as at creation.
        Detecting a complete substitution of a different valid game requires a
        trusted external copy of its initial setup or fingerprint.
        """
        keys = {"schema","edge","capacity","initial_remaining","initial_turn","turn","remaining",
                "nodes","roster","positions","moves"}
        _require(type(snapshot) is dict and snapshot.keys() == keys and snapshot["schema"] == _SCHEMA,
                 "unknown snapshot format")
        for k in ("capacity","initial_remaining","initial_turn","turn","remaining"):
            _require(_natural(snapshot[k]), "invalid saved integer")
        _require(type(snapshot["edge"]) is list and snapshot["turn"] >= snapshot["initial_turn"], "invalid turn or edge")
        nodes = _read_rows(snapshot["nodes"],_NODE)
        _require(len(nodes) == 2 and nodes[0]["id"] != nodes[1]["id"], "two distinct squares required")
        population = {r["id"]:r["population"] for r in nodes}
        initial_food = {r["id"]:r["initial_food"] for r in nodes}
        roster = _decode_groups(snapshot["roster"], _GROUP)
        positions = _decode_groups(snapshot["positions"], _POSITION)
        game = cls.create(population=population, roster=roster, food=initial_food, edge=snapshot["edge"],
                          capacity=snapshot["capacity"], remaining=snapshot["initial_remaining"],
                          turn=snapshot["initial_turn"])

        allocated = dict.fromkeys(roster,0)
        for (home,affiliation,location),q in positions.items():
            _require((home,affiliation) in roster and location in population, "unknown token group or square")
            allocated[home,affiliation] += q
        _require(allocated == roster, "token allocations differ from roster")
        spending = dict.fromkeys(population,0)
        for m in _read_rows(snapshot["moves"],_MOVE):
            _require(game._turn <= m["turn"] <= snapshot["turn"], "out-of-order or future move")
            if game._turn < m["turn"]:
                # Waiting has no food or location cost; skip arbitrarily many empty turns.
                game._turn = m["turn"]
                game._remaining = game._capacity
            receipt = game.move(m["home"],m["affiliation"],m["source"],m["destination"],m["count"])
            _require(receipt["ok"], "impossible recorded move: " + receipt["reason"])
            spending[m["source"]] += m["count"]
        if game._turn < snapshot["turn"]:
            game._turn = snapshot["turn"]
            game._remaining = game._capacity
        _require(all(spending[r["id"]] == r["food_spent"] == r["initial_food"]-r["food"] for r in nodes),
                 "food payments differ from crossings")
        _require(game.snapshot() == snapshot, "saved allocation, turn balance or ordering differs from replay")
        return game
