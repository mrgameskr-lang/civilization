"""Re-run each short fork from the identical audited opening and publish its actual receipts."""
import argparse
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from civsim.annual_game import create
from civsim.peace62 import snapshot62
from civsim.regional_custody import audit_meal_custody
from civsim.storage import canonical_line
from civsim.unit_economy import Move, audit_game, step_game
from civsim.unit_upkeep import Upkeep
from experiments.priority_evidence import COLUMNS as FISCAL_COLUMNS, region_rows
from experiments.priority_receipts import COLUMNS, checkout_rows
from experiments.turn_civil_balances import paired_civil_delta, turn_civil_balances


def case(year, home, count, command):
    opening = create(0)
    for _ in range(year - 1):
        prior = step_game(opening)
    results, records = {}, {}
    for arm in ("move_off", "move_on", "relief_first"):
        game = deepcopy(opening)
        row = step_game(game,command,upkeep=Upkeep(home,count) if arm != "move_off" else None,
                        relief_first=True if arm=="relief_first" else None)
        following = step_game(game)
        audit_game(row,game.economy.world,prior)
        audit_game(following,game.economy.world,row)
        for entry in (row,following):
            audit_meal_custody(entry)
        costs = checkout_rows(row)
        results[arm] = {
            "move":row["unit_game"], "upkeep":row.get("unit_upkeep"),
            "next_upkeep":following.get("unit_upkeep"),"fiscal_accounts":region_rows(row,next_record=following),
            "item_evidence":list(costs.values()),"civil":turn_civil_balances(row),
            "relief_shipments":row["government"]["relief"]["shipments"],
            "next_locations":following["unit_game"]["opening_away"],
            "annual_sha256":[sha256(canonical_line(v)).hexdigest() for v in (row,following)]}
        records[arm] = row
    return {"seed":0,"year":year,"home":home,"count":count,"item_columns":COLUMNS,"fiscal_columns":FISCAL_COLUMNS,
            "opening_sha256":sha256(canonical_line(snapshot62(opening.economy))).hexdigest(),"arms":results,
            "paired_deltas":{a+"-minus-"+b:paired_civil_delta(records[b],records[a])
                for a,b in (("move_on","move_off"),("relief_first","move_off"),("relief_first","move_on"))}}


def suite():
    return {k:case(year,h,q,cmd) for k,year,h,q,cmd in (
        ("one",2,5,1,Move(5,5,7,1)), ("two",2,5,2,Move(5,5,7,2)),
        ("competing_relief",7,5,2,None), ("empty_tools",10,3,2,None))}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out",type=Path,required=True)
    args = p.parse_args()
    data = canonical_line(suite())
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open("xb") as f:
        f.write(data)
    print(f"4 same-opening forks, 3 arms each; SHA-256 {sha256(data).hexdigest()}")
