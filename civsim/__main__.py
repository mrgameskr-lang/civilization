"""Command-line entry point for simulation, analysis and deterministic replay."""

import argparse
import json
from pathlib import Path
import sys

from .analysis import summary, write_panel
from .rules import LEGACY, POLICIES31, Rules
from .storage import verify_run, write_run


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m civsim", description="자율 문명 시뮬레이션")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="새 디렉터리에 세계 지도와 연간 원장 저장")
    run.add_argument("--out", required=True, type=Path, help="새 실행 디렉터리")
    run.add_argument("--seed", type=int, default=42, help="세계 생성 시드 (기본 42)")
    run.add_argument("--width", type=int, default=48, help="가로 타일 수 (기본 48)")
    run.add_argument("--height", type=int, default=32, help="세로 타일 수 (기본 32)")
    run.add_argument("--nations", type=int, default=8, help="국가 수 (기본 8)")
    run.add_argument("--years", type=int, default=50, help="실행 연수 (기본 50)")
    run.add_argument("--labor", choices=("idle", "reallocate"), default=LEGACY.labor,
                     help="농업 유휴 노동 처리 (기본 idle)")
    run.add_argument("--trade-order", default=",".join(LEGACY.order), metavar="GOODS",
                     help="세 재화의 결제 순서 (기본 food,ore,tools)")
    run.add_argument("--investment", choices=("off", "inventory", "capital"), default="off",
                     help="3.0 도구 재고 제어(inventory) 또는 재고 제어와 설비 투자(capital)")
    run.add_argument("--policy31", choices=("off", *POLICIES31), default="off",
                     help="3.1 실물투자 규칙. --investment capital과 함께 선택")

    regional = commands.add_parser("regional", help="4.0 지역 생산·도로 운송 원장 저장")
    regional.add_argument("--out", required=True, type=Path)
    regional.add_argument("--seed", type=int, default=42)
    regional.add_argument("--years", type=int, default=50)
    regional.add_argument("--per-nation", type=int, default=4)
    regional.add_argument("--logistics", choices=("limited", "unlimited"), default="limited")
    regional.add_argument("--investment-scope", choices=("regional", "national"), default="regional")
    regional.add_argument("--no-soil-care", action="store_true")
    regional.add_argument("--close-road", action="append", default=[], metavar="A-B",
                          help="해당 국내 도로 폐쇄. 지역 번호 두 개를 작은 순서로 지정")

    analyze = commands.add_parser("analyze", help="연간 기록을 읽어 JSON 요약 출력")
    analyze.add_argument("directory", type=Path, help="실행 디렉터리")
    analyze.add_argument("--csv", type=Path, help="국가별 연간 지표를 저장할 새 CSV 파일")

    verify = commands.add_parser("verify", help="같은 조건으로 재실행해 원장 대조")
    verify.add_argument("directory", type=Path, help="실행 디렉터리")
    args = parser.parse_args()

    try:
        if args.command == "run":
            order = tuple(good.strip() for good in args.trade_order.split(","))
            rules = Rules(labor=args.labor, order=order, investment=args.investment, policy31=args.policy31)
            write_run(args.out, seed=args.seed, width=args.width, height=args.height,
                      nations=args.nations, years=args.years, rules=rules)
            print(f"{args.years}년 실행 기록을 저장했습니다. {args.out.resolve()}")
        elif args.command == "regional":
            from .regional_engine import RegionalPolicy
            from .regional_storage import write_regional_run
            closed = tuple(sorted(tuple(int(i) for i in edge.split("-")) for edge in args.close_road))
            policy = RegionalPolicy(args.logistics, args.investment_scope, not args.no_soil_care, closed)
            write_regional_run(args.out, seed=args.seed, years=args.years, per_nation=args.per_nation, policy=policy)
            print(f"4.0 지역 원장을 저장했습니다. {args.out.resolve()}")
        elif args.command == "analyze":
            totals = summary(args.directory)
            if args.csv is not None:
                write_panel(args.directory, args.csv)
            print(json.dumps(totals, ensure_ascii=False, indent=2))
        else:
            print(verify_run(args.directory))
    except (OSError, ValueError) as error:
        print(f"civsim 오류 · {error}", file=sys.stderr)
        return 1
    except (KeyError, TypeError, IndexError, AttributeError) as error:
        # A valid JSON value can still be missing a field or use the wrong type.
        if args.command == "run":
            raise
        print(f"실행 기록의 필드와 자료형을 확인하세요. {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    # Make redirected JSON and diagnostics UTF-8 even under legacy Windows locales.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
