# 6.0A.1 실험 자료 사전

개발 시드 0~19는 `dev/`, 규칙 동결 후 연 독립 검증 시드 20~39는 `holdout/`에 있다. 각 시드에서 같은 8개국·32개 지역의 초기 세계로 6개 경로를 시작한다. A는 기존 6.0A C(무역 협정), B는 A와 국제 식량 원조, C는 A와 수출 제한, D는 A와 출입국 제한, E는 세 수단을 모두 허용하는 기존 6.0A D다. F는 E의 각 공여국에서 원조 선적량과 실제 운임을 더한 연간 지출을 연초 예산 안에 둔다. [실험 계획](../../../docs/phase6a1-protocol.md) · [운송 및 예산 공식](../../../docs/aid-budget61.md)

| 표본별 파일 | 행을 식별하는 열 | 무엇을 읽을 수 있는가 |
|---|---|---|
| `runs.csv` | seed, arm, year | 50·100·200년의 세계 상태·누계 및 초기 세계/전 연도 원장 해시 |
| `countries.csv` | seed, arm, year, owner | 같은 시점의 국가 인구·현금·재고 및 누적 생산·식량·재정·국경·정치 |
| `regions.csv` | seed, arm, year, region | 같은 시점의 지역 인구·재고, 지역별 원조·섭취·교역 누계 |
| `paired.csv` | seed, year, contrast | 같은 시드의 B−A, C−A, D−A, E−A, F−E, 상호작용 잔차 I. 지표별 열이 각 차이의 값을 담음 |
| `means.csv` | arm, year | 시드별 지표의 산술평균. pooled_deficit_share는 시드별 부족의 합 ÷ 시드별 필요의 합 |
| `country-years.csv.gz` | seed, arm, year, owner | **그해**의 국가별 입출금·물자 거래, 예산과 승인·지출, 원조 효과, 인구·식량·정치 |
| `region-years.csv.gz` | seed, arm, year, region | **그해**의 지역 수요·섭취·부족, 창고 출고·순입고·중간비용, 공공·민간 기말재고, 집단별 구성원·지지·불만 |
| `direction-years.csv.gz` | seed, arm, year, source, target | 협정이 유효하거나 원조 요청·제안, 실제 교역·이동, 접근 제한이 있었던 국가 방향의 권한과 실적 |
| `aid-attempts.csv.gz` | seed, arm, year, donor, recipient, source, target | 승인된 원조를 각 국경에서 보낼 때 가능한 한도와 제약. source와 target은 **지역** ID. 한 방향에서 여러 국경을 시도할 수 있음 |
| `execution.json` | 표본 | 작업 수와 실제 소요시간, 과거 A/E 체크포인트 확인 수, 과학 파일 9개의 SHA-256 |

체크포인트의 같은 시드와 군에서 year=200은 1~200년 누계다. 누적 열을 50·100·200년 사이에서 다시 합산하면 기간이 겹친다. `opening_population`은 체크포인트 표에서 실험 시작, 연간 표에서 해당 연도 시작의 주민 수다. `closing_*`는 원칙적으로 해당 연말 상태다. 단 `closing_public_food_years`는 매년 말 공공 창고 식량을 더한 **재고·년**이고, `open_public_food_years`는 매년 초 같은 수치를 더한 값이다.

## 요인 효과와 단년 섭취 효과

`paired.csv`에서 I = (E−A) − [(B−A) + (C−A) + (D−A)]다. 인구와 실물량은 우선 시드 안에서 차감하고, 부족 비율도 각 경로의 누적 부족/누적 필요를 먼저 계산한 뒤 차감한다. I는 비선형적인 전 경로 반응을 포함한다. 두 수단씩만 켠 경로가 없어 특정 두 수단의 상호작용량은 정해지지 않는다.

| 지표 | 계산·해석 |
|---|---|
| `food_need`, `food_eaten`, `food_deficit` | 필요한 식량, 실제 섭취량, 둘의 차이. 부족률 `deficit_share` = 부족 ÷ 필요 |
| `aid_sent`, `aid_freight_food`, `aid_handling_food`, `aid_received` | 공여 창고 선적, 공여국이 추가 지불한 거리별 운임, 운송 중 취급손실, 수혜 창고 순입고. 공여지 같은 행의 순입고는 그 지역이 별도로 수혜자가 된 물량 |
| `relief_food` | 국내 공공창고에서 민간 재고로 실제 배급된 양. 국내 재고와 외국산 원조가 공공창고에 함께 쌓일 수 있음 |
| `direct_eaten_delta` | 그해 국제 원조 송장을 전부 유지한 실제 섭취 − 그 송장을 전부 뺀 반사실 섭취. 같은 생산·예산 승인·국경법으로 민간 교역·과세·국내 배급·운송·식사를 재실행. 원조가 없는 해는 0, 음수 가능 |
| `recipient_depot_eaten_delta` | 실제 순입고가 **양수인 지역**에 한정한 위 차이. 비입고지 효과는 전체 direct_eaten_delta − 이 값 |
| `control_eaten_delta`, `control_deficit_delta` | 같은 시드·지역·연도의 **A 경로**와 비교한 차이. 이번 해 시작 전 누적된 인구·재고·합의 변화도 포함 |
| `recipient_control_eaten_delta` | 처리군에서 실제 순입고가 있었던 지역·연도에 한정한 A 대비 섭취차. B에서 읽으면 원조만 허용한 경로의 같은 지역 비교 |
| `donor_control_deficit_delta` | **지역표**는 해당 지역에서 실제 선적한 연도의 A 대비 부족차. **국가표**는 국가 안에 실제 선적이 발생한 연도의 국가 전체 부족차. 장소·분모가 다름 |
| `donor_control_reserve_delta` | 실제 발송한 국가·연도의 기말 공공 식량 − A의 같은 국가·연도 기말 공공 식량. 누계는 재고·년 |
| `donor_control_support_delta_x_members`, `donor_control_population_years` | 실제 공여국·연도에서 구성원 가중 평균 지지의 A 대비 차이 × 현재 구성원 수, 그리고 해당 구성원 수. 두 누계의 비가 공여국 평균 지지차 |

실제 원조 식량의 개별 단위가 어느 가정에 도착했는지 표시하지 않는다. 따라서 창고 입고, 민간 배급, 당해 원조 제거 대비 추가 섭취, 장기 A 대비 섭취는 각각의 측정값으로 읽는다. 어느 것을 분자로 썼는지 밝힌 뒤 `aid_received`로 나눈다. 분모가 0인 경우 해당 비율은 정의되지 않는다.

## 공여국 예산과 실제 지출

Q는 연초 인구·부족·식량창고·집단 수요로 계산한 국가별 원조 예산이다. 한 국가가 여러 상대에 같은 Q를 표시하므로 국가·연도 단위에서 한 번만 집계한다.

| 열 | 정의 |
|---|---|
| `planned_budget` | 원조 기능이 없는 A/C/D에서도 계산할 수 있는 가상 Q. 전 국가·연도의 계획 능력을 나타냄 |
| `available_aid_budget`, `aid_policy_country_years` | 원조 권한이 있는 B/E/F에서는 Q와 1, A/C/D에서는 둘 다 0. 사용 가능 예산은 실제 공공창고 지급액과 다를 수 있음 |
| `approved_donor_budget` | 해당 국가·연도에 `aid_authorized > 0`이면 그 국가의 Q를 단 한 번 포함. 다른 국가 0 |
| `requested_food`, `aid_offered`, `aid_authorized` | 수혜국의 요청량과 공여국의 제안량·양측 수락량. `aid_unshipped` = 수락량 − 실제 선적량 |
| `actual_debit` | 실제 선적 + 실제 운임. 순입고 및 취급손실은 수송한 물량을 구성하므로 이에 두 번 더하지 않음 |
| `budget_overrun`, `overrun_donor_years` | max(0, 실지출 − Q)와 초과 국가·년 수. 실제 운임을 포함. F에서 초과 0 |
| `unspent_budget`, `approved_donor_unspent_budget` | 모든 원조 권한 국가 또는 실제 승인 국가만의 max(0, Q − 실지출) 합. 국가끼리 초과와 잔액을 상계하지 않음 |
| `budget_displaced` | 경로 처리 당시 물리적으로 실을 수 있었던 양에서 F 상한 적용 후 실제 선적한 양을 뺀 값. 뒤의 도로에서 잔량을 재시도할 수 있음 |
| `unapproved_requests`, `rejected_offers` | 실물량이 아니라 성립하지 못한 요청·제안 건수. offer_years·approved_donor_years·donor_years·recipient_years는 각각 해당 상태가 양수인 국가·년 |

`aid-attempts`의 `limit_authorized,limit_road,limit_stock,limit_storage,limit_budget`는 승인 잔량·남은 공유도로 용량·공여 창고 재고와 운임·수혜 창고 공간·선적과 운임을 함께 고려한 잔여 Q가 허용하는 최대 화물이다. 최소 출고량은 2다. 예산 한도가 적용되지 않은 경로의 `limit_budget`은 공란이다. `binding`에는 가장 작은 한도에 동률인 사유를 전부 기록한다. `shortfall_reasons`는 승인했으나 남은 화물의 말단 사유 집합이다. 마지막 잔량이 1이면 minimum_lot, 물리 경로가 없으면 no_border_route다. A/E의 과거 원장에 새 사유가 없는 경우 같은 계산을 원본 심사 수량으로 복원했다. 여러 사유에 같은 물량이 연결될 수 있다.

## 조약·국경·국내 반응

`active_pact_partners`, `new_pact_partners`, `terminated_pact_partners`는 국가별 조약 당사국·년 또는 체결/조기 종료 상대국 수다. 세계의 `agreement_years`, `agreements_started`, `agreements_terminated`는 두 상대국을 한 쌍으로 세므로 각 국가 합의 절반이다. `pact_breached_out`은 제한이 실제 수출을 막아 발생한 발신국 방향의 위반이다. 한 번 위반해도 즉시 종료되지 않을 수 있다. 조기 종료는 `pact_terminated` 사건과 기말 의무 상태를 대조했다. 방향별 새 체결·조기 종료 열은 해당 쌍의 두 방향에 같이 기록한다.

`trade_partner_years`, `migration_partner_years`는 국가가 실제 교역하거나 주민을 주고받은 서로 다른 상대국 수의 연도 합이다. 방향표의 `source,target`은 국가 ID다. 지역별 `export_*,import_*`는 실제 국제 교역이다. 거절량 `trade_denied_out,exit_denied_out,entry_denied_in`은 현금·재고·도로나 정착 여력이 있던 시도의 미허용량으로, 다른 경로로 갈 수 있다.

지역표에서 농업·산업·소비 집단별 `*_members, *_support, *_discontent`는 그해 실제 구성원 수와 0~1000 점수다. `*_direct`는 원조 송장이 해당 지역에 준 직접 지지점 변화이고 `*_direct_x_members`는 그 변화에 해당 집단 구성원 수를 곱한 값이다. 국가표 `aid_*_positive/negative/zero`는 원조 선적 또는 입고가 있었던 지역에서 구성원이 있는 각 집단이 어떤 부호를 보였는지 센다. 공여와 수혜가 동시에 있었던 국가·지역은 각각의 조건별 분석에 포함될 수 있다.

## 재현

두 표본은 같은 명령에서 `--sample dev` 또는 `--sample holdout`을 선택한다. `--verify-against`는 새 경로에서 같은 세계를 전부 재생해 결과 파일을 원본과 실제 바이트로 비교한다. 소요시간 등 실행 메타데이터는 따로 보존한다. `years_sha256`은 첫해부터 표시 연도까지 전체 연간 원장 JSONL의 누적 SHA-256이다. A/E의 기초와 연간 해시는 보관한 6.0A C/D 원장과 대조한다.

```sh
python -B -m experiments.phase6a1 --sample dev --workers 5 --out examples/phase6a1/study/dev
python -B -m experiments.phase6a1 --sample holdout --workers 5 --out examples/phase6a1/study/holdout
python -B -m experiments.phase6a1 --sample dev --workers 5 --out ../../work/phase6a1-repeat-dev --verify-against examples/phase6a1/study/dev
python -B -m experiments.phase6a1 --sample holdout --workers 5 --out ../../work/phase6a1-repeat-holdout --verify-against examples/phase6a1/study/holdout
```
