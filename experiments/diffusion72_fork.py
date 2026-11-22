"""Physically close one observed domestic migration link in an actual opening world."""
from copy import deepcopy

from civsim.annual_game import create, play
from civsim.supply62 import snapshot62
from experiments.diffusion72 import command_for
from experiments.research71 import digest


def facts(row, target):
    i = next(i for i, r in enumerate(row["regions"]) if r["id"] == target)
    region = row["regions"][i]
    trial = next(r for r in row["research"]["regions"] if r["id"] == target)
    memory = next(r for r in row["diffusion"]["regions"] if r["id"] == target)
    prod = region["production"]
    contact = memory["closing_contact"]
    move = row["moves"][contact["move_index"]] if contact and contact["year"] == row["year"] else None
    return {"year": row["year"], "record_sha256": digest(row), "owner": region["owner"],
            "region": target, "new_contact": memory["new_contact"], "contact": contact,
            "receipt": move, "closing_method": memory["closing_method"], "project_id": trial["project_id"],
            "reason": trial["reason"], "paid_trials": trial["closing_trials"], "trial_workers": trial["trial_workers"],
            "trial_ore": trial["trial_ore"], "trial_tools": trial["trial_tools"], "level_after": trial["level_after"],
            "applied_level": prod["farm_tech_level"], "food": prod["produced"]["food"],
            "food_without_tech": prod["food_without_tech"], "food_pointer": f"/regions/{i}/production/produced/food",
            "population": region["closing"]["population"],
            "border_quantity": sum(t["quantity"] for t in row["border_market"]["trades"]),
            "domestic_quantity": sum(t["quantity"] for t in row["domestic"]["shipments"]),
            "incoming_people": sum(t["people"] for t in row["moves"] if t["target"] == target)}


def smoke():
    seed, source, target, start, finish = 2, 16, 19, 5, 16
    opening = create(seed)
    for year in range(1, start):
        play(opening, command_for("diffusion", year))
    opening_hash = digest(snapshot62(opening.economy))
    paths = {}
    for label, blocked_until in (("open", 0), ("one_year", start), ("until_trial", finish)):
        game = deepcopy(opening)
        if digest(snapshot62(game.economy)) != opening_hash:
            raise ValueError("migration fork changed opening")
        path = []
        for year in range(start, finish + 2):
            cmd = {"move": None, "blocked_migration": [source, target]} if year <= blocked_until else None
            row = play(game, cmd)
            if cmd and any({m["source"], m["target"]} == {source, target} for m in row["moves"]):
                raise ValueError("closed domestic migration link had a movement receipt")
            path.append(facts(row, target))
        paths[label] = path
    open_path, once, closed = (paths[k] for k in ("open", "one_year", "until_trial"))
    invoice = open_path[0]["receipt"]
    if (not invoice or (invoice["source"], invoice["target"], invoice["people"]) != (source, target, 23)
            or once[0]["contact"] or closed[0]["contact"] or once[1]["contact"]["year"] != 6
            or open_path[-2]["closing_method"] != "transfer" or once[-2]["closing_method"] != "transfer"
            or closed[-2]["contact"] or closed[-2]["level_after"] or closed[-1]["applied_level"]
            or open_path[-1]["applied_level"] != 1):
        raise ValueError("actual contact, recontact, transfer or failed uptake evidence changed")
    for path in paths.values():
        trial = path[-2]
        if (trial["trial_workers"], trial["trial_ore"], trial["trial_tools"]) != (2, 1, 1):
            raise ValueError("expected the same paid first trial in every path")
    return {"seed": seed, "opening_year": start, "opening_sha256": opening_hash, "edge": [source, target],
            "commands": {"shared": "research + diffusion year 1; public farm + emergency reserve year 2",
                         "open": [], "one_year": [start], "until_trial": list(range(start, finish + 1))},
            "paths": paths}
