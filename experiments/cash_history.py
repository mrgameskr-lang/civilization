"""Baseline cash concentration and two matched-market order comparisons."""

from collections import Counter
import json
from statistics import fmean, median

from civsim.engine import step
from civsim.model import generate_world
from civsim.rules import Rules


YEARS = (0, 5, 10, 25, 50)
COUNTS = ("ever_zero_countries", "zero_country_years", "recovered_above_one_percent_after_zero",
          "food_net_buyers_at_first_zero", "food_only_net_cost_at_first_zero", "final_food_net_buyers")


def _concentration(wallets, total):
    return {"top1_share": max(wallets.values()) / total,
            "hhi": sum(cash * cash for cash in wallets.values()) / total**2}


def cash_path(nations, records, checkpoints=YEARS):
    initial = {n.id: n.cash for n in nations}
    total = sum(initial.values())
    net = {i: Counter() for i in initial}
    zeroed, recovered = {}, set()
    snapshots = {0: _concentration(initial, total)}
    leaders = {0: max(initial, key=initial.get)}
    counts = dict.fromkeys(COUNTS, 0)

    for record in records:
        year = record["year"]
        for deal in record["market"]["trades"]:
            value = deal["quantity"] * deal["unit_price"]
            net[deal["seller"]][deal["good"]] += value
            net[deal["buyer"]][deal["good"]] -= value
        wallets = {r["id"]: r["closing"]["cash"] for r in record["countries"]}
        if year in checkpoints:
            snapshots[year] = _concentration(wallets, total)
            leaders[year] = max(wallets, key=wallets.get)
        for i, cash in wallets.items():
            if cash != initial[i] + sum(net[i].values()):
                raise ValueError(f"year {year}, country {i}: cash flows do not reconcile")
            if cash == 0:
                counts["zero_country_years"] += 1
                if i not in zeroed:
                    zeroed[i] = year
                    counts["food_net_buyers_at_first_zero"] += int(net[i]["food"] < 0)
                    counts["food_only_net_cost_at_first_zero"] += int(
                        net[i]["food"] == -initial[i] and net[i]["ore"] == net[i]["tools"] == 0)
            elif i in zeroed and cash * 100 > initial[i]:
                recovered.add(i)
    counts.update(ever_zero_countries=len(zeroed), recovered_above_one_percent_after_zero=len(recovered),
                  final_food_net_buyers=sum(v["food"] < 0 for v in net.values()))
    return {**counts, "checkpoints": snapshots, "first_zero_years": list(zeroed.values()), "leaders": leaders}


def first_divergence(seed, nation_id):
    """Compare both full trajectories until their post-year country states first differ."""
    rules = [Rules(), Rules(order=("ore", "tools", "food"))]
    worlds = [generate_world(seed) for _ in rules]
    for year in range(1, 51):
        records = [step(world, year, variant) for world, variant in zip(worlds, rules)]
        if worlds[0].nations == worlds[1].nations:
            continue
        if records[0]["market"]["opening"] != records[1]["market"]["opening"]:
            raise ValueError("first divergent year has different opening market states")
        country = records[0]["countries"][nation_id]
        example = {"seed": seed, "year": year, "nation_id": nation_id, "name": country["opening"]["name"],
                   "opening_cash": country["opening"]["cash"], "population": country["opening"]["population"],
                   "market_open_food": country["production"]["closing_stock"]["food"]}
        for row, variant in zip(records, rules):
            subject = row["countries"][nation_id]
            trades = [{k: t[k] for k in ("good", "seller", "buyer", "quantity", "unit_price", "value")}
                      for t in row["market"]["trades"] if nation_id in (t["seller"], t["buyer"])]
            example["-".join(variant.order)] = {
                "trades": trades, "closing_cash": subject["closing"]["cash"],
                "food_unmet": subject["consumption"]["food_unmet"],
            }
        return example
    raise ValueError(f"no divergent year within 50 years for seed {seed}")


def report():
    paths = []
    for seed in range(20):
        world = generate_world(seed)
        paths.append(cash_path(world.nations, (step(world, year) for year in range(1, 51))))
    return {
        "seeds": list(range(20)), "years_per_seed": 50, "baseline": "idle/food-ore-tools",
        "checkpoints": [{
            "year": year,
            "mean_top1_share": fmean(p["checkpoints"][year]["top1_share"] for p in paths),
            "mean_hhi": fmean(p["checkpoints"][year]["hhi"] for p in paths),
            "worlds_top1_at_least_half": sum(p["checkpoints"][year]["top1_share"] >= 0.5 for p in paths),
        } for year in YEARS],
        **{k: sum(p[k] for p in paths) for k in COUNTS},
        "median_first_zero_year": median(y for p in paths for y in p["first_zero_years"]),
        "same_leader_y5_y50": sum(p["leaders"][5] == p["leaders"][50] for p in paths),
        "recovery_criterion": "After first zero year-end cash, any later year-end cash > 1% of initial cash.",
        "net_food_buyer_criterion": "Cumulative food import payments exceed food export receipts.",
        "first_divergences": [first_divergence(6, 0), first_divergence(17, 1)],
    }


if __name__ == "__main__":
    print(json.dumps(report(), indent=2, ensure_ascii=True))
