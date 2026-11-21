# 5.0D 실행과 검증 범위

기준은 PR #10의 `c220dc526d88b4e08396cdbd7a7717d7a0c59cf7`이다. 비교군과 측정 방법은 `c645b9a`, 새 행동과 재정·대조 규칙은 `614f0e9e3dab0c9ad910cda76c55279f54c51ee7`에서 고정했다. 독립 검증 시드의 새 결과를 연 뒤에는 문서, 독립 검산, 내보내기와 테스트를 추가했다. 실험은 Windows와 CPython 3.12.14에서 실행했다. 각 출력은 새 경로에 작성했다. [실험 계획](phase5d-protocol.md) · [공식과 실행 방법](collective5d.md) · [정치·경제 결과](phase5d-results.md)

## 테스트와 기존 실행 보존

최종 전체 테스트는 **242/242 통과, 63.282초**였다. 기준 222개에 20개를 추가했다. 연간 국가 파일이 아직 생성 중일 때 먼저 실행한 별도의 검사에서는 파일 부재로 게시 자료 테스트 1개가 실패했다. 두 파일이 완성된 뒤 공개 자료 검사 2/2개를 1.217초에 통과했고, 이어 전체 성공 로그를 저장했다. [최종 전체 출력](phase5d-tests.txt)

```sh
python -B -m unittest discover -q
python -B -m unittest tests.test_collective_rules tests.test_civic_fiscal tests.test_collective_integration tests.test_phase5d_study -q
python -B -m unittest discover -v
python -B -m experiments.check_stack5d --out examples/phase5d/pr-stack.json --workers 3
python -B -m experiments.verify_archives31 --workers 3
```

기준 브랜치의 222개 테스트가 38.525초에 통과했다. 행동 선택, 권한·재고·노동, 계정 위변조, 부분 중단과 구호, 동일 연초 분기와 원래 세계 불변성 등을 대상으로 한 동결 전 집중 검사는 12/12개, 5.247초였다. 각 PR의 고정 버전에서 다시 실행한 테스트 수와 기준 브랜치는 별도로 기재했다. [PR별 재실행과 수동 병합 순서](integration5d.md) · [최종 테스트 로그](phase5d-tests.txt)

과거 국가 엔진 280개 경로의 초기·연간 누적 해시 400개가 보관본에 일치했다. manifest를 갖춘 1.0·2.0·3.0·4.0·5.0A·5.0B·5.0C 예제 7개와 새 5.0D 예제 1개도 실제 재생했다. 본 실험의 기능 해제군 40개 경로에서 50·100·200년 체크포인트 120개의 시작 및 연간 해시가 5.0C C군 보관본과 일치했다. 3.1의 모든 장기 투자 실험이나 4.0·5.0A·5.0B 전체 행렬을 새로 실행하는 작업은 이번 검증 범위 밖이다.

## 연간 원장과 실험 자료

```sh
python -B -m civsim collective --seed 0 --years 6 --actions on --out examples/phase5d/seed0-actions
python -B -m civsim verify examples/phase5d/seed0-actions
python -B -m civsim analyze examples/phase5d/seed0-actions
python -B -m experiments.phase5d --sample dev --out examples/phase5d/study/dev --workers 8
python -B -m experiments.phase5d --sample holdout --out examples/phase5d/study/holdout --workers 8
python -B -m experiments.country_years5d --sample dev --out examples/phase5d/country-years/dev.csv.gz --workers 4
python -B -m experiments.country_years5d --sample holdout --out examples/phase5d/country-years/holdout.csv.gz --workers 4
```

시드 0 공개 예제에서 인구는 75,029명에서 77,931명이 됐다. 6년간 부족 31,783식, 참여 9,105인년, 노동 철회 86인년, 실물 미납 세 품목 모두 0이었다. 연간 원장 3,899,065바이트의 재생 SHA-256은 `c96297045b5475154e9a6e0cebd0b21a37e9ab6e883b2cd8fe6fcecdbd00c169`이다. 기능 해제 아카이브는 설정 파일에 5.0D 비활성을 표시하고, 초기 세계와 연간 기록의 내용은 5.0C와 동일하다. [6년 전체 원장](../examples/phase5d/seed0-actions)

각 표본의 `runs.csv`, `countries.csv`, `regions.csv`는 체크포인트까지 누적한 결과를 담는다. `events.csv.gz`에는 행동이 집행된 집단·연도의 직전 부족·지지·현물 부담과 실제 참여·납부·후속 지지가 있다. `country-years`의 두 파일은 시작·마지막 인구, 세 가지 당해 생산량, 당해 필요·부족 식량, 집권 세력, 집단행동과 실제 세액을 **모든 연도**에 제공한다. 행동이 없었던 연도와 비활성 대조군도 포함한다. 시드·처리군별 연간 원장을 다시 생성하며 주 실험 해시와 대조한 뒤 출판했다. [시드·국가·연도별 자료](../examples/phase5d/country-years) · [선거 진단·민감도 명령과 원자료](election-diagnostics5d.md) · [집단행동 반복·단년 개입 명령](phase5d-results.md)

연간 국가 자료는 표본별 64,000행, 총 128,000행이다. 내보낸 두 파일의 각 120개 원장 해시를 확인했다. 공개자료 테스트는 국가별 당해 산출·부족·노동 손실·미납을 합산해 50·100·200년 세계 장부를 재구성한다. 독립 대조 실행은 총 16,000세계연도를 다시 계산해 원 실행의 **240개 체크포인트와 18개 결과 파일 모두**에 일치했다. 별도의 단년 개입 4개도 재생 JSON 전체가 같았다. PR #10에서 물려받은 예제 150개의 Git blob을 현재 작업 트리와 직접 대조해 변경 0개를 확인했다. [검증 코드](../tests/test_collective_publication.py) · [개발 반복](../examples/phase5d/study/replay-dev.json) · [독립 검증 반복](../examples/phase5d/study/replay-holdout.json)

## 200년간 행동이 없는 세계

표준 개발 20개·독립 검증 20개 세계의 활성군에서는 모두 한 번 이상 행동이 발생했다. 무행동이 가능한 조건을 별도로 확인하려고 시드 0의 32개 지역 인구를 일률적으로 6명·30명·150명으로 초기화했다. 민간 재화와 현금도 각 지역의 인구 비율로 내림해 초기화했다. 지도·농지·광맥·기후는 그대로 두고 연중에는 자원을 추가하지 않았다. 아래 표는 초기 조건 세 개 모두를 보여 준다. 이 사례는 표준 40시드 무행동 빈도의 표본에 들어가지 않는다.

| 초기 지역 인구 | 초기 → 200년 세계 인구 | 집단 규모 8 이상인 집단·연도 | 직전 불만 ≥35인 집단·연도 | 활동 시작 | 활동 집단·연도 |
|---:|---:|---:|---:|---:|---:|
| 6 | 192 → 192 | 0 | 5,280 | 0 | 0 |
| 30 | 960 → 902 | 11,964 | 3,105 | 412 | 822 |
| 150 | 4,800 → 101,478 | 19,104 | 5,937 | 899 | 3,803 |

각 세계에 관측 가능한 집단·연도는 19,200개다. 지역 6명 사례는 불만이 일정 수준을 넘어도 최소 집단 규모를 만족하지 못했다. 200년 동안 실제로 부족한 식량은 누적 2,102식이었다. 여기서 활동 시작은 행동 종류·요구별 연속 기간의 첫해다. [정착지별 세 체크포인트와 해시](../examples/phase5d/settlements-dev0.json)

```sh
python -B -m experiments.settlements5d --out examples/phase5d/settlements-dev0.json
python -B -m experiments.settlements5d --out ../../work/phase5d-settlements-repeat.json --verify-against examples/phase5d/settlements-dev0.json
```

## 성능과 한계

```sh
python -B -m cProfile -o ../../work/phase5d-actions.prof -m civsim collective --seed 0 --years 30 --actions on --out ../../work/phase5d-actions-profile
```

30년 전체 원장 저장에 프로파일러 기준 22.962초·약 1,313만 호출이 관측됐다. 중첩 호출을 포함한 누적 시간은 상태·후보 복사 7.304초, 정상 내각 승인 재계산 3.986초였다. 다른 프로세스와 CPU를 공유한 측정이다. 구역·집단 수와 관측 기간을 늘리면 의사결정·회계 이중 검사, 기록 복사와 직렬화가 함께 늘어난다. 다른 규모로의 처리 속도 외삽은 검증하지 않았다.

표준 결과는 사전 설정한 합성 세계와 200년에 한정된다. 행동 종류별 강제 노출에서 추정한 독립 평균 인과 효과, 실제 개인의 참여 동기·노동 경력, 지역 간 확산, 다른 행동 문턱과 200년 이후의 안정성은 검증하지 않았다. 선거 대안의 고정 경로 진단과 경제를 함께 되먹임한 소규모 추가 실험의 범위는 별도 표기했다. 저장소와 PR 상태는 GitHub에서 조회했다. Context7에서 CPython의 dataclass 복사 동작을 확인해 한 해만 분기한 상태가 원본을 바꾸지 않도록 했다. 시스템 순환을 기존 tldraw 보드에 추가했고, UI 범위가 없어 Figma 작업은 수행하지 않았다. [공식 Python 문서](https://docs.python.org/3.12/library/dataclasses.html#dataclasses.replace) · [시스템 설계도](https://www.tldraw.com/f/0bUzL9_Y5-sq8tpY7HMM6)
