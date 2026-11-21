# 공공창고 운송 자료 사전

개발 시드는 0~19, 검증 시드는 20~39다. 각 시드의 A는 6.0A.1 F, B는 같은 원조·수출·이주 규칙에 국내 공공창고 간 운송을 더한 경로다. 체크포인트 50·100·200은 한 번 시작한 200년 경로의 누적 관측이다. [설계·결과](../../../docs/phase6b-study.md) · [기존 창고 배치 진단](../prior-shortfalls.json)

| 표본별 파일 | 한 행의 단위와 해석 |
|---|---|
| `runs.csv` | 시드·군·체크포인트별 세계 기말 상태, 누적 지표, 초기 상태/연간 JSONL 누적 해시 |
| `countries.csv`, `regions.csv` | 같은 시점의 국가·지역별 구분. `closing_*`는 기말 재고·현금·인구이고 그 밖의 물량·식사·노동은 누적 |
| `paired.csv`, `means.csv` | 같은 시드에서의 B−A와 시드 평균. `pooled_deficit_share`는 표본 전체 미충족 식량 ÷ 표본 전체 필요량 |
| `region-years.csv.gz`, `country-years.csv.gz` | 모든 지역·국가의 당해 식사, 시작/기말 재고, 생산·물자 사용, 자금·인구, 실제 공공·민간 운송, 원조와 정치 반응. 지역표에 창고 기초 재고 포함 |
| `public-shipments.csv.gz` | 국내 창고 사이에서 실제로 보낸 송장. `request_id`로 같은 시드·군·연도의 요청을 찾고 `source,target` 지역, 거친 지역·타일 경로, 화물·실제 운임을 확인 |
| `depot-requests.csv.gz` | 국내 공공 이동 요청. 기초 수량부터 목표와 기말 수량까지, 미충족량, `observed_limits`와 `evidence_json`에 기록한 당시 근거. 국경에서 원조가 미이행된 이유와 다른 단계 |
| `road-years.csv.gz` | 실제 국내 도로마다 연도별 총용량 및 공사·국내 공공창고·복무·국내 구호·민간 화물 사용·미사용량. A와 B는 복무 이동이 0 |
| `foreign-years.csv.gz` | 접경·원조 신호가 있는 외국 방향의 연도별 정책·거래·이동·원조. 원조 요청·제안·승인·선적·순수령·미발송과 사유 조합, 연초/말 긴장 |
| `execution.json` | 실행 규모, 버전, 시간, 모든 과학 파일의 바이트 해시. 상위 폴더의 `replay-dev.json`, `replay-holdout.json`은 독립 재실행의 원본 영수증 |

`public_transfer_out_food/ore/tools`와 `public_transfer_in_*`는 국내 정부창고 간 실제 수량이다. `emergency_aid_units`는 승인 원조의 출발 국경 창고로 보낸 양, `forward_aid_units`는 직전 신호에 따라 미리 옮긴 양, `domestic_reserve_units`는 국내 비축 목적 물량이다. 마지막 값은 서로 다른 세 재화를 단순 합한 수량이므로 상품별 분석에는 원본 송장의 `good`이 필요하다. 창고 재배치는 곧바로 주민 섭취나 국경 원조가 되지 않는다.

`depot_freight_food`는 국내 공공창고 이동의 거리별 운임 식량이다. `internal_aid_freight_food`는 그중 원조용 준비·긴급 수송에 지불한 운임이고 `domestic_reserve_freight_food`는 국내 목적의 운임이다. 국경을 건넌 원조는 `aid_sent = aid_received + aid_handling_food`로 세계에서 결산된다. 총 공여 지출 `aid_total_debit = aid_sent + aid_freight_food + internal_aid_freight_food`가 해당 공여국의 Q(`aid_budget`) 안에 들어야 한다. `aid_unshipped_stock/road/budget/storage`는 말단 사유에 해당 제약이 포함된 미발송 수량으로 서로 겹칠 수 있다.

`private_transfer_*`는 같은 나라의 민간 화물, `foreign_in/out_food/ore/tools`는 민간 국제 교역, `relief_food`는 국내 공공창고에서 개인 재고로 넘긴 실제 식량이다. `*_edge_cargo`는 화물량에 지나간 도로 구간 수를 곱해 합한 값이다. 이 값은 화물 단위의 송장 합보다 클 수 있다. `food_eaten`은 결국 주민이 실제로 먹은 양, `food_need`는 필요량, `food_deficit`는 부족량이다. 저장·운송을 거친 식량의 개별 산지는 식사 원장에 표시되지 않는다. 독립 단년 개입에서 배급 또는 이송을 바꿔 계산한 섭취 차이는 장기 A/B 궤적 차이와 구분한다.

인구는 주소지에서 한 번 센다. `births/deaths/immigrants/emigrants`는 모든 지역 출생·사망·유입·유출이므로 국가표의 이주 인원에 국내 지역 간 이동 양쪽이 들어간다. 국제 이동만 보려면 `foreign_in/out`을 사용한다. `mean_support`, `mean_discontent`는 집단 구성원·연도로 가중한 0~1000 점수다. 세계의 `pact_partners`, `terminated_pact_partners`는 국가 방향 합이므로 양국 협정 건수는 2로 나눈다. 평균 긴장은 국경이 없는 쌍까지 포함한 모든 쌍의 연도별 평균이다.

재현하려면 저장소에서 `python -B -m experiments.phase6b --sample dev --workers 5 --out 새폴더`를 실행한다. 검증 표본은 `--sample holdout`, 전체 과학 파일 바이트 대조는 `--verify-against 원본폴더`로 지정한다. A의 50·100·200년 누적 해시와 초기 세계는 기존 6.0A.1 F와 대조한다.
