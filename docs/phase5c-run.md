# 5.0C 실행 및 검증 기록

기준은 PR #9의 `b7c2aaacbb6d95f6788b398b4152056bf8b7325f`다. `0ccc34f`에서 비교군·평가 방법을 정했고, 선호·선거·현물세·지출 재량과 측정 코드는 `38612aa932e686846264b61ff6bdc9948e4412ef`에서 고정했다. 그 후 독립 검증 시드 20~39를 열었다. 플랫폼은 Windows와 CPython 3.12.14다. 아래 명령의 `python`은 해당 실행 파일이다. [비교 계획](phase5c-protocol.md) · [모형 수식](competition-rules.md)

## 자동 검사와 실물 원장

최종 Windows 전체 테스트는 **222/222 통과, 47.126초**였다. 기준 테스트 198개에 24개를 추가했다. 각 결과 파일을 직접 읽는 마지막 게시 검사는 두 표본의 600개 관찰점, 20개 결과 파일의 SHA-256, 두 반복 영수증, 과거 5.0B 활성군 해시를 대조한다. 별도 실행한 이 게시 검사는 0.047초에 통과했다. [전체 테스트 출력](phase5c-tests.txt)

기준 커밋을 분기했을 때 기존 전체 테스트 **198개가 32.108초에 통과**했다. 동결 직전 새 규칙·통합·세율·실험 집계의 집중 테스트는 18개가 4.259초에 통과했다. 개발 도중 첫해의 미분류 주민을 대표점수 분모에서 빠뜨린 검산을 단위 테스트가 발견했다. 선거 규칙의 초기 미참여 인원을 포함해 분모를 대조하도록 검산기를 고쳤다. 두 내각의 인수인계 전후에는 지역 및 국가의 전체 연말 스냅샷, 공공 창고, 도로 설비와 허용 용량도 전년과 대조한다. [최종 테스트별 로그](phase5c-tests.txt) · [과거 자료 재생 범위](phase5c-legacy.md)

```sh
python -B -m unittest discover -q
python -B -m unittest tests.test_competition_rules tests.test_competition_integration tests.test_tax_policy5c tests.test_phase5c_study -q
python -B -m unittest discover -v
python -B -m civsim competition --seed 0 --years 9 --per-nation 2 --arm D --out examples/phase5c/seed0-elections
python -B -m civsim verify examples/phase5c/seed0-elections
python -B -m civsim analyze examples/phase5c/seed0-elections
```

시드 0의 9년 공개 원장은 작은 재생 사례로 국가당 2개 지역을 사용했다. 75,029명에서 82,017명으로 바뀌었고 누적 식량 필요 697,126식 중 30,177식이 부족했다. 16회 국가 선거에서 첫 내각 설치 8회, 당선 세력 간 교체 3회가 발생했다. `years.jsonl`은 2,606,491바이트이며 실제 재생 SHA-256은 `cd14aa60b4cd37f867de29c9eb86fc13c8d3360fb0d97465349bcd0b1145c664`다. 주 실험은 48×32 타일·8국·국가당 4지역을 사용한다. [재생 가능한 공개 원장](../examples/phase5c/seed0-elections)

## 대조군과 반사실

동결 뒤 단년 원장의 선거 누계도 독립 달력과 대조하는 검사를 추가했다. 이 검사는 기준 연도의 선거가 100번 많게 기재된 장부를 거부한다. 주 실험의 선호·내각 선택·선거 및 경제 계수는 동결본을 유지했다. 개발 20개 경제 경로를 고정한 별도 분석은 아래 명령으로 실행해 200년 원장 20개 모두 5.0B 보관 해시에 일치했다. Windows에서 임시 결과를 하드 링크로 게시하려던 첫 시도는 파일 권한으로 실패해 새 경로에 원자적으로 이름을 바꾸는 방식으로 다시 실행했다. [고정 경제 경로의 결과](../examples/phase5c/preferences-dev.json)

```sh
python -B -X utf8 -m experiments.preferences5c --out examples/phase5c/preferences-dev.json --seeds 20 --years 200 --workers 4
```

각 조합은 200년 연속 실행하며 50·100·200년 지점에 결과를 기록한다. 개발과 독립 검증을 서로 다른 디렉터리에 쓰고, 반복 실행의 결과 표와 원장 해시를 첫 실행과 비교한다. `execution.json`의 소요 시간은 각 실행에만 해당한다. 재실행 시 출력 위치를 새 디렉터리로 바꿔야 한다. [40개 시드 비교 결과](phase5c-results.md) · [내각과 세율을 하나씩 바꾼 검산 명령 및 결과](competition-forks5c.md)

```sh
python -B -m experiments.phase5c --sample dev --out examples/phase5c/study/dev --workers 8
python -B -m experiments.phase5c --sample holdout --out examples/phase5c/study/holdout --workers 8
python -B -m experiments.phase5c --sample dev --out ../../work/phase5c-replay-dev --workers 8 --verify-against examples/phase5c/study/dev
python -B -m experiments.phase5c --sample holdout --out ../../work/phase5c-replay-holdout --workers 8 --verify-against examples/phase5c/study/holdout
```

## 성능과 확장 한계

본 실험에서 40개 시드×5군×200년을 실행했고, 새 프로세스에서 40,000세계연도를 다시 계산했다. 개발·검증 첫 실행은 각각 679.882초·677.991초, 반복은 478.015초·486.056초였다. 연도별 누적 원장에서 추출한 **600/600 체크포인트와 20/20 결과 파일**이 일치했다. [개발 반복 영수증](../examples/phase5c/study/replay-dev.json) · [검증 반복 영수증](../examples/phase5c/study/replay-holdout.json)

```sh
python -B -m cProfile -o ../../work/phase5c-seed0.prof -m civsim competition --seed 0 --arm D --years 30 --out ../../work/phase5c-profile-seed0
```

개발·검증 실험과 같은 기계에서 측정한 30년 전체 저장 실행은 프로파일러 집계 33.950초와 약 1,279만 함수 호출을 기록했다. 스냅샷과 후보 사본을 만드는 `deepcopy`의 누적 시간은 13.820초, 승인 계산은 7.602초, 연간 재정 검산은 6.592초였다. 중첩된 호출의 누적 시간은 서로 더할 수 없다. 세계당 지역·정파·정책 후보가 늘면 집단별 선호와 세력별 기여, 입법 후보의 계산·복사·재검산 및 원장 크기가 증가한다. 이 시간에는 다른 프로세스와의 CPU 경쟁 및 프로파일링 부하가 있다. 대규모 국가 수나 새 정치 제도에 대한 속도는 측정하지 않았다.

## 해석의 범위

가상 세계의 대표점수에는 개별 투표권·연령·소득 정보가 없다. 4년 임기, 21석, 네 강령, 세율, 참여 문턱, 현직 성과 계수와 경제 손실 한도는 사전에 정한 모형 가정이다. 의석 최다 세력이 정부를 구성하며 연정이나 과반 협상은 모형에 없다. 집권 직후 사업 평가에서는 새 내각을 대입해 지지 기반을 다시 계산한다. 직전 내각 시기의 성과가 이 평가에도 남을 수 있다. 단년 내각 분기는 실제 교체 연초의 국소 효과이고, 장기 짝 비교에는 이후 경제와 정치가 서로 영향을 준 모든 효과가 들어간다. 200년 이후의 안정성·다른 선거제나 계수에 대한 민감도·현실 정치 예측력은 검증하지 않았다.

GitHub에서 기준과 결과 PR을 확인했다. Context7에서 CPython의 `dataclasses.replace` 동작을 확인해 원래 세계를 전진시키지 않고 한 해를 분기하는 데 적용했다. tldraw에는 관측·집단 선호·선거·예산 승인·실물 집행의 순환을 그렸다. UI 작업은 이번 범위에 없어 Figma는 사용하지 않았다. [Python 공식 문서](https://docs.python.org/3.12/library/dataclasses.html#dataclasses.replace) · [tldraw 정치 경쟁 설계도](https://www.tldraw.com/f/0bUzL9_Y5-sq8tpY7HMM6)
