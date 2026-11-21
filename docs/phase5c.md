# 5.0C 대표 선거와 재정 집행

5.0B의 연말 정치 관측을 다음 연초의 의회 구성과 사업 승인으로 연결한다. 시드는 영토와 경제의 초기 조건을 정한다. 선거와 정책 승인에는 난수를 사용하지 않는다. [고정된 실험 계획](phase5c-protocol.md) · [선호·선거·공약의 수식](competition-rules.md) · [현물세 수식](tax-policy5c.md)

## 실행

Python 3.11 이상에서 저장소 루트를 기준으로 실행한다. 출력 경로는 매번 새 디렉터리를 지정한다.

```sh
python -m civsim competition --seed 0 --years 50 --arm C --out runs/representative-seed0
python -m civsim verify runs/representative-seed0
python -m civsim analyze runs/representative-seed0
```

| 선택 | 집단 요구 | 선거와 지출 | 세금 |
|---|---|---|---|
| `--arm A` | 5.0B | 5.0B 정책 순위 | 고정 |
| `--arm B` | 실현된 생산 제약과 식량·재정 부담으로 분화 | 5.0B 정책 순위 | 고정 |
| `--arm C` | B와 동일 | 4년 임기, 21석 의회. 당선 내각이 재정 후보의 순위를 정함 | 고정 |
| `--arm D` | B와 동일 | C에 지출 재량 추가. 지지·물리 예산·손실 한도를 만족하는 일부 사업은 예상 경제 점수가 0 이하여도 승인 가능 | 고정 |
| `--arm C --tax-policy platform` | B와 동일 | C와 동일 | 내각의 강령에 따른 상시 현물세. 실험 표에서 E |

5.0B 정치 피드백 해제는 기존 명령 `python -m civsim politics --feedback off --out runs/politics-off`을 사용한다. 5.0C의 A는 그와 다른 비교 기준이며 **5.0B 피드백을 켠 경로**를 재생한다.

## 한 해의 자료를 읽는 순서

1. 연초에 전년 관측을 읽는다. 연도 1에는 노동 구성이 아직 관찰되지 않아 참여점수가 0이다. C·D·E는 5, 9, 13년 차부터 4년 간격으로 의석을 배정한다. 첫 과도내각에서 당선 내각으로 넘어간 횟수와 서로 다른 당선 세력끼리 교체된 횟수는 따로 기록한다.
2. `competition.countries`의 `election.ballots`에는 지역·집단별 규모, 세력별 선호와 배분된 대표점수가 있다. `election.seats`는 해당 연도의 지지를 의석으로 환산한 값이다. 선거 사이에 실제 재임 중인 내각과 의회 의석은 `closing.incumbent`와 `closing.seats`에서 확인한다. 집단 대표점수의 단위는 사람 수와 다르다.
3. 새 내각은 이전 해의 지역·정부 재고, 생산 설비와 도로를 인수한다. `politics.countries[].recommendation`은 경제 권고와 내각 선택, 후보별 점수와 제약을 보관한다. `competition.countries[].outgoing_choice`는 최초 집권이나 교체가 일어난 해에 직전 내각이 동일한 재정 후보에서 선택했을 대안이다.
4. 실물은 기존 5.0A 집행기가 처리한다. `government.accounts`는 승인과 실적을 구분한다. `works`, `relief`, `levies`, `roads`, `depots`에서 광석·도구·노동 투입, 도로 사용, 징수 비용, 정부 입고, 구호 도착을 대조할 수 있다. 국경 무역·화폐·인구의 독립 검산도 매년 시행한다. 이 단계의 정부에는 채무나 별도의 현금 수입 계정이 없다.
5. 주민은 실현된 생산·부족·공공사업·현물 부담을 관찰한다. 각 지역의 `politics.regions[].closing`이 다음 연초의 정치 상태다. 지지는 정책 선호와 현직 성과 양쪽에 의존하며 특정 직종을 특정 세력의 고정 지지자로 지정하지 않는다.

사례의 `manifest.json`은 처리군과 세계 설정을, `world.json`은 초기 상태를, `years.jsonl`은 연간 전체 원장을 담는다. 비교 실험은 모든 경로의 전체 원장 SHA-256과 집계 자료를 보관한다. 원장이 필요한 다른 시드는 같은 옵션으로 재생할 수 있다. [9년 공개 원장](../examples/phase5c/seed0-elections) · [재정 경로를 분기한 반사실](competition-forks5c.md) · [실행 및 검증 기록](phase5c-run.md)
