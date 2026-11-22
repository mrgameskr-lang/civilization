# 지역별 직접 구호 수혜

`political-relief-benefits/1`은 각 연도에 어느 지역 가계가 얼마나 구호 식량을 받았는지 보여 준다. 같은 지역의 창고에서 나간 구호와 다른 지역에서 도착한 구호 모두 **가계가 실제 수령한 지역**에 기록한다. 지급 뒤 민간 거래·식사가 이어지므로, 수혜액과 최종 섭취량은 각각 확인할 수 있다.

```text
python -B -m civsim.annual_game new --seed 0 --out start.json
python -B -m civsim.annual_game step start.json --out year1.json
python -B -m civsim.annual_game step year1.json --reserve-policy emergency --relief-benefits --out year2.json
python -B -m civsim.annual_game show year2.json --relief-benefits
```

`step`의 출력에는 방금 마친 연도, `show`의 출력에는 저장된 모든 연도가 `relief_benefits.years`에 담긴다. 선택한 지역은 각 연도의 `regions`에서 찾는다. 세계 합계는 `totals`에 있다. 0년차 저장을 조회하면 연도 목록은 비어 있다.

| 지역별 필드 | 의미 |
|---|---|
| `region`, `owner` | 수령 지역과 소속 국가 |
| `ordinary_received` | 정규 구호가 해당 지역 가계에 전달한 식량 |
| `emergency_received` | 추가 구호가 해당 지역 가계에 전달한 식량. 해당 규칙이 꺼진 연도는 0 |
| `relief_received` | 두 단계의 실제 수령량 합계. 이 관측 버전의 직접 구호 수혜액 |
| `legacy_relief_food` | 원래 정치 원장의 지역별 `evidence.relief_food`. 정규 구호 수혜만 기록 |
| `food_eaten`, `food_unmet` | 실제 가계 섭취량과 충족하지 못한 필요량 |

연도별 `emergency_active`는 추가 구호 규칙이 적용됐는지 표시한다. 규칙이 켜진 해에도 전달량은 0일 수 있다. 검산에서는 민간 잔고 증가를 수령지별 전표와 대조하고, 지급 창고에서 발송량과 운임이 차감됐는지 확인한다. 식사 전표와 다음 단계의 민간 잔고를 독립적으로 확인한다. 운임을 수혜액에 더하거나 수혜액을 실제 섭취량에 더하면 중복 계산이 발생한다.

파이썬에서는 완결된 연간 원장을 `civsim.relief_benefits.relief_benefits(record)`에 전달한다. 저장하거나 전달받은 관측 결과는 `audit_relief_benefits(record, report)`로 재검산할 수 있다. 기존 정치의 집단별 지지·선거·집단행동은 기존 규칙을 따르며, 새 관측은 공개된 연간 원장과 저장 해시 바깥에서 계산한다. 직접 수령 기록만으로 집단별 개인 수혜, 추가 섭취량, 선거에 미친 효과를 식별할 수 없다.
