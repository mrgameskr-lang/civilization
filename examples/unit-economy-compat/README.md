# PR 20 기준 경로의 호환성 검증

비교 기준은 Git 커밋 `b0490cdd8c987342258f992f4234f3c8a3330614`다. 이전에 공개한 재생 명령으로 기존 연간 원장과 독립 두 칸 게임을 새 디렉터리에서 각각 만들었다. 두 계산은 상태나 데이터를 주고받지 않는다. [기존 게임 사용 설명](../../docs/unit-board.md)

## 독립 게임

시드 0의 기존 CLI로 새 게임, 첫 행동, 저장 파일에서 다음 턴 진행을 각각 새 Python 프로세스에서 실행했다. 그 결과 파일 세 개를 지정 커밋에 기록된 Git blob과 대조했다. 이어서 종전 게임 실험의 40개 시드·200턴 이동/보류 두 경로를 실행하고 네 과학 파일 및 별도 기본 한도 0 사례를 대조했다. 8개 파일 모두 전체 바이트가 같았다. 보드 코드 수정 후 같은 명령을 다시 실행했고 두 번째 검사에서도 8개 파일과 단기 테스트 6개가 모두 통과했다. 두 번째 확인서에는 실행 중 변동이 없었음을 확인한 보드 관련 소스 4개의 해시도 담았다. 게임 시드의 16,000개 상태는 경제 시뮬레이션 연도에 포함되지 않는다. [첫 파일별 검산](pr20-demo.json) · [소스 해시를 포함한 두 번째 검산](pr20-final.json)

## 기존 연간 원장

기존 공개 진입점 두 개에서 각각 시드 0~39를 200년까지 실행했다. 두 경로의 50·100·200년 누적 원장 해시 **600개 모두** 기준 커밋과 일치했다. 비교 대상은 각 경로의 공개 원장과 해시이며 새 기능을 켠 경로의 효과는 별도로 평가해야 한다. [통합 검산](annual-comparison.json)

| 이전 경로 | 실제 재생 세계연도 | 시드·시점 | 비교한 원장 해시 | 실행시간 |
|---|---:|---:|---:|---:|
| A, 경제·협의·약속 | 8,000 | 120 | 360/360 | 373.934초 |
| B, 고정 경제·행정 소속 명부 | 8,000 | 120 | 240/240 | 388.194초 |

두 영수증의 시드·시점 행 전체를 기준 커밋의 같은 파일과 대조했다. 실행시간과 작업자 수 이외의 영수증 필드도 모두 일치했다. 실제 작업자는 두 경로 각각 4개였으며 A의 원래 영수증 형식에는 이 수가 없어 검산 JSON에서는 `null`이다. [A의 시드별 해시](legacy-a.json) · [B의 시드별 해시](legacy-b.json)

## 재현 명령

저장소 루트에서 실행한다. 기존 결과를 보존하도록 출력에는 새 경로를 지정한다. `fresh-compat` 디렉터리는 첫 명령이 생성한다. 지정 커밋의 Git 객체를 로컬에서 읽을 수 있어야 한다. GitHub 접속은 필요하지 않다.

```text
python -B -X utf8 examples/unit-economy-compat/check.py games --out fresh-compat/pr20-final.json
python -B -X utf8 -m experiments.posting_replay65 --workers 4 --out fresh-compat/legacy-a.json
python -B -X utf8 -m experiments.repeat_posting_register65 compute --workers 4 --out fresh-compat/raw-b.json
python -B -X utf8 -m experiments.repeat_posting_register65 compare --scratch fresh-compat/raw-b.json --study examples/phase6c1-m1 --out fresh-compat/legacy-b.json
python -B -X utf8 examples/unit-economy-compat/check.py annual --receipts fresh-compat --out fresh-compat/annual-comparison.json
```

발표본의 `legacy-b.json` 생성 과정에서는 `raw-b.json`에 해당하는 중간 파일만 임시 디렉터리에 보관했다. 두 연간 계산을 다른 프로세스 풀에서 병행했으며 풀마다 작업자 4개를 사용했다. 과학 내용은 기준 Git blob과 직접 비교하며 실행시간과 작업자 수는 실행별 메타데이터로 본다. [검산 코드](check.py)

## 선택 인자 추가 후의 기본 경로 재검사

공개된 A·B 재생 명령의 기본 경제 경로를 다시 실행한다. 실행 시작 시 관련 소스 파일 8개의 SHA-256을 기록하고, 각 시드의 경로를 실행하기 전후에 같은 파일인지 확인한다. 과거 영수증은 위의 기준 커밋에서 직접 읽는다. 시드 0과 20의 두 경로를 먼저 검사한 뒤 나머지 38개 시드로 확장한다. 전체 영수증에는 첫 두 시드의 이번 재생 결과도 포함한다. 단일 프로세스 풀에서 작업자를 최대 4개만 사용한다. [검사 코드](check_final.py) · [실행 시작 시 입력과 소스 해시](final-off-sources.json)

시드 0과 20에서 **30/30개 해시**가 49.342초 만에 일치했다. 전체 40개 시드에서는 **600/600개 해시**가 일치했다. 각 경로가 8,000세계연도를 재생했고, 두 경로를 합친 경과시간은 첫 표본을 포함해 652.074초였다. A에서 경제·협의·약속 360개, B에서 경제·행정 명부 240개를 확인했다. [시드 0·20 검산](final-off-sample.json) · [전체 40개 시드 검산](final-off-all.json)

```text
python -B -X utf8 examples/unit-economy-compat/check_final.py --workers 4 --out fresh-compat/final
```
