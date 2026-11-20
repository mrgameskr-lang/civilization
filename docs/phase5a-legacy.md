# 5.0A 작업 트리에서 과거 엔진 재검증

4.0의 시드 0~19, 정책 4개, 200년 실행을 5.0A 작업 트리에서 다시 계산했다. 80개 경로·16,000회 연간 전이에 대해 50·200년 결과를 비교했다. [PR #7의 기준 결과](../examples/phase4/study)와 실험 CSV 다섯 개 및 사례 JSON의 바이트가 모두 같았다. 4.0 이전 저장 원장의 별도 재생과 3.1 소스 대조도 실시했다.

## 실제 실행한 명령

저장소 루트, Windows CPython 3.12.14에서 새 결과 디렉터리를 사용했다.

```sh
python -B -m experiments.verify_archives31 --workers 3
python -B -m experiments.phase4 --seeds 20 --workers 4 --horizons 50,200 --out ../../work/phase5a-legacy4
```

첫 명령은 벽시계 28.493초가 걸렸다. 구형 1.0~3.0 정책 280개 시드·규칙 경로를 재생했고, 저장 체크포인트 400개의 초기 세계 해시와 누적 연간 원장 해시가 각각 일치했다. 추가로 전체 원장이 저장된 다음 실행을 읽고 재계산한 SHA-256을 확인했다.

| 저장 실행 | 연간 원장 SHA-256 |
|---|---|
| seed-42 (1.0) | `9814b3c0409a7fcf4f65cc07a09f2d2b562ad1251857dcc6d8504b85272c7f11` |
| seed13-reallocated (2.0) | `062ae987fe753fe2af22cb6a209b1fb6f6ae3f7b2aebcd4809815a1c8dc6d9a4` |
| seed7-capital (3.0) | `16f816f811017d2a7d9091cc2e4c52272b8939245e628a98a19156978acc5a08` |
| seed7-two-years (4.0) | `cb5600c4af37f4a580eec64cf0cace1c0697b695b52cf526fc7d2c5665a005b4` |

두 번째 명령은 벽시계 157.063초가 걸렸다. 160개 체크포인트에서 `initial_national_sha256`, `initial_regional_sha256`, `years_sha256` 총 480개 필드를 대조하고, 아래 파일의 전체 바이트도 비교했다.

| 파일 | 행 수 | 5.0A에서 재생한 파일의 SHA-256 |
|---|---:|---|
| runs.csv | 160 | `b9ee03de830bafde63b336f27a3b23050eadb765b00ddd52caea8024916cfebd` |
| paired.csv | 120 | `b328ffacf04074d28c6250f535eaa7f3a09ebc2c8280866c07dd4b0dec607f9b` |
| means.csv | 8 | `68e192773cfa1c8f153337e6ce6e9fa8bcfd6367f00c384f64a5d7f77414222a` |
| regions.csv | 5,120 | `91364c8f6b4104e8f75b5106b2bb2fde5c6105033de06af9a502a4c97ef15554` |
| roads.csv | 5,072 | `6c5d8ffa1e1f036cd86cae5b9f4d051c246cb0ae4e2547b941d2b9c845a13de9` |
| cases.json | 사례 JSON | `48480ff96a7bba82d29efa2161140902dd39170b23c126e8f6576ed0ce842ce4` |

`execution.json`의 전체 키를 비교했다. 기준과 달라진 값은 작업자 수(8→4)와 벽시계 시간(116.500→157.063초)이다. 여러 작업이 같은 호스트를 공유한 상태여서 이 시간 차이로 엔진의 성능 변화를 추정하지 않았다.

## 3.1 검증 범위

5.0A 작업 트리의 다음 파일을 [PR #7 기준 커밋](https://github.com/mrgameskr-lang/civilization/commit/37935d78954b5c11de697257a8d38a4cb7a1d3c9)의 Git 원본 바이트와 각각 비교했다. 9개 모두 일치했다.

- `civsim/model.py`, `civsim/rules.py`, `civsim/engine.py`, `civsim/economy.py`
- `civsim/investment.py`, `civsim/investment31.py`, `civsim/demography.py`, `civsim/audit.py`
- `experiments/investment31.py`

3.1 개발·검증 40개 시드, 8개 정책의 1,280개 체크포인트 전체 재생은 이전 4B 검증에서 수행했다. 이번 5.0A 검증은 해당 3.1 계산 소스의 동일성을 확인했다. 3.1 전체 실험을 이번에 다시 실행한 횟수는 0회다.
