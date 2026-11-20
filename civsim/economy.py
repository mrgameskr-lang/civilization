"""Annual production, national markets, and consumption in integer units."""

from .model import GOODS, Nation


def produce(nation: Nation, climate: int) -> dict:
    """Allocate the year's workers and post real production and material costs."""
    opening = nation.stock.copy()
    workers = nation.population // 2
    farm_share = max(450, 760 - 220 * opening["food"] // max(1, nation.population))
    farmers = workers * farm_share // 1000
    miners = (workers - farmers) // 2
    artisans = workers - farmers - miners

    # A tile supports at most 20 productive farmers. Only opening tools equip them.
    land_capacity = 20 * nation.land
    active_farmers = min(farmers, land_capacity)
    tool_need = (active_farmers + 29) // 30
    tools_used = min(opening["tools"], tool_need)
    equipment = 1000 + 150 * tools_used // max(1, tool_need)
    skill = nation.productivity * nation.technology
    food = (active_farmers * 32 * skill * nation.fertility * nation.soil
            * climate * equipment // (10 * 1000**6))

    mining_capacity = miners * skill * nation.ore_grade // (2 * 1000**3)
    ore = min(nation.deposit, mining_capacity)
    factory_capacity = artisans * skill // (3 * 1000**2)
    tools = min(factory_capacity, (opening["ore"] + ore) // 2)
    produced = {"food": food, "ore": ore, "tools": tools}
    used = {"food": 0, "ore": 2 * tools, "tools": tools_used}
    for good in GOODS:
        nation.stock[good] += produced[good] - used[good]

    old_deposit = nation.deposit
    old_soil = nation.soil
    nation.deposit -= ore
    erosion = 8 * active_farmers // max(1, land_capacity)
    nation.soil = min(1150, max(550, old_soil + 6 - erosion))
    return {
        "opening_stock": opening, "population": nation.population,
        "productivity": nation.productivity, "technology": nation.technology,
        "fertility": nation.fertility, "climate": climate, "land": nation.land,
        "ore_grade": nation.ore_grade, "deposit_before": old_deposit,
        "deposit_after": nation.deposit, "soil_before": old_soil,
        "soil_after": nation.soil, "erosion": erosion, "workers": workers,
        "farm_share": farm_share, "labor": {"farm": farmers, "mine": miners,
                                            "factory": artisans},
        "active_farmers": active_farmers, "tool_need": tool_need,
        "equipment": equipment, "mining_capacity": mining_capacity,
        "factory_capacity": factory_capacity, "produced": produced, "used": used,
        "closing_stock": nation.stock.copy(),
    }


BASE_PRICES = {"food": 8, "ore": 4, "tools": 12}


def market(nations: list[Nation]) -> dict:
    """Clear each good against fixed opening quotes. Funds settle per fill."""
    ordered = sorted(nations, key=lambda nation: nation.id)
    targets = {}
    prices = {}
    opening = {}
    for nation in ordered:
        population = nation.population
        targets[nation.id] = {
            "food": population + population // 8,
            "ore": population // 20,
            "tools": population // 40,
        }
        opening[nation.id] = {"stock": nation.stock.copy(), "cash": nation.cash}
        prices[nation.id] = {}
        for good, base in BASE_PRICES.items():
            scarcity_quote = base * targets[nation.id][good] // max(1, nation.stock[good])
            prices[nation.id][good] = max(base // 4, min(4 * base, scarcity_quote))

    trades = []
    active = [n for n in ordered if n.population > 0]
    for good in GOODS:
        sellers = sorted((n for n in active if n.stock[good] > targets[n.id][good]),
                         key=lambda n: (prices[n.id][good], n.id))
        buyers = sorted((n for n in active if n.stock[good] < targets[n.id][good]),
                        key=lambda n: (-prices[n.id][good], n.id))
        seller_index = 0
        for buyer in buyers:
            need = targets[buyer.id][good] - buyer.stock[good]
            while need and seller_index < len(sellers):
                seller = sellers[seller_index]
                available = seller.stock[good] - targets[seller.id][good]
                unit_price = (prices[seller.id][good] + prices[buyer.id][good]) // 2
                quantity = min(need, available, buyer.cash // unit_price)
                if quantity == 0:
                    break
                value = quantity * unit_price
                trades.append({
                    "seller": seller.id, "buyer": buyer.id, "good": good,
                    "quantity": quantity, "unit_price": unit_price,
                    "value": value, "buyer_cash_before": buyer.cash,
                    "offered": available, "requested": need,
                })
                seller.stock[good] -= quantity
                buyer.stock[good] += quantity
                seller.cash += value
                buyer.cash -= value
                need -= quantity
                if quantity == available:
                    seller_index += 1
    return {"opening": opening, "targets": targets, "prices": prices, "trades": trades}


def consume(nation: Nation) -> dict:
    """Residents eat one ration each if available; 1/12 of leftover food spoils."""
    opening_food = nation.stock["food"]
    food_eaten = min(nation.population, opening_food)
    food_spoiled = (opening_food - food_eaten) // 12
    used = {"food": food_eaten + food_spoiled, "ore": 0, "tools": 0}
    nation.stock["food"] -= used["food"]
    return {
        "opening_food": opening_food, "food_need": nation.population,
        "food_eaten": food_eaten, "food_spoiled": food_spoiled,
        "food_unmet": nation.population - food_eaten, "used": used,
        "closing_food": nation.stock["food"],
    }
