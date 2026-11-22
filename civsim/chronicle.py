"""Build an evidence-linked Korean chronicle from completed annual game records."""
import argparse
from collections import defaultdict
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys

from .chronicle_event import resolve
from .chronicle_research import farm_adoptions, farm_applications
from .storage import canonical_line


VERSION = "chronicle/1"
YEAR_LIMIT = 4
ESCALATION = 10
EPISODES = {"food_crisis", "population_rise", "population_fall", "large_relief"}


def annual_candidates(row):
    from .chronicle_civic import candidates as civic
    from .chronicle_material import candidates as material
    yield from material(row)
    yield from civic(row)


def _order(candidate):
    return (-candidate.importance, candidate.kind, candidate.country,
            -1 if candidate.region is None else candidate.region,
            -1 if candidate.counterparty is None else candidate.counterparty,
            candidate.description, tuple(sorted(candidate.evidence.items())))


def _episode(candidate):
    return (candidate.kind, candidate.country, candidate.region, candidate.counterparty)


def _evidence(row, pointers):
    evidence = {}
    for label, pointer in pointers.items():
        value = resolve(row, pointer)
        if isinstance(value, (dict, list)):
            raise ValueError(f"expected a scalar fact at {pointer}")
        evidence[label] = {"pointer": pointer, "value": value}
    if not evidence:
        raise ValueError("chronicle entry has no evidence")
    return evidence


def _entry(row, digest, candidate):
    pointers = candidate.evidence.copy()
    for index, country in enumerate(row.get("countries", ())):
        if country["id"] == candidate.country:
            pointers["country_name"] = f"/countries/{index}/opening/name"
        if country["id"] == candidate.counterparty:
            pointers["counterparty_name"] = f"/countries/{index}/opening/name"
    return {"year": row["year"], "country": candidate.country, "region": candidate.region,
            "counterparty": candidate.counterparty, "kind": candidate.kind,
            "importance": candidate.importance, "description": candidate.description,
            "record_sha256": digest, "evidence": _evidence(row, pointers)}


class Chronicle:
    """Read rows in order. Keep only selected scalar facts and ongoing episode scores."""
    def __init__(self, seed=None):
        self.seed = seed
        self._year = self._total = self._repeats = self._excluded = 0
        self._episodes = {}
        self._events = []
        self._awaiting_application = {}

    def observe(self, row):
        year = row["year"]
        if type(year) is not int or year != self._year + 1:
            raise ValueError("chronicle needs consecutive annual records beginning at 1")
        candidates = sorted(annual_candidates(row), key=_order)
        eligible = []
        ongoing = {}
        for candidate in candidates:
            if candidate.kind in EPISODES:
                key = _episode(candidate)
                previous_score = self._episodes.get(key)
                ongoing[key] = previous_score
                if previous_score is not None and candidate.importance < previous_score + ESCALATION:
                    continue
            eligible.append(candidate)
        selected = eligible[:YEAR_LIMIT]
        advances = sorted(farm_adoptions(row), key=_order)
        applications = list(farm_applications(row))
        digest = sha256(canonical_line(row)).hexdigest() if selected or advances or applications else None
        entries = [_entry(row, digest, candidate) for candidate in selected]
        # Every attained level is history, even during a year with four other headlines.
        milestones = [_entry(row, digest, candidate) for candidate in advances]
        resolved = {}
        for key, pointers in applications:
            if key not in self._awaiting_application or key in resolved:
                raise ValueError("first farm application has no unique preceding completion")
            resolved[key] = {"year": year, "record_sha256": digest, "evidence": _evidence(row, pointers)}
        for key, application in resolved.items():
            self._awaiting_application.pop(key)["application"] = application
        for event in milestones:
            event["application"] = None
            self._awaiting_application[event["country"], event["region"], year] = event
        for candidate in selected:
            if candidate.kind in EPISODES:
                ongoing[_episode(candidate)] = candidate.importance
        self._episodes = ongoing
        self._events.extend(entries)
        self._events.extend(milestones)
        self._year = year
        self._total += len(candidates) + len(advances)
        self._repeats += len(candidates) - len(eligible)
        self._excluded += len(eligible) - len(selected)

    def report(self):
        return {"schema": VERSION, "seed": self.seed, "years": self._year,
                "candidates": self._total, "suppressed_repeats": self._repeats,
                "excluded_by_year_limit": self._excluded, "events": deepcopy(self._events)}


def _location(event):
    facts = event["evidence"]
    country = facts.get("country_name", {}).get("value", f"국가 {event['country']}")
    if event["counterparty"] is not None:
        partner = facts.get("counterparty_name", {}).get("value", f"국가 {event['counterparty']}")
        return f"{country}·{partner}"
    if event["region"] is not None:
        return f"{country} · 지역 {event['region']}"
    return country


def _source_pointer(event):
    facts = event["evidence"]
    # Prefer the quantity behind the statement over an identity or classification.
    for key in ("food_unmet", "closing_population", "seats", "participants", "quantity", "level_after"):
        if key in facts:
            return facts[key]["pointer"]
    keys = sorted(facts)
    key = next((key for key in keys if key.endswith("_quantity")), keys[0])
    return facts[key]["pointer"]


def _markdown_event(event):
    text = f"**{_location(event)}** · {event['description']} (`{_source_pointer(event)}`)"
    if event["kind"] == "farm_tech_adoption":
        application = event["application"]
        if application is None:
            return f"{text} 첫 적용 예정 연도는 {event['year'] + 1}년이다. 해당 생산 원장은 아직 관측되지 않았다."
        food = application["evidence"]["food_produced"]
        without = application["evidence"]["food_without_tech"]["value"]
        return (f"{text} {application['year']}년 첫 적용 때 이 지역의 식량 생산량은 "
                f"{food['value']:,}단위였다. 같은 투입으로 기존 농법을 계산한 값은 {without:,}단위다. "
                f"(`{food['pointer']}`)")
    return text


def render_markdown(report):
    events = report["events"]
    lines = ["# 문명 연대기", "",
             f"시드 {report['seed']} · 관측 {report['years']}년 · 수록 사건 {len(events)}건",
             "", f"탐지 후보 {report['candidates']}건 중 지속된 현상 {report['suppressed_repeats']}건과 "
             f"연간 수록 한도를 넘은 후보 {report['excluded_by_year_limit']}건을 생략했다."]
    previous_year = None
    for event in events:
        if event["year"] != previous_year:
            previous_year = event["year"]
            lines.extend(["", f"## {previous_year}년", ""])
        lines.append(f"- {_markdown_event(event)}")
    if not events:
        lines.extend(["", "수록 기준에 해당하는 사건이 없었다."])
    return "\n".join(lines) + "\n"


def render_highlights(report):
    decades = defaultdict(dict)
    for event in report["events"]:
        best = decades[(event["year"] - 1) // 10]
        previous = best.get(event["kind"])
        if previous is None or event["importance"] > previous["importance"]:
            best[event["kind"]] = event
    lines = ["# 문명 연대기 발췌", "",
             f"시드 {report['seed']} · 관측 {report['years']}년 · 전체 수록 사건 {len(report['events'])}건",
             "", "10년마다 중요도가 높은 서로 다른 종류의 사건을 최대 세 건씩 실었다."]
    for decade, by_kind in sorted(decades.items()):
        top = sorted(by_kind.values(), key=lambda e: (-e["importance"], e["year"], e["kind"]))[:3]
        lines.extend(["", f"## {10 * decade + 1}~{min(report['years'], 10 * decade + 10)}년", ""])
        for event in sorted(top, key=lambda e: (e["year"], -e["importance"], e["kind"])):
            lines.append(f"- {event['year']}년 · {_markdown_event(event)}")
    if not decades:
        lines.extend(["", "수록 기준에 해당하는 사건이 없었다."])
    return "\n".join(lines) + "\n"


class _LedgerYear:
    def __init__(self, year):
        self.year = year
        self.record = None

    def observe(self, row):
        if row["year"] == self.year:
            self.record = row


def _observe_source(path, observer):
    if path.is_dir():
        from .chronicle_archive import observe_archive
        return observe_archive(path, observer)
    from .annual_game import load
    journal, _ = load(path, observer=observer)
    return journal["seed"]


def chronicle_text(path, output_format="markdown", *, ledger_year=None):
    path = Path(path)
    if ledger_year is not None:
        source = _LedgerYear(ledger_year)
        _observe_source(path, source)
        if source.record is None:
            raise ValueError(f"저장 기록에 {ledger_year}년 원장이 없습니다.")
        return canonical_line(source.record).decode("utf-8")
    observer = Chronicle()
    observer.seed = _observe_source(path, observer)
    report = observer.report()
    if output_format == "markdown":
        return render_markdown(report)
    if output_format == "highlights":
        return render_highlights(report)
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    raise ValueError(f"unknown chronicle output format: {output_format}")


def add_arguments(parser):
    parser.add_argument("save", type=Path, help="연간 게임 저장 파일 또는 검증 가능한 지역 원장 디렉터리")
    display = parser.add_mutually_exclusive_group()
    display.add_argument("--format", choices=("markdown", "highlights", "json"), default="markdown",
                         help="전체 한국어 연대기, 10년별 발췌 또는 근거값을 담은 JSON")
    display.add_argument("--ledger-year", type=int, metavar="YEAR", help="지정한 해의 근거 원장을 JSON으로 출력")


def print_chronicle(args):
    text = chronicle_text(args.save, args.format, ledger_year=args.ledger_year)
    # Preserve the original UTF-8 and LF for external ledger checksum tools on Windows.
    sys.stdout.buffer.write(text.encode("utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description="실제 연간 원장에서 한국어 역사 연대기를 생성합니다.")
    add_arguments(parser)
    args = parser.parse_args(argv)
    try:
        print_chronicle(args)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"{parser.prog}: {exc}\n")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
