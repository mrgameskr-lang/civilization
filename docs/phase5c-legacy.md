# 5.0C에서 확인한 과거 원장 호환성

PR #9 기준 커밋은 `b7c2aaacbb6d95f6788b398b4152056bf8b7325f`이다. `phase5c/representative-competition`의 저장소 루트에서 CPython 3.12.14로 아래 두 검사를 실행했다. 과거 저장 파일에 쓰지 않고 현재 엔진으로 연도를 진행해 보관된 SHA-256과 대조했다. 경과 시간에는 같은 호스트에서 동시 실행 중이던 다른 실험의 부하가 포함된다.

```sh
python -B -m experiments.verify_legacy5c --workers 4
python -B -m experiments.verify_archives31 --workers 3
```

## 5.0B 정치 관측 대조군

첫 번째 명령은 종료 코드 0, 경과 시간 448.923초로 `120 archived 5.0B feedback-off checkpoints matched`를 출력했다. 개발 시드 0~19와 검증 시드 20~39의 기존 5.0B 엔진을 정치 반영 비활성으로 각 200년간 실제 실행했다. 총 40경로·8,000세계연도다. 각 시드의 50·100·200년마다 초기 정치·경제 스냅숏, 해당 시점까지 전체 정치·경제 연간 원장, 정치 항목을 제외한 재정·경제 연간 원장의 SHA-256 세 개가 보관 행과 일치했다. [재생 코드](../experiments/verify_legacy5c.py) · [개발 보관표](../examples/phase5b/study/dev/runs.csv) · [검증 보관표](../examples/phase5b/study/holdout/runs.csv)

## 국가 엔진과 전체 원장 저장 예제

두 번째 명령의 종료 코드는 0이고 경과 시간은 85.792초였다. [검사 코드](../experiments/verify_archives31.py)는 2·3단계 보관 표의 400개 행에 사용된 280개 고유 시드·규칙 경로를 각각 최장 체크포인트까지 진행했다. 모든 행의 기초 세계와 해당 연도까지의 누적 연간 원장 SHA-256이 일치했다. 같은 명령은 3.1 실험 디렉터리를 제외한 다음 일곱 개 저장 예제의 초기 파일과 전체 연간 원장도 재생했다.

| 저장 예제 | 재생된 전체 연간 원장 SHA-256 |
|---|---|
| [1.0, 시드 42](../examples/seed-42) | `9814b3c0409a7fcf4f65cc07a09f2d2b562ad1251857dcc6d8504b85272c7f11` |
| [2.0, 시드 13](../examples/phase2-seeds-0-19/seed13-reallocated) | `062ae987fe753fe2af22cb6a209b1fb6f6ae3f7b2aebcd4809815a1c8dc6d9a4` |
| [3.0, 시드 7](../examples/phase3/seed7-capital) | `16f816f811017d2a7d9091cc2e4c52272b8939245e628a98a19156978acc5a08` |
| [4.0, 시드 7](../examples/phase4/seed7-two-years) | `cb5600c4af37f4a580eec64cf0cace1c0697b695b52cf526fc7d2c5665a005b4` |
| [5.0A, 시드 7](../examples/phase5/seed7-integrated) | `ea91ffa3f442b2c73ff6d1daf01bc05f75d5eea374410deb1855a7e9133c5293` |
| [5.0B, 시드 0](../examples/phase5b/seed0-feedback) | `d4784560f71c020b6aeafbe482af64315fb8976325c5470ba0d4bd62dbe96b52` |
| [현재 5.0C 예제, 시드 0](../examples/phase5c/seed0-elections) | `cd14aa60b4cd37f867de29c9eb86fc13c8d3360fb0d97465349bcd0b1145c664` |

## PR #9의 기존 예제 119개

PR #9 당시 `examples/`에 추적되던 경로만 열거해 비교했다. 비교 당시 HEAD는 `38612aa932e686846264b61ff6bdc9948e4412ef`였다. 기존 119개 경로가 모두 존재하고, 파일별 Git blob ID가 기준 커밋과 현재 HEAD, 작업 트리를 Git 필터로 읽은 값에서 각각 일치했다. 경로를 정렬해 `UTF-8 경로 + NUL + ASCII blob ID + LF`를 연결한 SHA-256은 `1622fd32b66f3b7756933f8cc697b82e441e57f82dd45bb81ffba558172cf99d`이다. 아래 PowerShell 비교는 파일 수 119, 두 종료 코드 0을 반환했다.

```powershell
$archivedExamples = @(git ls-tree -r --name-only b7c2aaa -- examples)
$archivedExamples.Count
git diff --quiet b7c2aaa HEAD -- $archivedExamples
$LASTEXITCODE
git diff --quiet b7c2aaa -- $archivedExamples
$LASTEXITCODE
```

Git 필터를 거치지 않은 Windows 작업 파일도 별도로 읽었다. 112개는 기준 blob의 바이트와 직접 일치했고, 나머지 JSON 7개는 저장소의 LF가 체크아웃에서 CRLF로 표현됐다. 양쪽의 줄바꿈만 LF로 통일했을 때 119개 모두 일치했다. 7개는 `examples/benchmark.json`, `examples/summary.json`, 3.1 투자 실험의 개발·검증 `execution.json`, 3.1 안정성 `manifest.json`, 4.0 연구의 `cases.json`과 `execution.json`이다.

## 재계산 범위

이 검증에서 3.1의 투자·토양·장기 진단 전체 행렬, 4.0의 전체 물류 행렬, 5.0A의 4개 재정 정책 전체 행렬은 재계산하지 않았다. 이들 보관 파일은 Git 기준으로 대조했고 위에 명시한 개별 예제는 별도로 실제 재생했다. 5.0B 정치 반영 활성군의 독립 실험 명령으로 두 표본 전체를 반복하는 작업 역시 여기서 실행하지 않았다. 현재 5.0C A군의 5.0B 활성군 대조 결과는 5.0C 본 실험에서 별도로 확인할 수 있다.
