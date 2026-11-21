# 주민 구호와 현지 게임 유닛 유지비의 집행 순서

기준 커밋은 `6db12f8`(PR #23)이다. 40개 기준 파일에서 같은 이동 명령을 내린 기존 지급 경로의 누적 지급은 50년 1,850세트, 100년 1,877세트, 200년 1,880세트였다. 유닛이 자리를 옮기는 규칙과 한 세트의 비용(현지 창고 식량 1 + 도구 1)은 세 경로에서 같다.

## 비교 대상과 해석

| 경로 이름 | 이동 및 유지비 선택 | 구호와 지급 순서 |
|---|---|---|
| `move_off` | 이동만, 유지비 선택 끔 | 기존 구호 |
| `move_on` (A) | 최대 2개 표시, 기존 `annual-unit-upkeep/1` | 이동 → 지급 → 국내 구호 → 민간 배송 |
| `relief_first` (B) | 같은 표시, 선택형 `annual-unit-upkeep/2` | 이동 → 국내 구호 → 지급 → 민간 배송 |

모두 같은 생성 세계의 1년 차를 복사한다. 2년 차에 주소지 5의 두 유닛에 대해 5→7 명령을 한 번 내린다. 거부된 명령도 표본에 남긴다. B는 국내 구호의 기존 승인·예산·도로·운임을 그대로 집행한 뒤 **그 결과로 남은 각 창고**에서 지급한다. 새 순서는 처음 활성화할 때 선택해 저장한다. 이전 연도의 실제 기말 위치와 표시 인원만 이월한다. 그룹에 지급한 식량은 게임 유지비 계정에 기표되고 주민 섭취는 기존 민간 식사 원장에서 측정한다. 식량세는 현물이며 금전 예산은 도입하지 않았다.

한 지역·턴에서 표시 인원이 `n`, 지급 직전 식량과 도구가 `F,T`일 때 `f=min(n,F), t=min(n,T)`로 둔다. 완성 세트를 먼저 만드는 실제 결제 규칙에 맞춰 다음 네 정수의 합이 항상 `n`인지 검사한다.

| 수량 | 식 |
|---|---:|
| 실제 지급 | min(f,t) |
| 식량만 부족 | max(0,t−f) |
| 도구만 부족 | max(0,f−t) |
| 두 품목 모두 부족 | n−max(f,t) |

가령 2개 요청에 식량 1과 도구 1이면 1개 지급하고 나머지 1개는 두 품목 모두 부족하다. `move_off`에서는 플레이어가 표시한 수와 결제 요청이 0이다. 이동 명부는 보존된다.

## 원자료 읽기

[40개 시드의 체크포인트와 지역 원장](../examples/relief-priority-v1/study)에 시드별 JSON과 경로별 gzip JSONL을 저장한다. 각 압축 파일 첫 줄은 열 이름, 다음 한 줄은 한 연도의 32개 지역이다. 시드·경로·연도·지역으로 찾을 수 있다. 지역 0개 표시와 미관측값을 구분한다. 200년 말 이후의 연초·지급 직전 재고는 `null`이다. 차기 자료는 두 턴이 모두 끝난 뒤 비교 파일에만 붙인다.

- `marked, paid, missing_food_only, missing_tools_only, missing_both`는 요청 수와 지급 근거다. `before_*, after_*`는 실제 지급 시점 잔액, `depot_open_*, depot_close_*, next_depot_open_*`는 연간 경계, `next_before_*`는 다음 해 같은 처리 시점의 잔액이다. 끔 경로의 무지급 관측 경계는 이동 직후·구호 직전이다.
- 현물세 총징수와 순입고, 국내 창고 간 발송·입고·운임, 사업 재료·운임, 국제 원조 발송·입고·운임·취급손실, 구호의 창고 출고·가구 입고, 기존 public 배식과 도구 지출, 편도 이동비, 부패를 각각 보존한다. 취급손실은 원조 총발송에 이미 포함된다. [각 열이 읽은 원장 경로](../experiments/priority_evidence.py)
- [진단 코드](../experiments/checkout_diagnosis.py)는 결제 시점 증거를 시드 체크포인트와 다시 맞춘다. 지역의 기초 식량 + 순세수 + 국내 공공 입고 + 원조 입고를 그해 지출 전 가용 식량의 상한으로 쓴다. 이 상한도 요청에 미달했다면 그해 해당 창고의 기존 지출 순서만 바꾸어 채울 수 없는 수량을 분리할 수 있다.
- 기존 사업·원조·배식의 실제 영수증을 하나씩 되더한 민감도는 다른 거래를 고정한 산술 검산이다. 각 수치는 중첩될 수 있다. 사업 취소나 원조 중단이 경제 전체에 미치는 인과 효과는 여기서 추정하지 않는다. 같은 연초 구호 순서 대조만 실제로 재집행했다.

## 작은 실제 세계

| 시드 0, A → B | 실제 지급 | 국내 구호 식량 | 민간 식량 배송 | 주민 섭취 |
|---|---:|---:|---:|---:|
| 2년 차 지역 5→7, 유닛 1개 | 1 → 1 | 0 → 0 | 1,293 → 1,293 | 64,955 → 64,955 |
| 같은 이동, 유닛 2개 | 1 → 1 | 0 → 0 | 1,293 → 1,293 | 64,955 → 64,955 |
| 7년 차 지역 5, 유닛 2개 | 2 → 0 | 16 → 18 | 1,092 → 1,090 | 76,219 → 76,219 |
| 10년 차 지역 3, 유닛 2개 | 0 → 0 | 0 → 0 | 1,347 → 1,347 | 79,048 → 79,048 |

2년 차 목적지 창고는 식량 1·도구 3이었다. 다음 해에도 유닛 2개가 남았고 식량이 없어 새 지급은 0이었다. 7년 차에는 같은 연초의 식량 5·도구 28에서 구호를 먼저 집행하자 지급 직전 식량이 0이 됐다. 끔 경로의 국내 구호 역시 18이었다. 10년 차에는 식량 22가 남고 도구가 0이어서 순서로 지급을 바꿀 수 없었다. [단년 4개 사례의 세 경로·지역 원장·다음 턴](../examples/relief-priority-v1/case.json)

## 재현 명령

기존 저장에서 새 순서를 쓰려면 첫 지급 선택에 `--relief-first`를 붙인다. 1년 차까지 진행한 저장을 사용한 예다.

```sh
python -m civsim.annual_game step year1.json --move 5 5 7 2 --upkeep 5 2 --relief-first --out year2.json
python -m civsim.annual_game step year2.json --out year3.json
```

저장소 루트에서 실행한 주요 명령은 다음과 같다. 다시 실행할 때는 기존 출력 파일을 보존하도록 새 출력 경로를 지정한다.

```sh
python -B -m experiments.priority_case --out examples/relief-priority-v1/case.json
python -B -m experiments.priority_study --workers 8 --out examples/relief-priority-v1/study
python -B -m experiments.repeat_priority examples/relief-priority-v1 --workers 5 --out examples/relief-priority-v1/repeat.json
python -B -m experiments.verify_priority_archive --study examples/relief-priority-v1/study --out examples/relief-priority-v1/compat.json
python -B -m experiments.checkout_diagnosis --study examples/relief-priority-v1/study --out examples/relief-priority-v1/diagnosis.json
python -B -m experiments.priority_civil_summary --study examples/relief-priority-v1/study --out examples/relief-priority-v1/civil-summary.json
python -B -m unittest discover -v
```
