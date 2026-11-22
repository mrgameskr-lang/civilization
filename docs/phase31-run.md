# 3.1 실행 기록

저장소 루트에서 Windows 11, CPython 3.12.14 표준 라이브러리로 실행했다. 아래의 `python`은 이 환경의 번들 CPython 실행 파일을 나타낸다. 배포한 실험 파일에 재실행하려면 출력 경로를 새 이름으로 바꾼다.

## 기준선과 자동 테스트

```console
git switch -c phase31/stability-investment 64fcfeb1a83c046ed523949583c251abc329dfbf
python -m unittest discover -v
Ran 91 tests in 9.617s
OK
```

기존 테스트를 수정하지 않았다. 새 정책의 비용·규모별 효과·반복 선택·후보 순위·유형별 운영 가치, 위조 원장 거부, 독립 표본 분리, 처치·자료 게시·재현을 검증했다. 구현 후 같은 명령에서 **115개 통과(기존 91개, 신규 24개), 10.767초**였다. 초기 구현 중 정책 이름 누락, 테스트 입력에 지표 누락, 게시 코드의 `os` 가져오기 누락으로 발생한 실패는 수정 후 재실행했다. [최종 테스트 출력](phase31-tests.txt)

## 보존과 재생

```console
python -m experiments.verify_archives31 --workers 6
400 archived checkpoint rows: exact initial and annual SHA-256 matches, 280 distinct seed/policy trajectories
phase2-seeds-0-19/seed13-reallocated  062ae987fe753fe2af22cb6a209b1fb6f6ae3f7b2aebcd4809815a1c8dc6d9a4
phase3/seed7-capital  16f816f811017d2a7d9091cc2e4c52272b8939245e628a98a19156978acc5a08
seed-42  9814b3c0409a7fcf4f65cc07a09f2d2b562ad1251857dcc6d8504b85272c7f11
python -m civsim run --seed 7 --years 200 --labor reallocate --investment capital --policy31 combined-multi --out ../../work/phase31-checked-seed7
python -m civsim verify ../../work/phase31-checked-seed7
8620aec892dc28ab0d423f2701223ed654d297f50658a2b0de5aa6158cc3dc3e
```

과거 실험표 400개 행은 2차 240행과 3차 160행의 합이다. 여러 관측 연도·자료에 같은 경로가 등장하므로 서로 다른 경로는 280개다. 각 행에서 지도 해시와 해당 연도까지 누적한 원장 해시를 모두 검증했다. 기존에 저장한 1.0·2.0·3.0 예시 원장 3개는 저장 파일을 직접 읽어 재생했다.

## 투자·인구 실험

```console
python -m experiments.investment31 --seed-start 0 --seeds 20 --workers 6 --out examples/phase31/investment/dev
160 paths, 32000 annual transitions, 45.712 s
python -m experiments.investment31 --seed-start 20 --seeds 20 --workers 6 --match-design examples/phase31/investment/dev --out examples/phase31/investment/holdout
160 paths, 32000 annual transitions, 49.983 s
python -B -m experiments.stability31 --seeds 20 --baseline-years 500 --treatment-years 200 --out examples/phase31/stability
python -m experiments.long31 --out examples/phase31/long-primary.csv --workers 4
40 paired-arm trajectories, 20,000 audited world-years, 280 checkpoints
python -B -X utf8 -m experiments.decision31 --out examples/phase31/decisions/choices.csv
60 branch/no-match rows from 20 development seeds.
```

두 투자 표본의 정책 소스 SHA-256은 `4d6c30d623925ca3a70b31d8b0bc9f5dc85e1909557dcb236079dd9f404e9479`로 같았다. 조건이 충족된 20개 세계의 의사결정 분기는 실제로 유보·농업·개간 3개씩 모두 실행했다. 실험별 세계 수와 경로는 일부 겹친다.

## 독립 반복 및 처리 비용

```console
python -m experiments.investment31 --seed-start 0 --seeds 20 --workers 5 --out ../../work/phase31-final-dev
160 paths, 32000 annual transitions, 76.150 s
python -m experiments.investment31 --seed-start 20 --match-design examples/phase31/investment/dev --seeds 20 --workers 5 --out ../../work/phase31-final-holdout
160 paths, 32000 annual transitions, 75.906 s
python -B -m experiments.stability31 --seeds 20 --baseline-years 500 --treatment-years 200 --out ../../work/stability31-replay-01
python -m experiments.long31 --out ../../work/phase31-long-final.csv --workers 4
python -B -X utf8 -m experiments.decision31 --out ../../work/phase31-choice-final.csv
```

마지막 투자 재실행에는 각 설비 유형을 제거한 생산을 원장의 투입값에서 다시 계산해 신고된 편익과 대조하는 검사도 적용했다. 개발·검증 각각의 CSV 5개, 안정성 파일 8개, 500년 연장 CSV 1개, 사업 분기 CSV 1개, **총 20개 파일의 바이트가 기존 생성본과 일치**했다. 투자 `execution.json`의 실행 시간과 프로세스 수는 실행마다 달라지므로 CSV 비교 대상에서 제외했다. 500년 연장 파일 SHA-256은 `ce0c2ac1e61d4379c2908b854e392fcb40fa26ec8d9e64ab89df921ee0489bb3`이다.

```console
python -m cProfile -o ../../work/phase31-seed7.prof -m civsim run --seed 7 --years 200 --labor reallocate --investment capital --policy31 combined-multi --out ../../work/phase31-profile-7
```

프로파일러에서 총 1.657초 중 연간 전이 200회에 누적 1.323초, 그 안의 원장 감사에 0.609초, 3.1 생산에 0.499초가 걸렸다. 3.1 생산에는 투자 계획 0.298초가 포함된다. JSON 정규화·직렬화는 0.163초였다. 중첩된 누적 시간은 합산하지 않는다. 병렬 실험 실행 시간은 동시 작업량의 영향을 받았다. 더 큰 지도·국가 수에서의 3.1 처리량은 측정하지 않았다.

GitHub에서 기준 PR의 상태와 커밋을 확인했다. Context7에서 Python 3.12의 gzip 헤더 및 운영체제별 파일 게시 동작을 확인했다. Windows 제한 환경에서 하드 링크 게시가 거부된 뒤 Windows에는 기존 파일을 대체할 수 없는 이름 변경을 사용했다. POSIX에서는 같은 파일시스템의 하드 링크로 완성된 CSV를 게시한다. tldraw에는 26개 도형으로 개발·검증 표본과 반사실 구조를 기록했다. Figma 작업은 UI를 제외한 이번 범위에 포함하지 않았다. [Python gzip](https://docs.python.org/3.12/library/gzip.html) · [Python os.rename](https://docs.python.org/3.12/library/os.html#os.rename) · [tldraw 도식](https://www.tldraw.com/f/0bUzL9_Y5-sq8tpY7HMM6)
