# 6.0C1 후속 · 양측 서명과 민간 약속의 이행 검증

기준은 PR #17 커밋 `2114ca31af3b72d6b0147feb2ffe91e7770d8517`이다. 이 단계의 새 정책은 기존 민간 협의 이후에 당사국이 약속에 서명할지 결정하고, 약속 만기에 확인한 실적을 다음 서명 판단에 사용하는 선택 사항이다. PR #17의 평시 보급·식사 장부와 민간 분쟁 판정은 기존 진입점에서 읽는다. 경제 모형이나 당해의 통행 제한으로 약속 판단을 역입력하지 않는다. [서명·이행 수식](civic-pledges64.md) · [연구 결과](civic-pledges64-results.md)

## 원래 요청과 제출물

| 요청 | 구현·검증 범위 |
|---|---|
| 1. 지속되는 전략적 주둔 | 미구현. 기존 주소지·평시 복무 경로는 호환성 대조의 입력이다. |
| 2. 민간 분쟁과 대응 | 부분 구현. 협의 수락 후 별도로 양측 서명, 무합의, 당사자별 이행·불이행·판정 불가, 이력이 바꾼 후속 서명을 기록한다. 군사 위기·국경 방어·추가 동원 선택은 미구현이다. |
| 3. 전시 동원과 재원 | 미구현. 새로운 전시 비용·준비 기간을 산출하지 않았다. |
| 4. 대조 실험 | 기존 자율 방위 경제를 고정한 민간 협의·약속 경로 및 같은 연초의 이력 사용/보류를 대조한다. 요청한 군사 B·C·D군 및 배치·동원 반사실은 미실행이다. |
| 5. 6.0C2 인터페이스 | 전투용 지역 상태는 미제공이다. 이 PR의 출력은 국가쌍별 민간 약속 원장이다. |
| 6. 호환성과 검증 | 기준 시드의 경제·민간 외교 원장 해시를 독립 대조하고 기존 인구·노동·창고·현금·도로·원조 예산을 재감사한다. 신규 약속 원장은 공공 지출·물자·신뢰 점수를 게시할 권한이 없다. |

## 실제로 바뀌는 결정

연초 Y에 이용하는 증거는 Y−1년의 확정된 민간 결산이다. 협의가 수락돼도 한쪽이 약속에 서명하지 않으면 양자 약속은 성립하지 않는다. 양쪽이 서명하면 통상·출국·입국 중 선택된 한 종류에 대해 두 의무국의 기준과 만기를 고정한다. 다음 결산에서는 의무국별 실적을 확인한다. 관측이 누락되거나 비교할 기회가 없는 경우 이행 판단을 유보한다. 만기 결산이 끝나지 않은 약속은 후속 결과와 구분한다.

새 이력은 같은 상대와 같은 종류의 차기 약속에 관한 **서명·보류**를 바꿀 수 있다. 협의를 수락한 시점에 자원·관계 점수·통행량을 만들어내는 분개는 없다. 이행 판정에 쓰인 실제 거래·이동량은 기존 경제가 만든 값이다. 따라서 서명 변화는 직접적인 모형 효과이지만 주민 섭취·교역·경제적 피해의 개선 효과를 식별할 수 없다. 개발 0~19와 검증 20~39는 과거부터 공개된 서로 다른 시드 집단이다.

## 실행 API와 민간 데이터

```python
from civsim.civic_followup64 import run

for economic_ledger, consultation_pairs, pledge_pairs in run(0, 5, consult=True, pledges=True):
    year = economic_ledger["year"]
    civil_pair = consultation_pairs[0, 1]
    undertaking = pledge_pairs[0, 1]
```

`pledges=False`가 기본이며 세 번째 반환값은 `None`이다. 앞의 두 값은 PR #17의 원래 경제·민간 외교 기록이다. `pledges=True`일 때 세 번째 값은 두 국가 ID의 오름차순 튜플로 찾는 연간 상태다. 명령줄은 동일한 내용을 JSON Lines로 내보낸다. 파일 한 줄에 `schema="civil-pledges/1"`, 시드, 연도, 협의/약속 옵션, 쌍별 약속 목록을 넣는다. 실체결, 의무의 만기 결산, 회고적 가설의 차이를 구분해 읽어야 한다. [실행 코드](../civsim/civic_followup64.py) · [등록부 흐름도](https://www.tldraw.com/f/0bUzL9_Y5-sq8tpY7HMM6)

## 기존 결과를 보존했는지 확인한 방법

40개 시드 모두에서 약속을 끈 협의 경로를 초기 지도부터 200년간 다시 실행했다. 50·100·200년에서 초기 상태, 누적 경제 원장, 누적 기존 민간 외교 원장을 대조한 120개 지점이 PR #17과 일치했다. 시드 0·20은 관측 전용 경로와 약속 사용 경로에서도 새로 실행했다. 두 시드의 400개 연도에서 약속 사용 전후의 기존 경제·민간 외교 원장이 각각 바이트 단위로 일치했다. 두 시드의 약속 원장 해시 6개도 저장된 민간 자료로 별도 생성한 연구 결과와 같았다. [실시간 재생 확인서](../examples/phase6c1-followup/compatibility.json)

독립 검산 범위는 44경로·8,800세계연도, 281,600지역연도, 70,400국가연도다. 원래 지리와 직전 연말로 인구·노동·재화·창고·현금·도로 원장을 연결했고 공여 예산 계정 70,400건과 실제 원조 송장 1,762건을 검사했다. 검산기는 8개 작업 프로세스에서 325.719초가 걸렸다. 40개 시드의 **새 약속**에 대한 독립 반복은 PR #17의 확인된 민간 연간 입력에서 실행했다. 원래 경제부터 약속 출력까지의 200년 경로를 약속 기능을 켜고 전 구간 다시 실행한 시드는 0·20이다.

첫 44경로 측정 후 시드 0·20의 새 약속 해시 6개를 별도 재생해 첫 확인서에 추가했다. 325.719초는 첫 44경로의 시간이다. 이후 최종 검산기를 새 프로세스에서 실행해 같은 44개 경로와 모든 해시를 한 번에 계산한 시간은 328.976초였다. 실행 시간을 제외한 두 확인서의 나머지 필드는 전부 일치했다. [독립 검산 결과](../examples/phase6c1-followup/compatibility-repeat.json)

이전 버전의 값은 별도로 확인했다. 기준 커밋에 있던 추적 파일 660개의 변경·삭제·이름 변경이 0건이다. 저장된 과거 실행 예제 8개에는 공식 검증 명령을 실행해 모두 종료 코드 0을 얻었다. 과거 모든 조합을 1.0부터 다시 모의한 결과로 해석할 수는 없다. [원본 예제별 명령과 해시](../examples/phase6c1-followup/archive-checks.txt)

## 실행 명령과 증거

로컬 환경은 Windows, Python 3.12.14였다. 첫 명령은 시드 0에서 5개 JSON 행과 매년 28개 쌍을 출력했다. 기준 테스트 373개는 기준 커밋에서 `benchmarks/`와 `tests/` 아래의 테스트 모듈을 열거해 실행했다. 모두 통과했고 실행 시간은 101.795초였다. 최종 전수 실행에서는 기존 373개와 신규 29개를 합쳐 402개가 81.599초에 통과했다. 연구 자료·독립 반복을 만드는 명령은 결과 보고서에 있다. 새 출력 디렉터리를 지정하면 기존 원장을 보존하면서 재현할 수 있다. [기준 373개 로그](../examples/phase6c1-followup/pinned-tests.txt) · [최종 전체 테스트 로그](../examples/phase6c1-followup/final-tests.txt) · [원자료 및 독립 반복 명령](civic-pledges64-results.md)

```text
python -B -m civsim.civic_followup64 --seed 0 --years 5 --pledges
python -B -X utf8 -m experiments.verify_civic_off64 --workers 8 --out examples/phase6c1-followup/compatibility.json
python -B -X utf8 -m experiments.verify_civic_off64 --workers 8 --out ../../work/phase6c1-followup-final-independent.json
python -B -X utf8 -m experiments.verify_civic_off64 --compare-release examples/phase6c1-followup/compatibility.json ../../work/phase6c1-followup-final-independent.json --out examples/phase6c1-followup/compatibility-repeat.json
python -B -m unittest tests.test_civic_pledge_publication64 -v
python -B -m unittest discover -v
git diff --diff-filter=MDTR --name-status 2114ca3 HEAD
```

공동 서명 1,772건 중 만기에 양측 이행을 확인한 것은 232건이다. 예를 들어 시드 0의 6년차에는 1국의 수출 거절량 61이 이전 약속의 상한 41을 넘었다. 반대 방향은 시도가 0이어서 4국의 이행은 판정할 수 없었다. 4국은 1국의 확인된 불이행을 반영해 재서명을 보류했다. 같은 연초에 이력만 가리면 두 나라 모두 서명했다. 기회 변화에 따라 거절 총량도 변하므로 이 결과로 정부의 의도를 알아낼 수는 없다. [개발 표본의 국가쌍별 양쪽 결정](../examples/phase6c1-followup/pledges/dev/same-opening-cases.json)
