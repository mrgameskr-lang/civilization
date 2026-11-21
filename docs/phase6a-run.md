# 6.0A 재생·검증 및 실행 환경

Windows의 CPython 3.12.14에서 표준 라이브러리로 실행했다. 기준은 PR #11 `a4721bd`, 실험 계획은 `d271693`, 독립 표본을 열기 전에 고정한 엔진·실험기는 `5ff36abb8ff1a77018cce40cdde81cd4cc1f29f7`이다. 4군은 동일 시드·지도·국가·초기 창고·정치 상태로 출발한다. 결과를 다시 생성할 때는 아래 명령의 출력만 새 경로로 바꾼다.

## 전체 원장 재생과 상속 기록

```sh
python -B -m experiments.check_stack6a --out examples/phase6a/pr-stack.json --workers 3
python -B -m experiments.verify_archives31 --workers 4
python -B -m unittest -q tests.test_aid_opinion6 tests.test_diplomacy_integration tests.test_diplomatic_flows tests.test_phase6a_study
python -B -m civsim diplomacy --arm D --seed 0 --years 6 --out examples/phase6a/seed0-diplomacy
python -B -m civsim verify examples/phase6a/seed0-diplomacy
python -B -m civsim analyze examples/phase6a/seed0-diplomacy
```

- 고정 기준 8개를 각각 독립 테스트했다. #4부터 순서대로 91·115·120·149·178·198·222·242개가 통과했다. 각 통합 예행의 Git 트리는 해당 커밋의 트리와 같았다. [PR별 검산](integration6a.md)
- 이전 국가 엔진의 280개 서로 다른 시드·규칙 경로를 재실행해 400개 체크포인트의 초기·연간 해시를 맞췄다. 1.0~5.0D의 전체 JSON 원장이 있는 8개 예제는 초기 세계 8건 및 연간 173행을 바이트 단위로 재현했다. 모든 과거 단계의 모든 장기 실험을 재계산한 수치는 아니다. [이전 원장별 재생](diplomatic-flows6a.md)
- `git ls-tree -r --name-only a4721bd examples`로 센 상속 파일은 184개다. `git diff --name-status a4721bd -- examples ':(exclude)examples/phase6a/**'`의 출력은 비어 있었다.
- 규칙 동결 직전 집중 시험은 17개 통과(5.043초). 양측 서명과 종료, 운반비, 국경 방향, 정치 피드백, 같은 연초 분기 및 변조 탐지 검증을 후속 시험에서도 실행했다.
- 6.0A의 공개 6년 원장은 5,307,771바이트이며 SHA-256이 `d4ee8225688cde4dc82d967d450ca3f6f2f79769164e4762ee9583630de11507`로 재현됐다. 세계 인구는 75,029명에서 77,827명으로 변했고 누적 미충족 식량은 32,474였다. 원조 발송 489에서 취급 손실 21을 제외해 468이 입고됐다. 공여 창고들은 운임 51도 지급했다. 6년차에 유효한 협정은 2개였다. [초기 세계와 원장](../examples/phase6a/seed0-diplomacy)

## 성능

```sh
python -B -m cProfile -o ../../work/phase6a-diplomacy.prof -m civsim diplomacy --seed 0 --arm D --years 30 --out ../../work/phase6a-profile
```

32개 지역, 28개 국가 쌍의 30년 D군 전체 원장을 저장했다. 프로파일러가 계측한 약 1,937만 호출의 시간은 16.038초였다. 중첩 호출을 포함한 누적 시간은 상태 깊은 복사 7.791초, 연간 재정 감사 4.415초, 외교 규칙 감사 1.488초, JSON 정규 직렬화 1.184초였다. 이 시간들은 서로 겹친다. 국경이 없는 쌍도 해마다 보관하므로 외교 관측 행 수는 국가 수의 제곱에 비례한다. 하루 단위 운송, 간접 경유·환적, 다른 지도 크기의 처리 속도는 이번 실행에서 측정하지 않았다.

## 도구와 재현 조건

GitHub에서 PR 계보·CI를 조회하고 별도 기능 브랜치를 게시했다. tldraw의 기존 시스템 도면에 연초 협의, 실제 국경 정산, 사후 국내·양자 반응의 순환을 추가했다. Context7에서 CPython의 `gzip.GzipFile`의 헤더 동작을 확인했다. 이름과 수정 시간을 고정해 압축 표도 재실행 시 바이트 단위로 대조한다. UI 작업이 없는 이번 단계에서는 Figma를 사용하지 않았다. [tldraw 시스템 도면](https://www.tldraw.com/f/0bUzL9_Y5-sq8tpY7HMM6) · [Python gzip 공식 문서](https://docs.python.org/3.12/library/gzip.html#gzip.GzipFile)

양자 선택 수식·의무·신뢰 갱신 및 직접 정치 반응은 [외교 수식](diplomatic-rules.md)에, 공여·수혜 창고와 국경별 보존식은 [실물 계산](diplomatic-flows6a.md)에 있다. [사전 계획](phase6a-protocol.md) · [표본별 수치·개입 결과](phase6a-results.md) · [자료 사전](../examples/phase6a/study/README.md)
