"""A two-village festival puzzle with an independent resident roll and food counters."""

from .unit_board import UnitBoard


def demo_board(seed: int = 0) -> UnitBoard:
    """Open a fresh game. Seeds 0 through 39 cover all 8 × 5 initial food layouts."""
    if type(seed) is not int or seed < 0:
        raise ValueError('seed must be a nonnegative integer')
    return UnitBoard.create(
        population={0: 12, 1: 10},
        roster={(0, 0): 1, (0, 1): 2, (1, 0): 1, (1, 1): 1},
        food={0: 2 + seed % 8, 1: 2 + (seed // 8) % 5},
        edge=(0, 1),
        capacity=2,
    )


def production_pool(board: UnitBoard) -> dict[int, int]:
    """Residents available for other work = home population minus home volunteers.

    Moving a volunteer changes their square. Their home and festival role stay fixed.
    """
    workers = board.population.copy()
    for (home, _affiliation), volunteers in board.roster.items():
        workers[home] -= volunteers
    return workers
