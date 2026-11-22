# 비축·비상 구호 실행 기록

기준은 PR #25의 `c2d2ea38292e62ca2e4bb3c20ad92ca868e4b1cc`다. 아래 경로는 저장소 루트 기준이다. 실험 출력에는 새 디렉터리나 파일이 필요하다. 재실행할 때는 보관된 원자료와 다른 출력 경로를 사용한다.

## 작은 세계와 본 실험

먼저 시드 0에서 실제 연간 경제의 C와 E를 같은 연초에서 분기해 이동 없이 현지 창고를 지급한 사례, 실제 주민 섭취 차이, 차년도 이월을 확인했다. 7일·14일 목표도 실제 같은 농지·노동의 작물로 작동함을 검산했다. 그 후 개발 0–19, 검증 20–39로 진행했다. 50·100년 결과는 각각 동일한 200년 궤적의 중간 상태다.

```text
python -B -m unittest tests.test_reserve_relief_game -q
python -B -m experiments.relief_forks --out examples/reserve-relief-v1/forks
python -B -m experiments.reserve_relief_study --out examples/reserve-relief-v1/study --workers 10
python -B -m experiments.reserve_relief_study --out ../reserve-relief-repeat-v1 --workers 2 --seeds 0 20
python -B -m experiments.crop_practices --study examples/food-reserve-v1/study --out examples/reserve-relief-v1/production-diagnosis.json
python -B -m unittest discover -v
```

## 원자료

본 실험은 Python 3.12.14, 10개 작업 프로세스에서 1,158.06초가 걸렸다. 40,000세계·연도, 320,000국가·연도, 1,280,000지역·연도를 게시했다. 1년차를 공유하고 B 호환성 재생을 포함한 실제 엔진 실행은 47,800단계다. [실행 메타데이터](../examples/reserve-relief-v1/study/execution.json)

다음 후처리를 실행했다. 시드 0·20에서 따로 생성한 압축 파일과 시드 해시 명세 22개가 모두 바이트 단위로 일치했다. 원자료의 1,280,000개 지역 행과 국가·세계 합계, PR #25의 연초 40개와 원장 해시 360개를 확인했다. [검산 결과](../examples/reserve-relief-v1/verification.json)

```text
python -B -m experiments.reserve_relief_summary --study examples/reserve-relief-v1/study --out examples/reserve-relief-v1/summary.json
python -B -m experiments.reserve_relief_verify --study examples/reserve-relief-v1/study --repeat ../reserve-relief-repeat-v1 --out examples/reserve-relief-v1/verification.json
python -B -m experiments.relief_forks --natural-study examples/reserve-relief-v1/study --out examples/reserve-relief-v1/forks/natural-obstructions.json
python -B -m experiments.ordinary_relief_residual --study examples/reserve-relief-v1/study --out examples/reserve-relief-v1/ordinary-residual.json --workers 6
```

`study/seed-NN-P-regions.jsonl.gz`의 첫 줄은 시드, 정책, 열 이름이다. 이후 한 줄이 한 해이고, 각 줄에 지역 32곳이 ID 순서로 들어간다. `-totals.jsonl.gz`는 매년 8개 국가와 세계 합계를 담는다. 보관된 `seed-NN.json`에는 같은 시드의 1년차 결산 상태 해시와 정책별 50·100·200년 전체 원장 해시가 있다. 연구용 출력은 필요한 전표와 수치를 추출한 자료다. 200년의 모든 연간 엔진 JSON을 그대로 저장한 파일은 아니다. [원자료 디렉터리](../examples/reserve-relief-v1/study) · [각 열의 원장 출처](../experiments/reserve_relief_flow.py)

구호 전과 연말 시점을 별도 기록한다. 예를 들어 `unmet_with_local_stock`은 추가 구호 직전 현지 창고에 양의 식량이 있었던 지역의 최종 미충족량이다. 이 수량을 구호로 모두 없앨 수 있었다고 가정하지 않는다. 출고를 두고 경쟁하는 공공 배식·원조·사업 지출, 구간별 운임과 도로·행정 용량은 실제 연간 엔진에서 우선순위대로 차감된다.

## 검증 범위

로컬 전체 테스트의 최종 실행은 **593개 통과, 336.035초**였다. 중간 전체 실행에서는 588개가 통과했다(401.861초). [최종 전체 로그](../examples/reserve-relief-v1/tests-final.txt) · [중간 테스트 로그](../examples/reserve-relief-v1/tests.txt)

정규 구호 C의 승인 후 미발송이 있었던 315지역·연도를 검산하기 위해 필요한 마지막 연도까지 7,227세계·연도를 따로 재생했다. 이 과정에서 도달한 기존 연간 원장 해시 83개가 모두 일치했다. `git diff --exit-code c2d2ea3 -- examples ':(exclude)examples/reserve-relief-v1/**'`는 종료 코드 0이었다. [정규 구호 사유별 근거](../examples/reserve-relief-v1/ordinary-residual.json)

기존 A·B·C를 실제로 재생하고 PR #25에 보관된 각 시드의 연초 및 세 체크포인트를 대조한다. 새 다섯 실험군은 지역별 기초/기말 창고·민간 재고·주민 수의 다음 해 연속성, 국가합·세계합, 식량 소비와 사망, 추가 구호의 승인·재고·운임·도로·수령을 검산한다. 기능 비활성 시 이전 저장 형식이 재생되고 새 정책을 저장한 슬롯은 규칙을 이월한다. 이전 8개 보관 예시 재생 명령과 해시는 [별도 로그](../examples/reserve-relief-v1/archived-replays.txt)에 있다.

공공 경작 목표·구호 처리량·사업 순서는 사전 고정한 게임 규칙이다. 대안 재정 구조, 모든 미래 기후, 200년 이후 결과, 새 농업 기술의 동적 시뮬레이션은 검증 범위 밖이다. 추가 구호에서 주민 개인별 식사를 식별하지 않았다. 시드가 같아도 정책이 달라지면 이후 인구와 생산이 달라질 수 있다.
