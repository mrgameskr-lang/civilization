"""Explain the food component of a settled civic levy receipt."""

COLUMNS = ('private_food', 'protected_floor', 'opening_public_food', 'cap', 'baseline_assessed',
           'conceded', 'refused', 'gross', 'handling', 'net', 'reason')


def _food(receipt, field):
    try:
        value = receipt[field]['food']
    except (KeyError, TypeError) as exc:
        raise ValueError(f'Missing food amount in {field}') from exc
    if type(value) is not int or value < 0:
        raise ValueError(f'Invalid food amount in {field}')
    return value


def food_assessment(receipt):
    """Return quantities in COLUMNS order, followed by an exclusive receipt-level reason.

    Positive net food takes precedence. With no assessment, the private food floor
    precedes a full depot when both bind. Surplus and space with zero assessment
    leave integer rounding and other nonassessment causes indistinguishable. When
    assessment was positive, distinguish zero payment from a positive payment that
    was all spent on handling. Concessions and refusals remain separate quantities.
    The depot balances refer to the moments immediately before and after collection.
    """
    private, floor, public, cap = (_food(receipt, f) for f in
                                   ('private_open', 'protected', 'depot_open', 'reserve_cap'))
    assessed, conceded, refused, gross, handling, net = (_food(receipt, f) for f in
        ('baseline_levy', 'foregone_concession', 'refused', 'levied', 'handling_used', 'deposited'))
    if assessed > min(max(0, private-floor), max(0, cap-public)):
        raise ValueError('Food assessment exceeds taxable surplus or free depot space')
    if assessed != conceded + refused + gross:
        raise ValueError('Food assessment differs from concessions, nonpayment and collections')
    if gross != _food(receipt, 'standing_levy') + _food(receipt, 'extra_levy'):
        raise ValueError('Standing and supplemental food collections do not match gross')
    if gross != handling + net:
        raise ValueError('Gross food collection differs from handling and net deposit')
    if private-gross != _food(receipt, 'private_close') or public+net != _food(receipt, 'depot_close'):
        raise ValueError('Private or public closing food balance does not reconcile')

    if net > 0:
        reason = 'positive_net'
    elif assessed > 0:
        reason = 'handling' if gross else 'concession_or_refusal'
    elif private <= floor:
        reason = 'no_taxable_surplus'
    elif public >= cap:
        reason = 'warehouse_full'
    else:
        reason = 'below_integer_levy_or_other_nonassessment'
    return [private, floor, public, cap, assessed, conceded, refused, gross, handling, net, reason]
