# 두 지역 턴제 게임의 유닛 이동

시드 0에서 유닛 1명이 A에서 B로 이동했다. 이동 직후 저장한 파일을 다른 Python 프로세스에서 열고 다음 턴으로 진행한 뒤에도 그 유닛은 B에 있었다. 지역 A는 `0`, B는 `1`이다. [시작 저장](../examples/unit-board-checks/start.json) · [이동 직후](../examples/unit-board-checks/moved.json) · [다음 턴](../examples/unit-board-checks/turn-2.json)

## 직접 실행

저장소 루트에서 Python 3.11 또는 3.12로 실행한다. 출력 파일 이름에는 새 경로를 사용한다. `show`로 저장된 주민·명부·현재 위치·양쪽 창고·도로 잔량을 읽을 수 있다.

```shell
python -m civsim.unit_game new --seed 0 --out turn1.json
python -m civsim.unit_game move turn1.json --home 0 --affiliation 1 --from 0 --to 1 --count 1 --out arrived.json
python -m civsim.unit_game next arrived.json --out turn2.json
python -m civsim.unit_game show turn2.json
```

게임은 초기 주민 A 12명·B 10명 가운데 이미 역할 명부에 기재된 5명을 유닛으로 배정한다. 각 그룹의 키는 (주소지, 행정 소속지)다. 모든 유닛은 처음에 주소지에 서 있다. 이동은 그룹의 **현재 위치**와 출발지 창고, 공용 도로 잔량을 함께 바꾼다. 주소지별 일반 작업 가능 인원은 주민 수에서 그 주소지의 명부 인원을 한 번 뺀 A 9명·B 8명이다. 이 보드에는 생산량을 산출하는 연간 생산 단계가 없다. [시나리오](../civsim/unit_board_scenario.py)

## 이동 한 건의 회계

플레이어가 선택한 그룹에서 `q`명이 한 칸 건넌다. 출발지 현재 인원·출발지 식량·도로 잔량이 각각 `q` 이상일 때만 실행한다. 식량과 도로는 모두 게임 단위로 1인당 1씩 소모하며 양방향 이동은 같은 도로 잔량을 쓴다. 실패하면 세 상태와 영수증 목록을 그대로 둔다. 다음 턴에는 도로 용량만 갱신한다. 명시적인 역방향 이동 명령을 내리기 전까지 도착지의 유닛은 귀환하지 않는다. [상태와 이동 코드](../civsim/unit_board.py)

| 시드 0에서 관측한 값 | 이동 전 | 1명 이동 후 | 저장을 불러온 다음 턴 |
|---|---:|---:|---:|
| 선택한 그룹 (주소 A, 소속 B) 중 A에 있는 인원 | 2 | 1 | 1 |
| 같은 그룹 중 B에 있는 인원 | 0 | 1 | 1 |
| 지역 내 전체 유닛 A / B | 3 / 2 | 2 / 3 | 2 / 3 |
| 공공창고 식량 A / B | 2 / 2 | 1 / 2 | 1 / 2 |
| 도로 잔량 | 2 | 1 | 2 |
| 주소지별 주민 수 A / B | 12 / 10 | 12 / 10 | 12 / 10 |

별도로 같은 1명 이동 명령을 도로 잔량 0·출발 식량 2에서 실행해 `insufficient_capacity`를 받았다. 도로 잔량 2·출발 식량 0에서는 `insufficient_food`를 받았다. 두 경우 모두 도로·식량 차감은 0이고 실패 전후 보드의 SHA-256이 같았다. 명령줄은 종료 코드 1을 반환했고 후속 저장 파일을 만들지 않았다. [입력·출력·실패 전후 해시](../examples/unit-board-checks/one-token-results.json)

## 저장과 재현

`unit-board/1` 저장에는 초기 주민·명부·창고·도로, 성공한 이동의 턴과 인원, 현재 위치·잔량이 담긴다. 불러올 때 초기 상태에서 이동을 재생하고 모든 현재 값을 대조한다. 게임이 검산하는 대상은 저장 파일의 내부 일관성이다. 원본 슬롯을 보존하므로 같은 출발 상태에서 이동과 보류를 각각 실행할 수 있다. [저장·실행 진입점](../civsim/unit_game.py)

짧은 성공·실패·새 프로세스 복원 시험을 먼저 통과시킨 뒤, 초기 식량 배치가 다른 게임 시드 0~39에서 각 200턴을 실행했다. 시드마다 1턴에 1명을 옮기는 경우와 같은 턴에 보류하는 경우를 비교했다. 이동을 선택한 40개 게임 모두 1턴에 성공했고 200턴에도 해당 1명이 도착지에 남아 있었다. 보류한 40개 게임에서 그 그룹이 도착지에 둔 인원은 0명이다. 각 게임의 50·100·200턴을 기록한 결과는 총 240행이다. 독립 반복에서는 원자료 네 파일이 바이트 단위로 일치했다. [턴별 결과 요약](../examples/unit-board-v1/summary.json) · [시드별 원자료](../examples/unit-board-v1/seeds.csv) · [독립 반복](../examples/unit-board-v1/replay.json)

```shell
python -m unittest tests.test_unit_board_trials -v
python -m experiments.unit_board_trials --out first-run
python -m experiments.unit_board_trials --out repeat-run --verify-against first-run
python -m unittest discover -v
```

기준 커밋 `a78c0a9`에서 기존 테스트 432개가 130.381초에 통과했다. 변경 후 같은 명령으로 기존 432개와 신규 22개를 포함한 전체 454개가 132.363초에 통과했다. [기준 테스트 로그](../examples/unit-board-checks/baseline-tests.txt) · [전체 테스트 로그](../examples/unit-board-checks/full-tests.txt)

## PR #19와의 경계

이번 제출은 요청에서 허용한 **독립적인 2개 지역·1개 도로 모델**이다. 초기 주민·명부·도로·창고 모두 이 게임의 저장 상태다. PR #19의 실제 연간 실행에서 명부나 재화를 가져오거나 그 경제로 결과를 되쓰는 기능은 미구현이다. 위 200턴 수치는 이 보드에서의 위치 지속성 검사다.

PR #19의 `posting_engine65.run`은 연간 경제를 닫은 뒤 명목 근무지를 붙인다. 이 시점에는 민간 운송·구호·창고 결산과 주민 소비가 이미 끝났다. 기존 유상 왕복 근무 단계와 감사기는 한 사람당 왕복 도로 사용량 2를 전제로 하고, 다음 해에 넘기는 기존 복무 명부는 주소지별 합계다. 이 경로에 사후 편도 영수증만 추가하면 실물 차감의 시점과 현재 위치의 연속성을 보장할 수 없다. 이 때문에 두 경로의 회계를 서로 합산하지 않았다. 기존 경제의 생산·주민 식사에 대한 이동 효과는 이번 보드에서 미측정이다.
