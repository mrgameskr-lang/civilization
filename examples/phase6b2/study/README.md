# 평시 복무 실험 자료 사전

시드 0~19는 개발 표본, 20~39는 독립 검증 표본이다. C와 D는 모두 B1의 공공 창고·원조·국내 도로 경제를 사용한다. C는 고정된 목표 비율, D는 연초까지 관찰한 자료로 결정한 목표 비율이다. 거주민의 일부가 정해진 기간에 평시 공공 복무를 맡으며 생산에는 같은 시간만큼 참여하지 않는다. [B1 자료 사전](../../phase6b1/study/README.md) · [평시 정책과 연구 결과](../../../docs/phase6b2-results.md)

B1과 같은 경제 파일 11개에 `service-policy.csv.gz`와 `service-moves.csv.gz`가 추가된다. `runs.csv`·`countries.csv`·`regions.csv`는 C/D의 50·100·200년 체크포인트, 연간표는 해당 연도의 실제 수량이다. `paired.csv`는 B1 공식 표본의 초기 상태·원본 해시를 확인한 후 B−A, C−B, D−C, D−B, C−A, D−A를 같은 시드끼리 계산한다. A/B에서 복무가 없는 경우 비교 시 복무 인원과 비용은 모두 0이다. 원래 A/B 경로의 개별 원장 해시는 B1 파일에 있다.

| 열·파일 | 계산 단위와 해석 |
|---|---|
| `service_serving`, `service_enrolled`, `service_released`, `closing_service_roster` | 주소지 기준 복무 인년, 당해 신규 등록/해제, 기말 명부. 마지막 열은 해당 기말의 인원이며 연도별 합이 아니다. `service_roster_open_years`는 연초 등록인원을 연도에 걸쳐 합한 인년 |
| `service_stationed`, `service_available`, `service_unavailable` | 실제 근무지 기준 인원, 급식·도구를 실제 배정받아 근무할 수 있는 인원과 그렇지 않은 인원. 전국합에서 근무지 인원은 주소지 복무 인원과 같다. 가용 비율은 가용 인년 ÷ 복무 인년. 복무 인원이 0이면 이 비율은 정의되지 않는다 |
| `service_ration_food`, `service_tools_used`, `service_travel_food` | 집에서 배정받은 식량, 근무지에서 실제 지급한 도구, 국내 왕복에 지급한 식량. 급식은 평소 식량수요와 실제 섭취에 이미 포함된다. 도구와 운임은 공공창고에서 지출된다 |
| `working_age`, `service_eligible_workers`, `withheld_workers`, `production_workers`, `construction_workers`, `soil_workers`, `project_workers` | 지역 기초 인구의 절반인 노동 인원에서 집단행동으로 철회된 노동을 빼면 복무 후보 인원이 된다. 복무 인년, 공공 사업, 생산·투자·토양 노동 및 철회 노동의 합이 기초 노동 인원과 같다 |
| `service_deaths`, `service_emigrants` | 복무 명부에서 빠지는 사망·기존 주소지 이탈 인원. 주민 사망·이주에 이미 반영된다 |
| `service-policy.csv.gz` | 시드·군·국가·연도별 인구, 이전 국경 긴장·위반·무역 의존, 비축과 부족률, 세 집단 신호와 집권 세력, 예상 생산 손실과 각 결정 요인의 가감점, 목표 비율·목표 인원과 실제 인원. `adjustments_json`은 당시 기록한 구성 요소다 |
| `service_opportunity_food_estimate` | 이전 작물 산출을 이전 노동 인원으로 나눈 생산성에 실제 복무자 수를 적용한 계획용 추정치. 실제 생산 차이는 같은 시드 B/C/D의 `produced_food`에서 확인 |
| `service-moves.csv.gz` | 국내 출신지에서 다른 근무지로 이동한 경우의 실제 인원·거리·경로·지출. 주민 주소지는 유지한다. `road_load`와 `service_road_load`는 1인 왕복당 2 도로 단위. `road-years.csv.gz`의 `duty_use`와 일치 |
| `service_undersupplied_country_years`, `service_zero_available_country_years` | 급식·도구 배정 후 실제 가용 인원이 명부 인원보다 적거나, 양의 복무 인원 중 가용 인원이 0이었던 국가·년 수 |

실제 소요시간과 기준 표본 해시는 각 `execution.json`, 독립 재실행은 `replay-dev.json`, `replay-holdout.json`에 기록된다. 같은 샘플을 먼저 B1에서 생성한 뒤, `python -B -m experiments.phase6b2 --sample dev --reference examples/phase6b1/study/dev --out 새폴더`로 C/D를 실행한다. 독립 검증은 `holdout`을 두 경로에 사용한다. 파일별 바이트 대조에는 `--verify-against 기존폴더`를 지정한다.
