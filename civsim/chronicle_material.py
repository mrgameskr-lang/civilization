"""Read regional meal, population and domestic relief receipts from a completed turn."""
from collections import defaultdict

from .chronicle_event import Candidate


def _relief_receipts(record):
    stages = []
    if "government" in record:
        stages.append(("ordinary", "/government/relief", record["government"]["relief"]))
    if "emergency_relief" in record:
        stages.append(("emergency", "/emergency_relief", record["emergency_relief"]))
    receipts = defaultdict(list)
    for label, path, stage in stages:
        for index, shipment in enumerate(stage["shipments"]):
            receipts[shipment["target"]].append((label, f"{path}/shipments/{index}", shipment["quantity"]))
    return receipts


def candidates(record):
    receipts = _relief_receipts(record)
    for index, area in enumerate(record["regions"]):
        owner, region = area["owner"], area["id"]
        name = area["opening"]["name"]
        path = f"/regions/{index}"
        location = {"region_id": path + "/id", "owner": path + "/owner", "region_name": path + "/opening/name"}
        meal = area["consumption"]
        need, unmet, eaten = meal["food_need"], meal["food_unmet"], meal["food_eaten"]
        if need > 0 and unmet >= 100 and 5 * unmet >= need:
            evidence = {**location, **{key: f"{path}/consumption/{key}" for key in ("food_need", "food_eaten", "food_unmet")}}
            yield Candidate(
                "food_crisis", owner, region, 55 + min(40, 50 * unmet // need),
                f"{name} 지역 주민에게 필요한 식량 {need:,}단위 가운데 {eaten:,}단위가 소비됐고 "
                f"{unmet:,}단위가 부족했다.", evidence,
            )

        opening, closing = area["opening"]["population"], area["closing"]["population"]
        change = closing - opening
        if opening > 0 and abs(change) >= 50 and 20 * abs(change) >= opening:
            evidence = {**location, "opening_population": path + "/opening/population",
                        "closing_population": path + "/closing/population"}
            evidence.update({key: f"{path}/demography/{key}" for key in ("births", "deaths", "immigrants", "emigrants")})
            kind, verb = ("population_rise", "늘었다") if change > 0 else ("population_fall", "줄었다")
            yield Candidate(
                kind, owner, region, 62 + min(32, 200 * abs(change) // opening),
                f"{name} 지역 인구는 연초 {opening:,}명에서 연말 {closing:,}명이 되어 "
                f"한 해 동안 {abs(change):,}명 {verb}.", evidence,
            )

        deliveries = receipts.get(region, ())
        received = sum(quantity for _, _, quantity in deliveries)
        if need > 0 and received >= 100 and 20 * received >= need:
            evidence = {**location, "food_need": path + "/consumption/food_need"}
            ordinary = 0
            for index_in_region, (label, source, quantity) in enumerate(deliveries):
                if label == "ordinary":
                    ordinary += quantity
                evidence[f"{label}_{index_in_region}_target"] = source + "/target"
                evidence[f"{label}_{index_in_region}_quantity"] = source + "/quantity"
            yield Candidate(
                "large_relief", owner, region, 65 + min(30, 100 * received // need),
                f"{name} 지역에 구호 식량 {received:,}단위가 도착했다. 정규 구호로 {ordinary:,}단위, "
                f"긴급 구호로 {received - ordinary:,}단위를 받았다.", evidence,
            )
