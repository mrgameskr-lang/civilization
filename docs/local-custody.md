# 지역 재고·주민 배식·위치 명부 검산

이 변경은 PR #21의 연간 저장을 열어 재고와 인원 변동을 대조하는 부분 구현이다. 기존 이동 규칙은 `annual-unit/1`이다. 새로 제공하는 `show --custody`는 선택형 읽기 기능이다. 실행 결과로 입증한 범위는 도착지 창고 잔고, 실제 주소지 배식, 연말 위치, 주소지·행정·현재 위치 명부와 이탈 사유다.

## 직접 실행

```sh
python -m civsim.annual_game show examples/annual-unit-v1/position-saves/moved.json --custody
python -B -m experiments.region_custody_case --verify examples/location-upkeep-v1/custody-case.json
python -B -m experiments.region_custody_case --stocked-destination --verify examples/location-upkeep-v1/stocked-destination.json
python -B -m experiments.region_custody_case --shrinking-home --verify examples/location-upkeep-v1/shrinking-home.json
python -B -m unittest tests.test_regional_custody tests.test_resident_exits tests.test_region_custody_case -v
python -B -m unittest discover -v
```

`--out 새파일.json`으로 세 사례의 원자료를 각각 새 경로에 생성할 수 있다. 검산기는 동일 명령을 보류한 연간 경제도 실제로 실행한다. [실행기](../experiments/region_custody_case.py) · [회계 및 이탈 검산](../civsim/regional_custody.py)

## 창고 식량과 실제 섭취의 차이

시드 0, 2년 차에 같은 연초를 복사했다. 지역 5에서 지역 4로 1명이 이동한 경우와 이동을 보류한 경우를 비교했다.

| 실제 관측값 | 이동 | 보류 |
|---|---:|---:|
| 구호 직전 지역 5 식량 / 도구 | 2 / 8 | 3 / 8 |
| 구호 직전 지역 4 식량 / 도구 | 0 / 73 | 0 / 73 |
| 연말 도로 (4,5) 잔량 | 220 | 221 |
| 연말 및 차년 초 지역 4에 있는 주소지 5의 유닛 수 | 1 | 0 |
| 당해 국내 민간 식량 배송 | 1,293 | 1,293 |
| 당해 주민 섭취 | 64,955 | 64,955 |
| 다음 해 국내 민간 식량 배송 | 1,988 | 1,988 |
| 다음 해 주민 섭취 | 67,415 | 67,416 |

출발 창고의 차이 1은 PR #21의 편도 이동 운임이다. 지역 5의 민간 배송 직후 식량 846에 주소지 공공 배식 10이 들어갔다. 식사 직전 잔고는 856, 섭취는 846, 남은 식량은 10이었다. 공공 배식 10을 섭취 846에 다시 더하면 이중계상이다. 공공 창고에서 지출한 도구도 같은 단계의 창고 전후 잔고로 따로 확인했다. 세부 원장에는 소비 이전 재고와 사용량이 분리되어 있다. [이동·보류의 32개 지역 원장](../examples/location-upkeep-v1/custody-case.json)

같은 시드에서 지역 5에서 지역 7로 이동하는 별도 사례도 실행했다. 지역 7은 2년 차 구호 직전에 식량 1·도구 3을 보유했고, 3년 차 같은 시점에는 식량 0·도구 3을 보유했다. 해당 방문 인원은 두 해 모두 지역 7에 있었다. 이 수치는 창고 실사와 위치 등록이다. 방문 유닛에게 식량 1을 지급했다는 영수증이나 개인별 섭취 기록은 없다. [도착지 잔고와 다음 해 대조](../examples/location-upkeep-v1/stocked-destination.json)

## 세 명부와 이탈 배분

주소지 명부는 주민 수의 부분집합이다. 행정 소속은 기존 PR #19 등록 규칙으로 재생했다. 물리적 위치는 PR #21의 실제 편도 이동 영수증으로 재생했다. 같은 인원을 서로 다른 기준으로 집계하므로 이 세 표를 더하거나 동일 인물의 소속·위치 조합을 추정하면 안 된다.

- 주소지별 복무 사망자 수는 `복무 중 인원 × 실제 주민 사망 / 기초 주민 수`의 내림값이다. 주소지를 떠난 명부 인원은 사망 배분 후 남은 명부 인원과 실제 이주, 이주 전 주민 수로 같은 방식으로 계산한다. 연도별 입·퇴장 수는 명부 잔액 및 실제 주민 변동과 대조한다.
- 위치별로 해제, 등록, 이동, 사망, 이주 순서대로 기표한다. 해제·사망·이주 각각은 주소지에 있는 인원부터, 부족하면 방문 지역 번호 역순으로 배분한다. 그 결과를 독립적으로 재구성해 기존 `retained_away`, `after_move_away`, `closing_away` 세 잔액과 비교한다. 위치 장부에는 실제 이탈과 이동으로 설명되는 수량만 줄일 수 있다.
- 시드 2, 지역 7에서 지역 4로 2년 차에 1명이 이동했다. 5년 차에 주소지 7의 명부는 16명에서 15명으로 줄었다. 주소지 7에 있던 1명이 복무를 해제했고, 지역 4에 있던 1명은 유지됐다. 사망·이주로 이탈한 명부 인원은 각각 0명이었다. [5개 연도의 실측 원장](../examples/location-upkeep-v1/shrinking-home.json)

## 구현 경계

현지 식량·도구를 방문 유닛에게 새로 지급하는 거래, 그 지급으로 활동 가능 인원을 판정하는 규칙, 그 규칙이 구호와 민간 배송에 미치는 효과는 이번 결과에 포함되지 않았다. PR #21 보급량을 현지 지급량으로 간주하지 않았다. 인원 부족·식량 부족과 무관하게 추가 유지비를 부과하지 않는 기존 규칙으로 데이터를 생성했다. 따라서 이번 수치로 새 유지 정책의 효과를 평가할 수 없다.

새 지급 규칙을 켠 40시드 장기 실험은 미실행이다. 별도 호환성 검사는 기준 커밋 `a6d9e6b`에서 공개한 원장과 현재 기본 경로의 재생 결과를 대조한다. [호환성 검산 코드](../experiments/verify_annual21.py)
