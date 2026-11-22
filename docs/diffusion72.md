# 7.2 국내 이주로 전해지는 농법

지역 16은 시드 2의 4년차에 두 번의 현장 시험을 마쳤다. 이듬해 이 지역 주민 23명이 도로 거리 10인 지역 19로 이주했다. 지역 19는 11년을 더 기다려 16년차에 현지 시험을 치렀다. 17년차 실제 수확은 1,589였고, 그해의 노동·토양·도구·기후를 그대로 두고 기존 농법을 대입한 생산량은 1,543이었다. [세 해의 원장 해시와 JSON 위치](../examples/diffusion72/seed2-region19.json) · [흐름도](https://www.tldraw.com/f/0bUzL9_Y5-sq8tpY7HMM6?d=s5EFyBZpDcrqbDq8ZqNqV-)

## 언제 기술이 바뀌는가

| 시점 | 필요한 사실 | 경제 장부에 남는 결과 |
|---|---|---|
| 이주 연도 말 | 연초에 농법 수준 1이었던 지역에서 같은 나라의 인접 지역으로 실제 주민이 한 명 이상 이주. 수령지는 아직 수준 0이며 최초 접촉 전 | 실제 이주 명세의 출발지·도착지·인원·거리·순번을 저장. 해당 연도 수확·숙련도에는 변화가 없다. |
| 이후 연도, 공공사업 집행 | 수령 지역에 토양 사업이 승인되고 7.1의 식량 사정·예상 수익·집행 능력 기준을 모두 충족 | 현장 시험 비용으로 기존 사업비 중 노동 2인년, 광석 1, 도구 1을 사용. 두 번째 온전한 현지 시험이면 독자 습득, 그 전이라면 과거 접촉과 이번 시험을 결합해 전파 습득. 연말에 수준 1이 된다. |
| 습득 이듬해부터 | 생산 시작 시점에 농법 수준 1 | 기존 식량 생산식의 농업 승수에 30을 가산한다. 원장에 실제 생산과 같은 입력에서 기술 효과를 뺀 수확을 함께 기록한다. |

정부가 승인한 토양 사업 전체는 노동 4인년·광석 2·도구 2를 사용한다. 시험을 병행하면 그중 절반이 연구로 분류되고 직접 관리할 농지가 최대 12타일에서 6타일로 줄어든다. 전파를 켜도 투자 승인과 시험의 기대 수익 계산은 7.1 기준을 사용한다. 첫 접촉 전에 한 번 시험한 지역도 접촉만으로 승급하지 않는다. 이후 두 번째 유상 시험을 마치면 독자 습득으로 기록한다. [의사결정과 생산식](research71.md)

한 해의 첫 적격 이주 명세가 수령지의 출처가 된다. 그해 여러 곳에서 이주했을 때는 기존 이주 원장의 순서를 따른다. 최초 접촉은 유지되며 추가 이주민 수에 따른 가속, 지식 소실, 개인별 지식이나 직업은 모형화하지 않는다. 이 모형의 접촉은 출발 지역이 가진 지식을 실제 지역 간 교류에서 접할 수 있었다는 집계 규칙이다. 이주민 개개인의 숙련은 관측하지 않는다.

## 실행과 검산

저장 경로에는 새 이름을 사용한다.

```console
python -m civsim.annual_game new --seed 2 --out runs/diffusion72/start.json
python -m civsim.annual_game step runs/diffusion72/start.json --research --diffusion --out runs/diffusion72/year1.json
python -m civsim.annual_game step runs/diffusion72/year1.json --reserve-policy emergency --out runs/diffusion72/year2.json
python -m civsim.annual_game show examples/diffusion72/seed2-year17.json
python -m civsim chronicle examples/diffusion72/seed2-year17.json --format json
```

`--diffusion`은 기존 연구가 활성화된 세계 또는 같은 해에 `--research`를 켠 세계에서 선택한다. 중도에 활성화하면 이미 습득한 지역의 독자 습득 이력을 인정하고, 과거 이주로 소급해서 접촉을 부여하지 않는다. 저장 형식 `annual-game/6`은 지역별 첫 접촉·습득 방식, 연구 상태, 명령, 연간 원장 해시를 보존한다. 재생 시 원래 시드와 명령에서 계산한 연말 상태를 대조한다.

| 확인할 내용 | 연간 원장 |
|---|---|
| 실제 국내 이주 | `/moves/{순번}` 및 양쪽 지역의 `demography` |
| 지식 출처와 습득 방식 | `/diffusion/regions/{순번}`의 `closing_contact`, `closing_method` |
| 현지 비용과 자격 | `/research/regions/{순번}`, 해당 `project_id`의 `/government/works/projects/{순번}` |
| 다음 해 수확·동일 투입 비교 | `/regions/{순번}/production`의 `farm_tech_level`, `produced/food`, `food_without_tech` |

경로 차단 진단인 `--block-migration 16 19`는 지정한 한 해에 두 지역 사이의 양방향 주민 이동을 막는다. 같은 도로의 화물 운송은 원래 규칙을 따르며 다른 이주로를 이용한 인구 이동도 가능하다. 이 차단은 실제 지역별 인구도 바꿀 수 있다. 열린 길과 닫힌 길의 전체 수확 차이에는 이주에 따른 경제 변화가 포함된다. 농법의 직접 효과는 해당 수확에서 투입을 고정한 차이로 읽는다. [시드별 비교와 반례](diffusion72-results.md)
