# 게임 유닛의 현지 창고 지급

선택 규칙 `annual-unit-upkeep/1`은 기존 위치 원장 `annual-unit/1` 위에서 플레이어가 표시한 게임 말 1~2개의 턴별 유지 상태를 계산한다. 주소지 5에서 7로 이동한 두 말에 대해, 플레이어는 다음 명령으로 실제 경제를 한 턴씩 진행하고 새 슬롯에 저장할 수 있다.

```sh
python -m civsim.annual_game new --seed 0 --out runs/token-0.json
python -m civsim.annual_game step runs/token-0.json --out runs/token-1.json
python -m civsim.annual_game step runs/token-1.json --move 5 5 7 2 --upkeep 5 2 --out runs/token-2.json
python -m civsim.annual_game step runs/token-2.json --out runs/token-3.json
python -m civsim.annual_game show runs/token-3.json --custody
```

## 누가 어디에서 지급받는가

`--upkeep HOME COUNT`가 지정된 첫 턴의 **기초 명부**에서 말을 최대 COUNT개 표시한다. 이미 다른 곳에 있던 말은 방문 지역 번호 순서로 먼저 선택하고 남은 수만 주소지에서 선택한다. 복무자가 한 명도 없는 첫해 연초에 선택하면 표시되는 수도 0이다. 이후 등록자는 자동 보충하지 않는다. 같은 주소지의 한 지역에 여럿 있으면 이동 영수증의 수량까지 표시된 말을 먼저 옮긴다. 거부된 명령은 위치를 바꾸지 않는다. 행정 소속, 통근 왕복 기록, 편도 위치는 각각 별도 상태다.

명부는 집계 자료다. 기존 엔진이 해제·사망·이주에 따라 한 주소지에서 각 위치에 남을 수 있는 인원을 먼저 정한다. 각 위치에서 표시된 인원은 `min(기존 표시 인원, 그 위치의 잔존 인원)`만큼 남는다. 기말에는 표시된 말 중 이번 턴 지급받은 말을 마지막에 제외한다. 이는 개인을 식별할 수 없는 자료에 적용하는 명시적인 정수 배분 순서다. 이 선택 때문에 장기 생존 기간을 개인 통계로 해석할 수 없다. 해당 지역의 명부 자체가 비면 지급 여부와 관계없이 표시 인원도 0이 된다.

## 창고·식사·도로 회계

1. 원래의 노동 배정, 공공사업, 공공 운송, 통근, 생산, 국경 거래·원조, 현물 징수를 실행한다.
2. 편도 이동 영수증이 출발 창고 식량과 실물 도로 용량을 차감한다. 성공하면 목적지 위치에 반영한다.
3. 실제 현재 위치마다 표시된 유닛 수를 `n`, 그곳 공공창고의 남은 식량과 도구를 `F, T`로 읽는다. 완성 세트 수 `s = min(n, F, T)`만 지급한다. 창고 기말은 이 단계에서 `F−s, T−s`이고 미충족은 `n−s`다. 두 품목을 갖추지 못한 말에 대한 부분 지출은 0이다. 같은 창고 내에서 지급하여 추가 도로 사용은 0이다.
4. 남은 재고로 기존 국내 구호를 실행하고 잔여 도로에서 민간 배송을 실행한다. 주민 식사·부패·인구변동은 원래 규칙을 따른다.
5. 국가별 공공지출에 `unit_upkeep_food`와 `unit_upkeep_tools`를 각각 적는다. 공공창고와 국가 통합 장부는 같은 소비의 두 집계 수준이다. 비용을 두 번 더하지 않는다. 현금·노동 추가 발행은 없다.

여기서 식량 한 점은 **게임 유지용 소모품**이다. 기존 주소지 배식이 주민 식사에 한 번 들어가며, 이 추가 지출은 주민 식량 수요나 실제 섭취에 더하지 않는다. 지급 상태는 게임 말이 한 턴에 두 물품을 받았는지만 나타낸다. 종전 복무 집계와 이 인원을 더해 사람이 늘어났다고 계산할 수 없다.

규칙을 켜면 원장의 `unit_upkeep.groups`에 지역별 명목·충족·미충족, 각 품목의 지출과 전후 잔고가 남는다. 기말 행 `[현재 위치, 남은 표시 유닛, 그중 당해 지급 유닛]`이 다음 연초에 이월되고, 새 턴의 지급 여부는 재고를 다시 보고 계산한다. 종료 상태는 `annual-game/2` 저장과 재생 해시 양쪽에서 확인한다. 기존 선택을 사용하지 않은 저장은 기존 형식을 사용한다.

## 실제 단년 대조

시드 0의 2년 차, 지역 5→7의 실제 도로 잔량이 106→104, 출발 창고의 이동 운임이 식량 2였다. 이동 후 지역 7의 창고는 식량 1·도구 3이었고, 두 말 중 한 말만 유지비를 전액 지급받았다. 지급 후에는 식량 0·도구 2였다. 다음 연초에는 지역 7에 두 말과 전년 지급 상태 1이 남았다. 새 턴 현지 식량이 0이어서 0명분을 지급했다. 한 말만 이동하면 2년 차에 1/1, 다음 턴에는 0/1이었다.

| 2년 차 대조 (앞 경로 − 뒤 경로) | 유지 식량 | 유지 도구 | 기말 창고 식량 | 기말 창고 도구 | 사용 도로 | 민간 배송 | 주민 섭취 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 같은 이동, 지급 켬 − 끔 | +1 | +1 | −1 | −1 | 0 | 0 | 0 |
| 지급 켬, 이동 − 보류 | −1 | −1 | −1 | +1 | +2 | 0 | 0 |

별도 분기에서 지역 4의 도구 73·식량 0으로는 아무것도 차감하지 않았다. 시드 0의 10년 차 지역 3에서는 식량 22·도구 0으로 두 말 모두 미충족이었다. 7년 차 지역 5에서는 제자리 지급 2세트가 구호를 2 줄였고 민간 식량 배송이 2 늘었다. 그해 주민 총섭취 변화는 0이었다. 시드 2의 5년 차 주소지 7 명부 감소는 실제 명부 이탈과 대조했다. 방문지 4에 남은 표시 유닛은 1이었다.

[실제 원장·경로별 차이](../examples/token-upkeep-v1/case) · [저장·불러오기 실행 로그](../examples/token-upkeep-v1/cli.json) · [지역·국가 수지 검산](../examples/token-upkeep-v1/compat/country-financial-balances.json)

## 재현 방법

아래 명령은 저장소 루트에서 실행하며 출력 디렉터리나 파일은 새 경로를 지정한다. 사례 원장은 정렬된 키의 UTF-8 JSONL을 gzip으로 압축했다. 운영체제 사이에서는 압축을 푼 원장 바이트로 재현성을 확인한다. Python 3.11~3.12에서는 시간 필드를 0으로 고정해도 gzip OS 바이트가 달라질 수 있다. [CPython 공식 문서](https://github.com/python/cpython/blob/v3.12.16/Doc/whatsnew/3.11.rst)

```sh
python -B -m unittest discover -v
python -B -m experiments.token_upkeep_case --out runs/token-case
python -B -m experiments.token_upkeep_study --out runs/token-study --workers 7
python -B -m experiments.summarize_token_civil --study runs/token-study --out runs/token-civil.json
python -B -m experiments.replay_token_upkeep examples/token-upkeep-v1 --out runs/token-repeat.json
python -B -m experiments.verify_annual21 --scope full --workers 3 --out runs/token-compat.json
```
