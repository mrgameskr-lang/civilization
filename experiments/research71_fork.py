"""Find the first observed adoption and rerun its actual opening with trials deferred."""
from copy import deepcopy
import json

from civsim.annual_game import create, play
from civsim.storage import canonical_line
from civsim.supply62 import snapshot62
from civsim.unit_economy import step_game
from experiments.research71 import command_for, digest


def facts(row, region_id):
    i, region = next((i,r) for i,r in enumerate(row["regions"]) if r["id"] == region_id)
    owner = region["owner"]
    study = next(r for r in row["research"]["regions"] if r["id"] == region_id)
    project = next((p for p in row["government"]["works"]["projects"] if p["action"]=="soil"
                    and p["target"]==region_id), None)
    node = next(n for n in row["government"]["works"]["nodes"] if n["id"] == region_id)
    cabinet = next(n for n in row["competition"]["countries"] if n["id"] == owner)
    production = region["production"]
    return {"year":row["year"], "record_sha256":digest(row), "region":region_id, "owner":owner,
            "political_faction":cabinet["governing_faction"], "trial_receipt":study,
            "works_project":project, "works_node":node, "food":production["produced"]["food"],
            "applied_level":production["farm_tech_level"], "food_without_tech":production["food_without_tech"],
            "food_pointer":f"/regions/{i}/production/produced/food", "population":region["closing"]["population"],
            "global_cash":sum(n["closing"]["cash"] for n in row["countries"])}


def smoke():
    seed = 0
    game = create(seed)
    for year in range(1, 51):
        opening = deepcopy(game)
        row = play(game, command_for("research",year))
        advances = [r for r in row["research"]["regions"] if r["level_after"] > r["level_before"]]
        if not advances:
            continue
        region = min(r["id"] for r in advances)
        held_game = deepcopy(opening)
        opening_hash = digest(snapshot62(opening.economy))
        if digest(snapshot62(held_game.economy)) != opening_hash:
            raise ValueError("annual fork starts from different states")
        options = dict(command_for("research",year) or {})
        options.pop("move", None)
        held = json.loads(canonical_line(step_game(held_game, hold_research=True, **options)))
        now, deferred = facts(row, region), facts(held, region)
        next_command = command_for("research",year+1)
        later = facts(play(game, next_command), region)
        held_later = facts(play(held_game, next_command), region)
        a,b = now["trial_receipt"], deferred["trial_receipt"]
        if (a["opening_trials"] != b["opening_trials"] or a["level_after"] != 1 or b["level_after"] != 0
                or (a["trial_workers"],a["trial_ore"],a["trial_tools"]) != (2,1,1)
                or (b["trial_workers"],b["trial_ore"],b["trial_tools"]) != (0,0,0)
                or now["applied_level"] != deferred["applied_level"] or now["applied_level"] != 0
                or now["works_project"]["used"] != deferred["works_project"]["used"]
                or now["works_node"]["workers_reserved"] != deferred["works_node"]["workers_reserved"]
                or now["works_project"]["treated_tiles"] >= deferred["works_project"]["treated_tiles"]
                or later["applied_level"] != 1 or held_later["applied_level"] != 0
                or later["food"] <= later["food_without_tech"] or later["food"] == held_later["food"]
                or now["global_cash"] != deferred["global_cash"]):
            raise ValueError("small-world paired adoption or funded physical fork failed")
        return {"seed":seed, "year":year, "region":region, "matched_opening_sha256":opening_hash,
                "intervention":"defer field trials for one turn only; other appropriations and later autonomy unchanged",
                "invest":now, "hold":deferred, "invest_next":later, "hold_next":held_later}
    raise ValueError("no adoption in 50 years for the preregistered smoke world")
