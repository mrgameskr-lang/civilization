# 식량 비축 실험 실행·검증 기록

기준은 `0340e0052599bdaa33fcff6daf88c011c55834b7`이다. Windows의 CPython 3.12.14로 실행했다. 아래의 `python`은 해당 인터프리터다. 경로는 저장소 루트 기준이다. 기존 결과를 덮어쓰지 않도록 각 생성 명령은 새 출력 경로를 요구한다. 이미 자료가 체크아웃되어 있다면 재현 시 별도의 빈 출력 위치를 지정한다.

## 실제 실행

1. 시드 0의 1년차를 생성하고, 2년차의 세 경로와 3년차 이월을 실행했다. 각 경로에서 기존 게임의 지역·국가·공공창고·현금·인구 감사를 호출했다. 최초의 공통 연초 비교를 `same-opening.json`으로 저장한 후에 장기 실행을 시작했다. 최종 감사 강화 후 같은 자료를 다시 생성해 바이트 단위로 비교했다. 두 파일의 SHA-256은 `0b81f5209567dee5280784470710534afad2b3d6209fb266b42e8da706b1a6f5`였다.
2. 10개 작업 프로세스로 40개 시드, 세 경로를 200년까지 실행했다. 1년차를 공유하여 엔진 단계는 23,920회, 관측한 세계·연도는 24,000개다. 192,000개 국가·연도와 768,000개 지역·연도를 기록했다. 벽시계 517.39초는 이 컴퓨터의 이번 실행 시간이며 다른 작업과 일부 겹쳤다. [실행 메타데이터](../examples/food-reserve-v1/study/execution.json)
3. 별도 프로세스와 별도 디렉터리에서 개발 시드 0과 검증 시드 20의 세 경로를 다시 실행했다. 두 시드의 압축 파일·시드 해시 명세 14개가 원본과 바이트 단위로 같았다. 40개 연초와 A·B의 240개 체크포인트를 PR #24 기록과 대조했다. 연속 두 연도의 지역 인구·민간 재고·공공 재고도 확인했다. [재현 해시와 대조 결과](../examples/food-reserve-v1/verification.json)
4. 생산 직후 재고와 영수증을 함께 위조한 회귀 사례를 발견해 보관 감사를 강화했다. 실제 인구·경작지·토양·예약 노동·시드 기후로 총생산을 별도로 재계산한다. 강화한 최종 코드로 C를 **40시드 모두 다시 실행**하여 8,000세계·연도의 모든 지역·국가·세계 통계와 120개 체크포인트 원장 해시가 기존 C 출력과 같음을 확인했다. [최종 C 독립 재생](../examples/food-reserve-v1/harvest-replay.json)
5. 전체 단위·통합 테스트의 최종 실행은 **558개 통과, 226.060초**였다. 중간 실행은 557개 통과(217.178초)였으며 교차 위조 회귀 한 개를 추가했다. CI와 같은 이전 버전 8개 보관 경로도 로컬에서 재생했다. `git diff --exit-code 0340e00 -- examples ':(exclude)examples/food-reserve-v1/**'`는 종료 코드 0이었다. [최종 전체 로그](../examples/food-reserve-v1/tests-final.txt) · [중간 전체 로그](../examples/food-reserve-v1/tests.txt) · [이전 경로 재생 로그](../examples/food-reserve-v1/archived-replays.txt)

```text
python -B -m experiments.food_reserve_study --small --out ../food-reserve-small-final.json
python -B -m experiments.food_reserve_study --out examples/food-reserve-v1/study --workers 10
python -B -m experiments.food_reserve_study --out ../food-reserve-repeat-v1 --workers 2 --seeds 0 20
python -B -m experiments.food_reserve_verify --study examples/food-reserve-v1/study --repeat ../food-reserve-repeat-v1 --out examples/food-reserve-v1/verification.json
python -B -m experiments.food_reserve_verify --study examples/food-reserve-v1/study --replay-harvest --workers 9 --out examples/food-reserve-v1/harvest-replay.json
python -B -m experiments.food_yield_factors --study examples/food-reserve-v1/study --out examples/food-reserve-v1/yield-factors.json
python -B -m experiments.food_fiscal_diagnosis --study examples/food-reserve-v1/study --out examples/food-reserve-v1/fiscal-diagnosis.json
python -m experiments.food_trajectory --study examples/food-reserve-v1/study --out examples/food-reserve-v1/summary.json
python -B -m unittest discover -v
```

경로 A와 B 전체의 모든 연간 **전체 원장**에 대한 과거 200개 해시는 PR #24 자료가 제공하지 않는다. 공개된 50·100·200년 전체 원장 해시와 연초 상태를 사용했다. 2개 시드의 세 경로, C의 40개 시드를 독립 반복했다. 주요 자료는 실험 출력이며, 창고의 1일분 기준과 토양·노동을 한 변수씩 바꾼 수확 비교는 사후 분석 지표다.
