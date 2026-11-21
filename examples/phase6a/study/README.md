# 6.0A 외교 실험 자료 사전

시드 0~19는 개발 표본, 20~39는 규칙을 고정한 뒤 실행한 검증 표본이다. 연도 50·100·200은 각 시드에서 200년간 이어진 같은 경로의 체크포인트다. 각 군의 첫 연초 세계는 같다. A는 5.0D 집단행동 활성군, B는 여기에 외교 관찰, C는 조약, D는 추가로 원조와 국경 제한을 허용한다. 한 연도에 실제 실행된 효과는 거주 지역 사이의 거래·이동·창고 송장에서 읽을 수 있다. [실험 계획](../../../docs/phase6a-protocol.md) · [정량 결과](../../../docs/phase6a-results.md)

| 각 표본의 파일 | 행 기준 | 용도 |
|---|---|---|
| `runs.csv` | 시드·군·체크포인트 | 세계 누계, 시점 상태, 초기 및 연속 연도 원장 SHA-256 |
| `paired.csv` | 시드·체크포인트·비교 | 같은 시드의 B−A, C−B, D−C, D−B 차이. 양수는 앞 군의 값이 큼 |
| `means.csv` | 군·체크포인트 | 시드 20개의 단순 평균. `pooled_deficit_share`는 부족 합계 ÷ 필요 합계 |
| `countries.csv` | 시드·군·체크포인트·국가 | 국가별 누적 세수·생산·무역·이동, 시점 재고와 인구 |
| `country-years.csv.gz` | 시드·군·연도·국가 | 바로 그해의 물량과 태도, 연초·연말 상태, 직전 국가 부족률 및 집권 세력 |
| `pairs.csv` | 시드·군·체크포인트·국가 쌍 | 28쌍의 사건 및 방향별 누적 흐름, 체크포인트 시점의 정책·관계 |
| `pair-years.csv.gz` | 시드·군·연도·국가 쌍 | 연초 방향별 교섭·제한, 이행 결과와 그해 말 관계. 접경하지 않은 쌍도 포함 |
| `borders.csv.gz` | 시드·군·체크포인트·출발 지역·도착 지역 | 해당 실물 도로 방향의 누적 상업 화물·원조·주민 이동·심사 거절 |
| `events.csv.gz` | 시드·군·연도·외교 사건 | 실제 사건. 한 국가 쌍에 한 해 여러 행 또는 0행이 가능. `details_json`은 원본 사건을 보존 |
| `execution.json` | 표본 1개 | 작업 수, 경과 시간, 5.0D 확인 수 및 과학 자료 9개 각각의 바이트 해시 |

`dev/`와 `holdout/`은 같은 스키마다. `replay-dev.json`, `replay-holdout.json`은 별도 프로세스가 새 디렉터리에서 같은 연도를 전부 재실행해 작성한 영수증이다. 실행 시각과 부하가 다르므로 성능 메타데이터는 과학 자료 해시에 포함하지 않는다.

## 시간을 해석하는 방법

| 열 | 단위와 시점 |
|---|---|
| `opening_population`, `opening_cash` | 연간표면 해당 연초, 체크포인트 표면 첫 연도 시작값 |
| `closing_population`, `closing_cash`, `closing_private_*`, `closing_public_*` | 해당 연도 말 주민·민간 현금·민간 재고·정부 창고. 정부는 현물로 세금을 받는다 |
| `food_need`, `food_eaten`, `food_deficit` | 필요한 배급량, 실제 섭취, 미충족 차이. 1인·1년 필요량은 식량 1단위 |
| `within_country_disparity` | 지역별 배급 충족률과 그해 자국 충족률의 절대 차이를 해당 지역 식량 수요로 가중. `within_country_ration_gap`은 이를 나누기 전의 합 |
| `produced_*`, `used_*`, `meal_used_*` | 당해 산출, 생산 시스템에서 쓴 투입, 식사와 사적 보관 손실에 사용한 수량. 체크포인트 표는 누적 |
| `import_*`, `export_*`, `import_value`, `export_value` | 민간 실물 교역량과 지급한/수취한 현금. 원조는 별도. 세계 총 교역액에는 수출액 한쪽만 사용 |
| `trade_partner_years`, `migration_partner_years` | 국가 내에서 실제 교역 또는 국제 이주를 주고받은 서로 다른 상대국 수. 체크포인트는 이 연간 수들의 누계 |
| `immigrants`, `emigrants`, `border_migrants` | 국가 간 실제 이동 인원. 한 건의 이동이 수신국 입국과 발신국 출국에 각각 기록됨. 세계 국제 이동 건수를 계산할 때는 한쪽만 사용 |
| `active_group_years`, `participants`, `withheld_workers`, `turnovers`, `policy_changes` | 동원된 집단·년, 참여 인년, 실제 철회 노동 인년, 현직 세력 교체, 국내 집단행동 대응에서 변경된 예산 결정 수 |
| `mean_support`, `mean_discontent` | 0~1000 점수의 구성원·연도 가중 평균. `member_years`가 분모 |
| `aid_exposed_region_years`, `aid_{farm,industry,consumer}_{positive,zero,negative}` | 실제 원조 출고·입고 지역·년과 그곳에서 구성원이 있는 각 집단의 **직접 지지효과** 부호별 관측 수. 변화량 가중합은 `delta_x_members`, 분모는 같은 집단 `members` |

## 쌍과 물리 국경

국가 ID `a < b`인 한 쌍에서 `ab_`는 a→b, `ba_`는 b→a 방향이다. 방향별 `import_dependence`는 출발국 전체 수입액 중 상대국에서 들여온 금액 비율, `export_exposure`는 출발국 전체 수출액 중 상대국으로 나간 비율이다. `food_import_share`는 출발국의 직전 식량 수요 중 상대국에서 수입한 식량 비율이다. 세 값은 모두 연초에 이미 관측된 직전 흐름의 천분율이다. `pact_score`·`pact_willing`은 연초 순가치와 체결 의사다. 각 접두사의 `trade_food/ore/tools`, `trade_value`, `migrants`는 그 방향으로 **실제 실현된** 화물·현금 거래액·이동이다. 국경표는 지역 ID 두 개가 물리 도로를 정한다.

`relation`은 양수·음수를 갖는 관계 점수다. `trust`는 중립 500, `cooperation`·`tension`·`reciprocity`는 0에서 시작한다. 이 상태는 각 행의 기말값이다. 세계표의 `closing_mean_*`는 국경이 없는 쌍까지 포함한 28쌍 산술 평균이다. `relation_improved/worsened`는 바로 전 기말보다 점수가 개선/악화된 쌍·년 수다. A의 관계 및 방향별 연초 정책 점수는 공란, 관측된 쌍·년 `observations`는 0이다.

`agreement_years`는 효력이 있던 쌍·년, `agreements_started`는 새 체결 수다. 효력이 있는 한 쌍에는 연도당 두 방향이 있다. `agreement_directions_kept`는 실행 가능한 거래에 제한이 걸리지 않았던 방향, `agreement_directions_breached`는 수출 제한이 실제 화물을 막은 방향, `agreement_directions_no_opportunity`는 거래 기회가 0이었던 방향이다. 셋을 더하면 `2 × agreement_years`가 된다. `event_pact_proposed`는 의사를 밝힌 국가별로 세고 `event_pact_started`는 양측 합의 한 건을 센다. `event_pact_expired`는 만료, `event_pact_terminated`는 연속 위반에 따른 조기 종료다.

수출·출국·입국의 `*_permille` 값은 허용 비율로 1000일 때 전량 허용이다. `*_restriction_direction_years`는 허용 비율이 실제로 낮아진 방향·년이다. `trade_denied`, `exit_denied`, `entry_denied`는 접근 가능한 국경·물량 또는 이주 수요가 있을 때 해당 심사에서 막힌 시도 수량이다. 다른 도로나 목적지에서 다시 시도할 수 있다. `events.csv.gz`의 입국 제한 사건 발신은 입국을 제한한 국가이며, `ab_*migration_accept_permille`는 a에서 b로 가는 주민에게 b가 적용한 비율이다.

`shared_capacity_per_year`는 양방향과 모든 화물이 함께 쓰는 연간 물리 용량이다. 같은 도로 두 행에서 이 열을 더하면 용량이 중복된다. 쌍 표의 `physical_capacity`는 해당 쌍에 연결된 실물 도로의 용량을 도로당 한 번만 합산한 값이다. 체크포인트에서는 이를 해당 시점까지 누적한다. 개별 도로가 어느 해에 포화됐는지는 별도의 연간 도로 관측이 필요하다. 사람 이동은 정착 여건·입출국 한도를 따르며 화물 용량을 소모하지 않는다.

원조에서 `aid_quantity`는 그 방향으로 승인된 선적 상한, `aid_dispatched` 또는 국가 `aid_sent`는 실제 선적, `aid_received`는 수혜 공공창고 순입고다. 공여 창고 지출은 선적량 + 거리별 `aid_freight_food`다. 받는 창고의 순입고는 선적량 − `aid_handling_food`다. 원조 요청·제안·승인·배송에 각각 별도의 사건이 생긴다. `event_aid_shortfall`은 승인 후 전량 보내지 못한 사건 수다. 식량 수량이 필요한 경우 승인과 선적을 차감한다.

## 재생과 개입

`years_sha256`은 표시한 연도까지 모든 전체 기록을 순서대로 직렬화한 JSONL 바이트의 누적 해시다. `initial_sha256`은 네 경로의 공통 6.0A 초기 상태, `initial_5d_sha256`은 경제·정치·집단행동 초기 상태다. A의 연간 원본에는 외교 항목이 없다. B에서 외교 항목만 제거한 `projected_5d_sha256`은 A 전체와 5.0D 보관본 모두에 일치해야 한다. C와 D에는 5.0D 투영을 주장하지 않아 해당 열을 비운다.

`forks-dev.json`은 자연 체결된 조약의 신규 체결을 보류하거나 자연 제한된 수출·이주 한 방향을 여는 단년 비교다. 각 수단에서 최초 사례와 노출이 가장 큰 사례를 개발 표본에서 골랐다. 조약의 노출은 체결 연도의 거래액, 통제는 실제 제한에 걸린 양이다. 묶음이 같은 경우 이른 연도·작은 시드·국가 ID 순서로 선정했다. 두 가지 선정 기준이 같은 사례를 고를 수 있다. `actual`은 표준 실행과 해시가 일치하는 원래 정책, `alternative`는 나머지 연초 결정을 고정한 대안이다. `world_delta_actual_minus_alternative`는 원래 정책 전체 세계값에서 대안을 뺀 당해 차이다.

개발 표본에서 선택한 단년 개입 6건은 별도 프로세스에서 다시 선정하고 시뮬레이션했다. 두 결과의 338,665바이트 전체가 일치했다. [6건의 원장](forks-dev.json) · [독립 검증 해시와 시간](replay-forks.json)
