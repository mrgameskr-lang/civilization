"""Read closed election, representative-group and bilateral trade records."""
from .chronicle_event import Candidate


FACTION_NAMES = {
    "stewards": "농지관리", "builders": "건설", "mutualists": "상호부조", "restraint": "절제",
}
GROUP_NAMES = {"farm": "농업", "industry": "광공업", "consumer": "소비자"}
# A new, material stoppage outranks a petition of the same size.
ACTION_LABELS = {
    "petition": ("청원", 0), "protest": ("시위", 3),
    "refusal": ("현물세 납부 거부", 7), "strike": ("부분 노동 중단", 9),
}
PACT_EVENTS = {
    "pact_started": ("trade_pact_started", "체결됐다", 77),
    "pact_terminated": ("trade_pact_terminated", "조기에 종료됐다", 91),
}


def _turnovers(countries):
    for index, country in enumerate(countries):
        ballot = country["election"]
        if not ballot or not ballot["election"] or not ballot["turnover"] or ballot["installation"]:
            continue
        former, winner = ballot["previous_incumbent"], ballot["incumbent"]
        if country["governing_faction"] != winner:
            # A one-year retention fork can record the election result but keep the former cabinet.
            continue
        path = f"/competition/countries/{index}"
        count = ballot["seats"][winner]
        yield Candidate(
            kind="government_turnover", country=country["id"], region=None, importance=90,
            description=(f"집권 정파가 {FACTION_NAMES[former]}에서 {FACTION_NAMES[winner]} 정파로 "
                         f"바뀌었다. 새 집권 정파는 대표 의석 {count}석을 얻었다."),
            evidence={"country": f"{path}/id", "election": f"{path}/election/election",
                      "turnover": f"{path}/election/turnover", "former": f"{path}/election/previous_incumbent",
                      "winner": f"{path}/election/incumbent", "governing_faction": f"{path}/governing_faction",
                      "seats": f"{path}/election/seats/{winner}"},
        )


def _actions(regions):
    for index, region in enumerate(regions):
        path = f"/collective/regions/{index}"
        for name, group in sorted(region["groups"].items()):
            action = group["action"]
            if action not in ACTION_LABELS or group["duration"] != 1:
                continue
            count, members = group["participants"], group["members"]
            if count < 15 or members <= 0 or 100 * count < 8 * members:
                continue
            label, weight = ACTION_LABELS[action]
            importance = 56 + min(20, 100 * count // members) + weight
            group_path = f"{path}/groups/{name}"
            yield Candidate(
                kind="collective_action", country=region["owner"], region=region["id"], importance=importance,
                description=(f"{GROUP_NAMES[name]} 대표 집단 {members:,}명 가운데 {count:,}명이 "
                             f"{label}에 참여했다."),
                evidence={"country": f"{path}/owner", "region": f"{path}/id",
                          "action": f"{group_path}/action", "duration": f"{group_path}/duration",
                          "members": f"{group_path}/members", "participants": f"{group_path}/participants"},
            )


def _pacts(events):
    for index, receipt in enumerate(events):
        if receipt["kind"] not in PACT_EVENTS:
            continue
        kind, verb, importance = PACT_EVENTS[receipt["kind"]]
        path = f"/diplomacy/events/{index}"
        yield Candidate(
            kind=kind, country=receipt["a"], counterparty=receipt["b"], region=None, importance=importance,
            description=f"두 나라 사이의 무역 협정 {receipt['quantity']}건이 {verb}.",
            evidence={"event": f"{path}/kind", "country": f"{path}/a", "counterparty": f"{path}/b",
                      "quantity": f"{path}/quantity"},
        )


def candidates(record):
    """Older record formats can omit any one of the civic subsystems."""
    yield from _turnovers(record.get("competition", {}).get("countries", ()))
    yield from _actions(record.get("collective", {}).get("regions", ()))
    yield from _pacts(record.get("diplomacy", {}).get("events", ()))
