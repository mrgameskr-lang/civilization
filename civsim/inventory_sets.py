"""Atomic purchases of complete sets from a game inventory."""

from threading import Lock


_purchase_lock = Lock()


def take_sets(stock: dict, requested: int) -> int:
    """Spend one food and one tool per set and return the number purchased."""
    if type(requested) is not int or not 0 <= requested <= 2:
        raise ValueError('requested must be an integer from 0 to 2')
    if not isinstance(stock, dict):
        raise ValueError('stock must be a dictionary')

    with _purchase_lock:
        food, tools = dict.get(stock, 'food'), dict.get(stock, 'tools')
        if type(food) is not int or food < 0 or type(tools) is not int or tools < 0:
            raise ValueError('food and tools must both have nonnegative integer balances')
        purchased = min(requested, food, tools)
        if purchased:
            dict.update(stock, food=food - purchased, tools=tools - purchased)
        return purchased
