# 5.0B 검증 기록

기준은 [PR #8](https://github.com/mrgameskr-lang/civilization/pull/8)의 `739a168`이다. `cbc3bc0`에서 대조군과 측정 방법을 정하고 `38e0699`에서 5.0A 도로 보고 지표를 수정했다. 정치 규칙은 독립 검증 표본을 열기 전 `869cbad`에서 고정했다. 플랫폼은 Windows 11 x64와 번들 CPython 3.12.14다.

## 실제 실행한 명령

저장소 루트를 기준으로 적었다. 각 실행과 반복에 다른 출력 위치를 사용했다. 결과 디렉터리나 사례 파일을 다시 생성할 때는 새 경로가 필요하다.

```sh
python -B -m unittest discover -q
python -B -m unittest tests.test_capacity5 tests.test_phase5_study -v
python -B -m unittest discover -v
python -B -m experiments.verify_archives31 --workers 4
python -B -m civsim politics --seed 0 --feedback on --years 3 --out examples/phase5b/seed0-feedback
python -B -m civsim verify examples/phase5b/seed0-feedback
python -B -m civsim analyze examples/phase5b/seed0-feedback
python -B -m cProfile -o ../../work/phase5b-seed0.prof -m civsim politics --seed 0 --feedback on --years 30 --out ../../work/phase5b-profile-seed0
```

- 기준 커밋의 전체 테스트는 178/178, 17.658초였다. 연도별 정치 반응, 당해와 차년 도로 용량, 원장 위변조, 저장 재생, 실제 경제 해시와 정치 지표의 분모를 검사하는 테스트를 추가했다. [최종 테스트별 로그](phase5b-tests.txt)
- 시드 0의 통합 재정·정치 개입 3년 공개 예제는 시작 인구 75,029명, 마지막 인구 75,731명, 누적 부족 식량 21,205, 구호 94였다. 경제 권고와 다른 실제 승인이 세 번 있었다. 연간 원장 1,410,951바이트의 재생 SHA-256은 `d4784560f71c020b6aeafbe482af64315fb8976325c5470ba0d4bd62dbe96b52`이다. [예제 재생 파일](../examples/phase5b/seed0-feedback)
- 5.0A 도로 교정에서 32,000세계연도를 재계산했다. 480개 보관 체크포인트의 누적 경제 원장 해시와 교정 전후 5.0A 원장이 일치했다. 시드 28·30의 회귀 테스트는 해당 간선의 유지·건설과 차년 용량을 직접 확인한다. [물리 장부 검증과 교정 명령](phase5b-capacity.md)
- 1.0~3.0의 기존 280개 경로·400개 체크포인트를 재생해 기초·연간 해시가 일치했다. 저장된 1.0·2.0·3.0·4.0·5.0A 상세 실행 5개도 각각 재생했다. PR #8에 있던 기존 예제 파일 74개의 Git 변경은 0개였다. 이번 작업의 전체 3.1 정책 격자 재실행 횟수는 0회다.

## 실험 시간과 병목

추가로 `python -B -X utf8 -m experiments.phase4 --seeds 20 --horizons 50,200 --workers 4 --out ../../work/phase5b-legacy4`를 실행했다. 261.039초 동안 기존 4.0의 네 처리군 80경로·16,000세계연도를 재생했다. CSV 다섯 개와 사례 JSON이 보관된 여섯 파일과 바이트 단위로 일치했다.

변조 실험에서 관측군의 정치 블록을 통째로 제거하거나, 사용되지 않는 기초 집단 인원·구호 합계만 고친 연간 장부가 개별 검사 일부를 통과했다. 연도 간 정치 블록 존재 여부, 직전 노동과 대표 인원, 구호 송장 합계·공공 운임 재기표를 확인하도록 감사를 보강했다. 상세 파일 전체 재생도 정치 증거 한 필드의 변경을 거절했다. 이 검사들은 승인 규칙·물리 결과를 바꾸지 않는다. [통합 테스트](../tests/test_politics5b.py)

시드 0의 30년 개입 상세 원장 저장을 프로파일링했다. 11,033,411회 호출, 프로파일러 집계 35.202초였고 연간 전이는 누적 29.114초였다. 중첩된 장부를 독립 복사하는 `deepcopy`에 누적 15.293초, 후보 재평가 `prioritize`에 7.783초, 도로망 초기화에 3.146초가 걸렸다. 누적 함수 시간은 서로 겹친다. 이 프로파일은 백그라운드 비교 실험과 함께 실행했다. 확장 비용으로는 지역·연도별 후보 기여 목록과 기초·기말 기억을 직렬화·복사하는 작업이 크다. 서로 다른 지도 규모에서의 처리량은 이번에 측정하지 않았다.

## 범위

로컬 최종 전체 실행은 **198/198 통과, 53.379초**였다. 기존 178개와 신규 20개를 포함한다. [전체 로그](phase5b-tests.txt)

정치 비교는 40개 시드 × 두 처리군 × 200년으로 16,000세계연도였고, 새 프로세스에서 다시 16,000세계연도를 실행했다. 240개 체크포인트 및 두 표본의 결과 파일 22개가 일치했다. 경제만 추출한 관측군의 120개 누적 원장 해시는 모두 5.0A 통합군의 기존 해시와 같았다. 같은 연초 정책 분기의 실물 장부와 실행 명령은 [시드 0 반사실](political-forks5.md), 두 표본의 정확한 명령·경과시간·시드별 원자료는 [비교 실험](phase5b-results.md)에 있다.

집단의 인원은 실제 노동 배정에서 나온다. 생산자가 현물세 부담을 지고 주민이 인구 비례로 구호를 체감한다는 가정은 실제 개별 납세·수혜 자료로 보정되지 않았다. 지지·불만과 정치 점수는 모형 지수다. 기초 경제 메뉴는 5.0A 통합 정책으로 고정했고, 다른 제도나 선거, 정권 교체, 정부별 세율 변경, 200년 이후 안정성은 실험하지 않았다. [비교 실험 결과](phase5b-results.md) · [정치 반응 수식](political-rules.md)

GitHub로 기준 PR을 조회하고 검토 브랜치를 관리했다. Context7에서 CPython 3.12의 `copy.deepcopy` 중첩 객체 처리 방식을 확인했다. tldraw에 초기 상태, 경제 후보, 개입 여부, 실제 집행, 집단 반응, 이듬해 상태를 연결한 도식을 추가했다. Figma 작업은 UI 범위 밖이어서 수행하지 않았다. [CPython 공식 문서](https://docs.python.org/3.12/library/copy.html) · [tldraw 보드](https://www.tldraw.com/f/0bUzL9_Y5-sq8tpY7HMM6)
