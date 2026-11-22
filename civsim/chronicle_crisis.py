"""Record a bilateral civilian crisis only when its audited level changes."""
from .chronicle_event import Candidate


TRANSITIONS = {
    (0, 1): ("start", "border_crisis_started", "시작됐다", 80),
    (1, 2): ("escalate", "border_crisis_escalated", "고조됐다", 86),
    (2, 1): ("ease", "border_crisis_eased", "완화됐다", 75),
    (1, 0): ("resolve", "border_crisis_resolved", "해소됐다", 82),
}


def _receipt_pointers(row, pair, diplomatic_index):
    base = f"/diplomacy/pairs/{diplomatic_index}/opening"
    opening = row["diplomacy"]["pairs"][diplomatic_index]["opening"]
    flows = opening["last"]
    if (opening["year"] != pair["evidence_year"] or opening["tension"] != pair["tension"]
            or opening["trust"] != pair["trust"]
            or sum(f["trade_denied"] for f in flows) != pair["trade_denied"]
            or sum(f["migration_denied_exit"] + f["migration_denied_entry"] for f in flows) != pair["people_denied"]
            or sum(f["agreement_breach"] for f in flows) != pair["breaches"]):
        raise ValueError("border crisis disagrees with the preceding diplomatic settlement")
    evidence = {"diplomatic_opening_year": f"{base}/year"}
    for i in range(len(flows)):
        for field in ("source", "target", "trade_denied", "migration_denied_exit", "migration_denied_entry",
                      "agreement_breach"):
            evidence[f"{field}_{i}"] = f"{base}/last/{i}/{field}"
    edge = set(pair["road"])
    for kind, released in (("trade", "goods_released"), ("migration", "people_released")):
        total = 0
        for i, receipt in enumerate(row["diplomacy"]["physical"][f"{kind}_attempts"]):
            passed = receipt.get("appeal_granted", 0)
            if passed and {receipt["source"], receipt["target"]} == edge:
                evidence[f"{kind}_receipt_{i}"] = f"/diplomacy/physical/{kind}_attempts/{i}/appeal_granted"
                total += passed
        if total != pair[released]:
            raise ValueError("border crisis clearances disagree with the physical crossing receipts")
    return evidence


def transitions(row):
    pairs = row.get("crisis", {}).get("pairs", ())
    if not pairs:
        return
    bilateral = {(p["a"], p["b"]): i for i, p in enumerate(row["diplomacy"]["pairs"])}
    for index, pair in enumerate(pairs):
        before, after = pair["opening_level"], pair["closing_level"]
        if before == after:
            if pair["transition"] != "none":
                raise ValueError("unchanged border crisis has a transition label")
            continue
        spec = TRANSITIONS.get((before, after))
        if spec is None or spec[0] != pair["transition"] or pair["evidence_year"] != row["year"] - 1:
            raise ValueError("border crisis transition disagrees with its levels or observation year")
        _, kind, label, importance = spec
        path = f"/crisis/pairs/{index}"
        evidence = {k: f"{path}/{k}" for k in (
            "a", "b", "opening_level", "closing_level", "transition", "evidence_year", "trade_denied",
            "people_denied", "breaches", "tension", "trust", "staffed", "workers", "goods_released", "people_released")}
        evidence.update(road_a=f"{path}/road/0", road_b=f"{path}/road/1")
        evidence.update(_receipt_pointers(row, pair, bilateral[pair["a"], pair["b"]]))
        description = (f"두 나라의 민간 국경 위기가 {label} (단계 {before}→{after}). "
                       f"{pair['evidence_year']}년 결산에 거래 거절 {pair['trade_denied']:,}단위와 "
                       f"이주 거절 {pair['people_denied']:,}명이 기록됐다.")
        if pair["staffed"]:
            description += (f" 이번 해 양국이 통행 심사에 노동 {pair['workers']:,}인년을 썼다. "
                            f"심사로 통과한 물자는 {pair['goods_released']:,}단위, "
                            f"이주민은 {pair['people_released']:,}명이었다.")
        yield Candidate(kind, pair["a"], None, importance, description, evidence, counterparty=pair["b"])
