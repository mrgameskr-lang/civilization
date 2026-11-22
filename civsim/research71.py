"""Local field trials within the elected government's funded soil appropriation."""
from .audit import BalanceError
from .public_works import _soil


VERSION = "farm-trial/1"
TRIALS = 2
FARM_BONUS = 30


def _check(condition, message):
    if not condition:
        raise BalanceError(message)


def prepare(regions, decisions, memory, year, hold, *, knowledge=None):
    """Choose a method for the approved soil job before transport, climate or production."""
    prior = {s["id"]: s for s in memory or ()}
    _check(memory is None or (len(memory) == len(regions) and prior.keys() == {r.id for r in regions}),
           "research sites differ from resident regions")
    old = {o["region"]: o["previous"] for plan in decisions.values() for o in plan["observations"]}
    rows, targets = [], set()
    for r in sorted(regions, key=lambda region: region.id):
        saved = prior.get(r.id, {})
        n, learned = saved.get("trials", 0), saved.get("adoption_year")
        transferred = knowledge is not None and knowledge[r.id]["opening_method"] == "transfer"
        _check(type(n) is int and 0 <= n <= TRIALS and
               ((learned is None and n < TRIALS) or
                (n == (1 if transferred else TRIALS) and type(learned) is int and TRIALS <= learned < year)),
               "invalid prior field-trial state")
        plan, obs = decisions[r.owner], old[r.id]
        funded_target = plan["action"] == "soil" and plan["target_region"] == r.id
        standard = _soil(r.farmland, r.soil)[1]
        trial_gain = _soil(r.farmland, r.soil, max_tiles=6)[1]
        lost_gain = standard - trial_gain
        soil = max(r.soil, 1)
        lost_food = (obs["food_output"] * lost_gain + soil - 1) // soil
        # Price a trial as one of two installments needed for a three-harvest return.
        expected = 3 * obs["food_output"] * FARM_BONUS // (1000 * TRIALS)
        if learned is not None:
            reason = "already_learned"
        elif not funded_target:
            reason = "other_fiscal_choice"
        elif 4 * obs["unmet"] > obs["food_need"]:
            reason = "urgent_hunger"
        elif expected <= lost_food or not lost_gain:
            reason = "insufficient_expected_return"
        elif hold:
            reason = "diagnostic_hold"
        else:
            reason = "awaiting_project"
            targets.add(r.id)
        rows.append({"id":r.id, "owner":r.owner, "opening_trials":n, "opening_adoption_year":learned,
                     "level_before":int(learned is not None), "previous_production_level":int(learned is not None and learned < year-1),
                     "first_application":learned == year-1, "expected_food_per_trial":expected,
                     "foregone_food_estimate":lost_food, "reason":reason})
    return {"version":VERSION, "first_turn":memory is None, "hold":hold, "regions":rows}, targets


def post(ledger, projects, year, *, knowledge=None):
    """Only an executed job can pay for one trial. Costs below classify its existing debits."""
    paid = {p["target"]: p for p in projects if p.get("field_trial") is True}
    for r in ledger["regions"]:
        trial = int(r["id"] in paid)
        n = r["opening_trials"] + trial
        if r["reason"] == "awaiting_project":
            r["reason"] = "paid_trial" if trial else "project_unfunded"
        contact = knowledge[r["id"]]["opening_contact"] if knowledge is not None else None
        learned = r["opening_adoption_year"]
        if trial and (n == TRIALS or (contact is not None and contact["year"] < year)):
            learned = year
        r.update(closing_trials=n, level_after=int(learned is not None), adoption_year=learned,
                 project_id=paid[r["id"]]["project_id"] if trial else None,
                 trial_workers=2*trial, trial_ore=trial, trial_tools=trial,
                 cumulative_workers=2*n, cumulative_ore=n, cumulative_tools=n)


def closing(ledger):
    return [{"id":r["id"], "trials":r["closing_trials"], "adoption_year":r["adoption_year"]}
            for r in ledger["regions"]]


def audit(record, previous, local, plans, *, knowledge=None):
    """Rebuild decisions from fiscal observations, and match paid trials to physical jobs."""
    from .storage import canonical_line
    cfg = record["public_policy"]
    ledger = record.get("research")
    prev = (previous or {}).get("research")
    _check(("research_rule" in cfg) == ("research" in record) == (ledger is not None) and
           (prev is None or ledger is not None),
           "research rule or continuity mismatch")
    if ledger is None:
        _check(all("field_trial" not in p for p in record["government"]["works"]["projects"]) and
               all("farm_tech_level" not in r["production"] for r in record["regions"]),
               "historical path contains research")
        return None, None
    year = record["year"]
    _check(cfg["research_rule"] == ledger["version"] == VERSION and type(ledger["hold"]) is bool
           and type(ledger["first_turn"]) is bool, "invalid field-trial rule")
    if previous is not None or year == 1:
        _check(ledger["first_turn"] is (prev is None), "unexpected field-trial activation")
    if prev is not None:
        memory = closing(prev)
    elif ledger["first_turn"]:
        memory = None
    else:
        memory = [{"id":r["id"], "trials":r["opening_trials"], "adoption_year":r["opening_adoption_year"]}
                  for r in ledger["regions"]]
    expected, targets = prepare(local, plans, memory, year, ledger["hold"], knowledge=knowledge)
    post(expected, record["government"]["works"]["projects"], year, knowledge=knowledge)
    _check(canonical_line(expected) == canonical_line(ledger), "unreconciled research decision or cost")
    return targets, {r["id"]:r["level_before"] for r in expected["regions"]}
